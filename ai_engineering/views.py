import hashlib
import json

from django.db import IntegrityError, transaction
from django.db.models import Avg, Sum
from django.db.models.functions import Coalesce
from django.http import Http404
from django.utils import timezone
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminUser, IsProducer
from products.models import Product, ProductBatch, default_discount_percent_for_grade

from ai_engineering.models import (
    AIModelVersion,
    ActiveModel,
    BatchGradeChangeEvent,
    ExportJob,
    InferenceInputImage,
    InferenceRequestLog,
    IntakeCommitRequest,
    ProducerOverrideEvent,
)
from ai_engineering.permissions import IsAIEngineerOrAdmin, IsExportOwnerOrAdmin
from ai_engineering.serializers import (
    AIModelVersionSerializer,
    ExportJobRequestSerializer,
    ExportJobSerializer,
    InferenceRequestLogSerializer,
    ModelActivationSerializer,
    ModelRollbackSerializer,
    ModelUploadSerializer,
    ModelUploadWebFormSerializer,
    BatchGradeEditSerializer,
    ProducerOverrideEventSerializer,
    ProducerOverrideSerializer,
    IntakeCommitSerializer,
    ProducerPredictSerializer,
)
from ai_engineering.services.export import create_retraining_export
from ai_engineering.services.grading import GRADING_POLICY_VERSION, compute_authoritative_grade
from ai_engineering.services.inference_client import (
    InferenceClient,
    InferenceClientError,
    InferenceClientNotImplementedError,
)
from ai_engineering.services.lifecycle_client import LifecycleClient, LifecycleClientError
from ai_engineering.services.recommendation import build_recommendation

WEIGHTED_F1_THRESHOLD = 0.85
ROTTEN_RECALL_THRESHOLD = 0.80


def _safe_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_commit_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _legacy_unallocated_lot_quantity(product: Product) -> int:
    active_batch_stock = ProductBatch.objects.filter(
        product=product,
        is_active=True,
    ).aggregate(total=Coalesce(Sum("stock_quantity"), 0))["total"]
    return max(int(product.stock_quantity) - int(active_batch_stock or 0), 0)


def _commit_intake_transaction(
    *,
    producer,
    commit_payload: dict,
    require_existing_acceptance: bool = False,
    create_override_event: bool = True,
    allow_legacy_quantity_fallback: bool = False,
):
    with transaction.atomic():
        product = Product.objects.select_for_update().filter(
            pk=commit_payload["product_id"],
            producer=producer,
        ).first()
        if not product:
            raise ValueError("Product not found for this producer.")

        idempotency_key = str(commit_payload["idempotency_key"])
        idempotency_row = IntakeCommitRequest.objects.select_for_update().filter(
            producer=producer,
            idempotency_key=idempotency_key,
        ).first()
        request_hash = _build_commit_hash(commit_payload)

        if idempotency_row:
            if idempotency_row.request_hash != request_hash:
                raise ValueError("idempotency_key has already been used with a different payload.")

            if idempotency_row.batch_id:
                return idempotency_row.batch, True
        else:
            idempotency_row = IntakeCommitRequest.objects.create(
                producer=producer,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )

        lot_quantity = _safe_int(commit_payload.get("lot_quantity"))
        if lot_quantity is None and allow_legacy_quantity_fallback:
            lot_quantity = _legacy_unallocated_lot_quantity(product)

        if lot_quantity is None or lot_quantity <= 0:
            raise ValueError("lot_quantity must be greater than 0.")

        allocate_from_unbatched = bool(commit_payload.get("allocate_from_unbatched"))
        if allocate_from_unbatched:
            available_unbatched = _legacy_unallocated_lot_quantity(product)
            if lot_quantity > int(available_unbatched):
                raise ValueError(
                    "Lot quantity exceeds available ungraded stock. "
                    "Lower lot quantity or disable existing-stock allocation."
                )

            new_stock_total = max(int(product.stock_quantity) - lot_quantity, 0)
            new_unbatched_total = max(int(product.unbatched_stock_quantity) - lot_quantity, 0)
            Product.objects.filter(pk=product.pk).update(
                stock_quantity=new_stock_total,
                unbatched_stock_quantity=new_unbatched_total,
            )
            product.stock_quantity = new_stock_total
            product.unbatched_stock_quantity = new_unbatched_total

        grade_source = commit_payload["grade_source"]
        inference_log = None
        grade = None
        discount_percent = 0

        if grade_source == "ai":
            inference_log_id = commit_payload.get("inference_log_id")
            inference_log = InferenceRequestLog.objects.select_for_update().filter(
                pk=inference_log_id,
                producer=producer,
            ).first()

            if not inference_log:
                raise ValueError("Inference log not found.")
            if not inference_log.product_id:
                raise ValueError("AI Scan is not linked to a persistent product.")
            if inference_log.product_id != product.id:
                raise ValueError("Inference log does not match the selected product.")
            if (
                inference_log.scan_mode != InferenceRequestLog.ScanMode.BATCH_INTAKE
                and not allow_legacy_quantity_fallback
            ):
                raise ValueError("Inference log is not from batch intake mode.")

            existing_batch = ProductBatch.objects.filter(inference_log=inference_log).first()
            if existing_batch:
                idempotency_row.batch = existing_batch
                idempotency_row.save(update_fields=["batch"])
                return existing_batch, True

            if inference_log.committed_at:
                raise ValueError("A batch has already been created for this scan.")

            if require_existing_acceptance:
                latest_override = inference_log.overrides.filter(
                    producer=producer
                ).order_by("-created_at").first()
                if not latest_override or not latest_override.accepted_recommendation:
                    raise ValueError("Recommendation must be accepted before creating a batch.")
            elif create_override_event:
                ProducerOverrideEvent.objects.create(
                    inference_log=inference_log,
                    producer=producer,
                    accepted_recommendation=True,
                )

            grade = inference_log.authoritative_grade
            discount_percent = default_discount_percent_for_grade(grade)

        elif grade_source == "manual":
            manual_grade = commit_payload.get("manual_grade")
            manual_reason = (commit_payload.get("manual_reason") or "").strip()
            if not manual_grade or not manual_reason:
                raise ValueError("manual_grade and manual_reason are required for manual commits.")

            grade = manual_grade
            discount_percent = default_discount_percent_for_grade(grade)
        else:
            raise ValueError("grade_source must be either 'ai' or 'manual'.")

        batch = (
            ProductBatch.objects.select_for_update()
            .filter(
                product=product,
                grade=grade,
            )
            .order_by("-is_active", "created_at")
            .first()
        )

        if batch:
            batch.base_price = product.price
            batch.discount_percent = discount_percent
            batch.stock_quantity = int(batch.stock_quantity) + lot_quantity
            batch.is_active = True
            batch.save()
        else:
            batch = ProductBatch.objects.create(
                product=product,
                grade=grade,
                stock_quantity=lot_quantity,
                base_price=product.price,
                discount_percent=discount_percent,
                inference_log=inference_log,
                is_active=True,
            )

        if inference_log:
            inference_log.committed_at = timezone.now()
            inference_log.save(update_fields=["committed_at"])

        idempotency_row.batch = batch
        idempotency_row.save(update_fields=["batch"])

        return batch, False


def _activation_gate_errors(model_version: AIModelVersion):
    manifest = model_version.manifest_json or {}
    metrics = manifest.get("metrics", {})
    artifacts = manifest.get("artifacts", {})

    errors = []

    weighted_f1 = metrics.get("weighted_f1")
    try:
        weighted_f1_value = float(weighted_f1)
    except (TypeError, ValueError):
        weighted_f1_value = None
    if weighted_f1_value is None or weighted_f1_value < WEIGHTED_F1_THRESHOLD:
        errors.append(f"weighted_f1 must be >= {WEIGHTED_F1_THRESHOLD}")

    rotten_recall = metrics.get("rotten_recall")
    try:
        rotten_recall_value = float(rotten_recall)
    except (TypeError, ValueError):
        rotten_recall_value = None
    if rotten_recall_value is None or rotten_recall_value < ROTTEN_RECALL_THRESHOLD:
        errors.append(f"rotten_recall must be >= {ROTTEN_RECALL_THRESHOLD}")

    if not artifacts.get("classification_report"):
        errors.append("classification_report artifact is required")

    if not artifacts.get("confusion_matrix"):
        errors.append("confusion_matrix artifact is required")

    if not manifest.get("input_schema") or not manifest.get("output_schema"):
        errors.append("input_schema and output_schema are required")

    return errors


class HealthcheckView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class ModelListView(APIView):
    permission_classes = [IsAIEngineerOrAdmin]

    def get(self, request):
        lifecycle_client = LifecycleClient()
        if lifecycle_client.sync_enabled:
            try:
                payload = lifecycle_client.list_models()
                remote_results = payload.get("results", []) if isinstance(payload, dict) else []
                for item in remote_results:
                    if not isinstance(item, dict):
                        continue

                    model_name = item.get("model_name")
                    model_version = item.get("model_version")
                    if not model_name or not model_version:
                        continue

                    AIModelVersion.objects.update_or_create(
                        model_name=model_name,
                        model_version=model_version,
                        defaults={
                            "framework": item.get("framework", ""),
                            "manifest_json": item,
                            "checksum": item.get("checksum", ""),
                            "artifact_path": item.get("artifact_path", ""),
                        },
                    )
            except LifecycleClientError as exc:
                if not lifecycle_client.allow_local_fallback:
                    return Response(
                        {"detail": f"AAI lifecycle sync failed: {exc}"},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

        queryset = AIModelVersion.objects.all().order_by("-created_at")
        serializer = AIModelVersionSerializer(queryset, many=True)
        return Response(serializer.data)


class ModelUploadView(generics.GenericAPIView):
    permission_classes = [IsAIEngineerOrAdmin]
    serializer_class = ModelUploadWebFormSerializer

    def post(self, request):
        serializer = ModelUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        lifecycle_warning = None
        lifecycle_payload = {}

        lifecycle_client = LifecycleClient()
        if lifecycle_client.sync_enabled:
            try:
                lifecycle_payload = lifecycle_client.upload_model(
                    model_name=data["model_name"],
                    model_version=data["model_version"],
                    framework=data.get("framework", ""),
                    manifest_json=data.get("manifest_json"),
                    artifact_file=data.get("artifact_file"),
                )
            except LifecycleClientError as exc:
                if lifecycle_client.allow_local_fallback:
                    lifecycle_warning = str(exc)
                else:
                    return Response(
                        {"detail": f"AAI lifecycle upload failed: {exc}"},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

        try:
            model = AIModelVersion.objects.create(
                model_name=data["model_name"],
                model_version=data["model_version"],
                framework=data.get("framework", "") or lifecycle_payload.get("framework", ""),
                manifest_json=data.get("manifest_json", {}) or lifecycle_payload,
                checksum=data.get("checksum") or lifecycle_payload.get("checksum", ""),
                artifact_path=data.get("artifact_path") or lifecycle_payload.get("artifact_path", ""),
                uploaded_by=request.user,
            )
        except IntegrityError:
            return Response(
                {"detail": "Model name and version already exist."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        output = AIModelVersionSerializer(model)
        payload = output.data
        if lifecycle_warning:
            payload = {**payload, "lifecycle_sync_warning": lifecycle_warning}
        return Response(payload, status=status.HTTP_201_CREATED)


class ModelActivateView(APIView):
    permission_classes = [IsAIEngineerOrAdmin]

    def post(self, request):
        serializer = ModelActivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        model = AIModelVersion.objects.filter(
            model_name=serializer.validated_data["model_name"],
            model_version=serializer.validated_data["model_version"],
        ).first()
        if not model:
            raise Http404("Model version not found.")

        errors = _activation_gate_errors(model)
        if errors:
            return Response({"activation_errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        lifecycle_warning = None
        lifecycle_client = LifecycleClient()
        if lifecycle_client.sync_enabled:
            try:
                lifecycle_client.activate_model(
                    model_name=model.model_name,
                    model_version=model.model_version,
                )
            except LifecycleClientError as exc:
                if lifecycle_client.allow_local_fallback:
                    lifecycle_warning = str(exc)
                else:
                    return Response(
                        {"detail": f"AAI lifecycle activate failed: {exc}"},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

        ActiveModel.objects.filter(
            is_active=True,
            model_version__model_name=model.model_name,
        ).update(is_active=False)

        active_record = ActiveModel.objects.create(
            model_version=model,
            activated_by=request.user,
            is_active=True,
        )

        response_payload = {
            "detail": "Model activated",
            "activation_id": active_record.id,
            "model_name": model.model_name,
            "model_version": model.model_version,
        }
        if lifecycle_warning:
            response_payload["lifecycle_sync_warning"] = lifecycle_warning
        return Response(response_payload)


class ModelRollbackView(APIView):
    permission_classes = [IsAIEngineerOrAdmin]

    def post(self, request):
        serializer = ModelRollbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        model_name = serializer.validated_data["model_name"]
        target_version = serializer.validated_data.get("target_model_version")

        if target_version:
            target_model = AIModelVersion.objects.filter(
                model_name=model_name,
                model_version=target_version,
            ).first()
        else:
            current_active = ActiveModel.objects.filter(
                is_active=True,
                model_version__model_name=model_name,
            ).select_related("model_version").first()

            target_model = AIModelVersion.objects.filter(model_name=model_name)
            if current_active:
                target_model = target_model.exclude(id=current_active.model_version_id)
            target_model = target_model.order_by("-created_at").first()

        if not target_model:
            return Response(
                {"detail": "No rollback target available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lifecycle_warning = None
        lifecycle_client = LifecycleClient()
        if lifecycle_client.sync_enabled:
            try:
                lifecycle_client.rollback_model(
                    model_name=model_name,
                    target_model_version=target_model.model_version,
                )
            except LifecycleClientError as exc:
                if lifecycle_client.allow_local_fallback:
                    lifecycle_warning = str(exc)
                else:
                    return Response(
                        {"detail": f"AAI lifecycle rollback failed: {exc}"},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

        ActiveModel.objects.filter(
            is_active=True,
            model_version__model_name=model_name,
        ).update(is_active=False)

        record = ActiveModel.objects.create(
            model_version=target_model,
            activated_by=request.user,
            is_active=True,
        )

        response_payload = {
            "detail": "Rollback complete",
            "activation_id": record.id,
            "model_name": target_model.model_name,
            "model_version": target_model.model_version,
        }
        if lifecycle_warning:
            response_payload["lifecycle_sync_warning"] = lifecycle_warning
        return Response(response_payload)


class ProducerQualityPredictView(generics.GenericAPIView):
    permission_classes = [IsProducer]
    serializer_class = ProducerPredictSerializer

    def post(self, request):
        serializer = ProducerPredictSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        scan_mode = serializer.validated_data.get("scan_mode", InferenceRequestLog.ScanMode.PREVIEW)
        lot_quantity = serializer.validated_data.get("lot_quantity")
        aggregation_method = serializer.validated_data.get("aggregation_method", "median")

        product = None
        product_id = serializer.validated_data.get("product_id")
        if product_id is not None:
            product = Product.objects.filter(pk=product_id, producer=request.user).first()
            if not product:
                raise Http404("Product not found for this producer.")

        requested_model_version = serializer.validated_data.get("model_version")
        resolved_model_version = requested_model_version
        if not resolved_model_version:
            active_model = ActiveModel.objects.filter(is_active=True).select_related("model_version").first()
            if active_model:
                resolved_model_version = active_model.model_version.model_version

        uploaded_images = []
        primary_image = serializer.validated_data.get("image")
        if primary_image is not None:
            uploaded_images.append(primary_image)

        validated_images = serializer.validated_data.get("images") or []
        if validated_images:
            uploaded_images.extend(validated_images)

        # Some clients post repeated "images" keys through multipart form data.
        request_images = request.FILES.getlist("images")
        if request_images:
            uploaded_images = request_images

        image_obj = uploaded_images[0] if uploaded_images else None
        image_count = len(uploaded_images) if uploaded_images else 1
        image_path = image_obj.name if image_obj is not None else ""
        close_after_predict = False

        # For saved products, allow scans to reuse the existing product image.
        if image_obj is None:
            if not product:
                return Response(
                    {
                        "detail": (
                            "Please upload an image, or save the product first and run "
                            "a batch-linked scan from the edit page."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not product.image:
                return Response(
                    {"detail": "This product does not have a saved image to scan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            product.image.open("rb")
            image_obj = product.image.file
            image_path = product.image.name
            close_after_predict = True
            image_count = 1

        client = InferenceClient()
        try:
            result = client.predict(
                image=image_obj,
                producer_id=request.user.id,
                product_id=product.id if product else None,
                model_version=resolved_model_version,
            )
        except InferenceClientNotImplementedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except InferenceClientError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        finally:
            if close_after_predict:
                try:
                    image_obj.close()
                except Exception:
                    pass

        grade_result = compute_authoritative_grade(
            result["color_score"],
            result["size_score"],
            result["ripeness_score"],
            result.get("predicted_class"),
        )
        recommendation_result = build_recommendation(grade_result.grade, result["confidence"])

        ai_reported_grade = result.get("ai_reported_grade")
        mismatch = bool(ai_reported_grade and ai_reported_grade != grade_result.grade)

        xai_payload = {
            "score_breakdown": {
                "color": result["color_score"],
                "size": result["size_score"],
                "ripeness": result["ripeness_score"],
            },
            "grade_derivation": grade_result.derivation,
            "recommendation_derivation": recommendation_result.derivation,
            "model_reasoning": {
                "predicted_class": result["predicted_class"],
                "class_probabilities": result.get("class_probabilities", {}),
                "model_version": result["model_version_used"],
            },
            "transparency_refs": result.get("transparency_refs", []),
            "inventory_action": result.get("inventory_action", {}),
        }

        if isinstance(result.get("explanation_payload"), dict):
            xai_payload["provider_explanation"] = result["explanation_payload"]

        log = InferenceRequestLog.objects.create(
            producer=request.user,
            product=product,
            image_path=image_path,
            color_score=result["color_score"],
            size_score=result["size_score"],
            ripeness_score=result["ripeness_score"],
            confidence=result["confidence"],
            predicted_class=result["predicted_class"],
            ai_reported_grade=ai_reported_grade,
            authoritative_grade=grade_result.grade,
            recommendation_action=recommendation_result.action,
            explanation_payload=xai_payload,
            model_version_used=result["model_version_used"],
            latency_ms=result["latency_ms"],
            grading_policy_version=GRADING_POLICY_VERSION,
            ai_grade_mismatch=mismatch,
            scan_mode=scan_mode,
            lot_quantity=lot_quantity,
            image_count=image_count,
            aggregation_method=aggregation_method,
        )

        if uploaded_images:
            InferenceInputImage.objects.bulk_create(
                [
                    InferenceInputImage(
                        inference_log=log,
                        image_path=img.name,
                        ordinal=index,
                    )
                    for index, img in enumerate(uploaded_images, start=1)
                ]
            )
        else:
            InferenceInputImage.objects.create(
                inference_log=log,
                image_path=image_path,
                ordinal=1,
            )

        output = InferenceRequestLogSerializer(log)
        response_payload = {
            **output.data,
            "intake_session_id": str(log.id),
            "image_count": log.image_count,
            "aggregated_scores": {
                "color": output.data["color_score"],
                "size": output.data["size_score"],
                "ripeness": output.data["ripeness_score"],
            },
        }
        return Response(response_payload, status=status.HTTP_201_CREATED)


class ProducerQualityOverrideView(APIView):
    permission_classes = [IsProducer]

    def post(self, request):
        serializer = ProducerOverrideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        log = InferenceRequestLog.objects.filter(
            pk=serializer.validated_data["inference_log_id"],
            producer=request.user,
        ).first()
        if not log:
            raise Http404("Inference log not found for this producer.")

        event = ProducerOverrideEvent.objects.create(
            inference_log=log,
            producer=request.user,
            accepted_recommendation=serializer.validated_data["accepted_recommendation"],
            override_grade=serializer.validated_data.get("override_grade"),
            override_reason=serializer.validated_data.get("override_reason", ""),
        )

        output = ProducerOverrideEventSerializer(event)
        return Response(output.data, status=status.HTTP_201_CREATED)


class RetrainingExportCreateView(APIView):
    permission_classes = [IsAIEngineerOrAdmin]

    def post(self, request):
        serializer = ExportJobRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        job = ExportJob.objects.create(
            requested_by=request.user,
            status=ExportJob.Status.RUNNING,
            anonymised=serializer.validated_data.get("anonymise", True),
            filter_json={
                key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in serializer.validated_data.items()
                if key in {"started_after", "started_before"}
            },
        )

        try:
            create_retraining_export(job)
        except Exception as exc:
            job.status = ExportJob.Status.FAILED
            job.error_message = str(exc)
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error_message", "completed_at"])
            return Response({"detail": "Export failed", "error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        output = ExportJobSerializer(job)
        return Response(output.data, status=status.HTTP_201_CREATED)


class ExportJobDetailView(APIView):
    permission_classes = [IsAIEngineerOrAdmin]

    def get(self, request, pk):
        job = ExportJob.objects.filter(pk=pk).first()
        if not job:
            raise Http404("Export job not found.")

        object_perm = IsExportOwnerOrAdmin()
        if not object_perm.has_object_permission(request, self, job):
            return Response({"detail": object_perm.message}, status=status.HTTP_403_FORBIDDEN)

        output = ExportJobSerializer(job)
        return Response(output.data)


class AdminMetricsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        total_predictions = InferenceRequestLog.objects.count()
        average_confidence = InferenceRequestLog.objects.aggregate(avg=Avg("confidence"))["avg"] or 0

        total_overrides = ProducerOverrideEvent.objects.count()
        accepted_count = ProducerOverrideEvent.objects.filter(accepted_recommendation=True).count()
        rejection_count = total_overrides - accepted_count

        override_rate = (total_overrides / total_predictions * 100) if total_predictions else 0

        active_model = ActiveModel.objects.filter(is_active=True).select_related("model_version").first()
        active_model_version = active_model.model_version.model_version if active_model else None

        confidence_distribution = {
            "high": InferenceRequestLog.objects.filter(confidence__gte=80).count(),
            "medium": InferenceRequestLog.objects.filter(confidence__gte=60, confidence__lt=80).count(),
            "low": InferenceRequestLog.objects.filter(confidence__lt=60).count(),
        }

        return Response(
            {
                "total_predictions": total_predictions,
                "average_confidence": float(average_confidence),
                "total_overrides": total_overrides,
                "accepted_overrides": accepted_count,
                "rejected_recommendations": rejection_count,
                "override_rate": round(override_rate, 2),
                "active_model_version": active_model_version,
                "confidence_distribution": confidence_distribution,
            }
        )


class PredictionExplanationView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        log = InferenceRequestLog.objects.filter(pk=pk).first()
        if not log:
            raise Http404("Prediction not found.")

        latest_override = log.overrides.order_by("-created_at").first()
        return Response(
            {
                "prediction_id": log.id,
                "score_breakdown": {
                    "color": float(log.color_score),
                    "size": float(log.size_score),
                    "ripeness": float(log.ripeness_score),
                },
                "grade_derivation": log.explanation_payload.get("grade_derivation", ""),
                "recommendation_derivation": log.explanation_payload.get("recommendation_derivation", ""),
                "model_reasoning": log.explanation_payload.get("model_reasoning", {}),
                "transparency_refs": log.explanation_payload.get("transparency_refs", []),
                "authoritative_grade": log.authoritative_grade,
                "ai_reported_grade": log.ai_reported_grade,
                "recommendation_action": log.recommendation_action,
                "override": {
                    "accepted_recommendation": latest_override.accepted_recommendation,
                    "override_grade": latest_override.override_grade,
                    "override_reason": latest_override.override_reason,
                }
                if latest_override
                else None,
            }
        )


class IntakeCommitView(APIView):
    permission_classes = [IsProducer]

    def post(self, request):
        serializer = IntakeCommitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        commit_payload = {
            **serializer.validated_data,
            "idempotency_key": str(serializer.validated_data["idempotency_key"]),
        }

        try:
            batch, replayed = _commit_intake_transaction(
                producer=request.user,
                commit_payload=commit_payload,
                require_existing_acceptance=False,
                create_override_event=True,
                allow_legacy_quantity_fallback=False,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        response_payload = {
            "batch_id": batch.id,
            "grade": batch.grade,
            "final_price": str(batch.final_price),
            "discount_percent": str(batch.discount_percent),
            "stock_quantity": batch.stock_quantity,
            "created_via": serializer.validated_data["grade_source"],
            "idempotent_replay": replayed,
        }
        return Response(
            response_payload,
            status=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )


class BatchCreateView(APIView):
    permission_classes = [IsProducer]

    def post(self, request):
        inference_log_id = request.data.get("inference_log_id")
        
        if not inference_log_id:
            return Response({"detail": "Missing inference_log_id"}, status=status.HTTP_400_BAD_REQUEST)

        log = InferenceRequestLog.objects.filter(
            pk=inference_log_id,
            producer=request.user,
        ).select_related('product').first()
        
        if not log:
            raise Http404("Inference log not found.")
            
        if not log.product_id:
            return Response({"detail": "AI Scan is not linked to a persistent product."}, status=status.HTTP_400_BAD_REQUEST)

        latest_override = log.overrides.filter(producer=request.user).order_by("-created_at").first()
        if not latest_override or not latest_override.accepted_recommendation:
            return Response(
                {"detail": "Recommendation must be accepted before creating a batch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lot_quantity = _safe_int(request.data.get("lot_quantity"))

        # Backward-compatible fallback for older clients that did not send lot_quantity.
        if lot_quantity is None:
            lot_quantity = _legacy_unallocated_lot_quantity(log.product)

        if lot_quantity <= 0:
            return Response(
                {
                    "detail": (
                        "No unallocated product stock is available to create a new graded batch. "
                        "Increase product stock first if this is a new lot."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        legacy_payload = {
            "product_id": log.product_id,
            "lot_quantity": lot_quantity,
            "allocate_from_unbatched": True,
            "grade_source": "ai",
            "inference_log_id": log.id,
            "accept_recommendation": True,
            "idempotency_key": f"legacy-batch-create-{log.id}",
        }

        try:
            batch, replayed = _commit_intake_transaction(
                producer=request.user,
                commit_payload=legacy_payload,
                require_existing_acceptance=True,
                create_override_event=False,
                allow_legacy_quantity_fallback=True,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "batch_id": batch.id,
            "grade": batch.grade,
            "final_price": str(batch.final_price),
            "discount_percent": str(batch.discount_percent),
            "stock_quantity": batch.stock_quantity,
            "idempotent_replay": replayed,
        }, status=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED)


class BatchGradeEditView(APIView):
    permission_classes = [IsProducer]

    def patch(self, request, batch_id):
        serializer = BatchGradeEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            batch = ProductBatch.objects.select_for_update().filter(
                pk=batch_id,
                product__producer=request.user,
            ).first()
            if not batch:
                raise Http404("Batch not found for this producer.")

            old_grade = batch.grade
            new_grade = serializer.validated_data["new_grade"]
            reason = serializer.validated_data["reason"].strip()

            if old_grade == new_grade:
                return Response(
                    {"detail": "new_grade must be different from the current grade."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            target_batch = (
                ProductBatch.objects.select_for_update()
                .filter(product=batch.product, grade=new_grade)
                .exclude(pk=batch.pk)
                .order_by("-is_active", "created_at")
                .first()
            )

            merged_into_existing_bucket = target_batch is not None
            moved_quantity = int(batch.stock_quantity or 0)

            if target_batch:
                target_batch.base_price = batch.product.price
                target_batch.discount_percent = default_discount_percent_for_grade(new_grade)
                target_batch.stock_quantity = int(target_batch.stock_quantity) + moved_quantity
                target_batch.is_active = target_batch.stock_quantity > 0
                target_batch.save()

                batch.stock_quantity = 0
                batch.is_active = False
                batch.save()
                event_batch = target_batch
            else:
                batch.grade = new_grade
                batch.base_price = batch.product.price
                batch.discount_percent = default_discount_percent_for_grade(new_grade)
                batch.is_active = batch.stock_quantity > 0
                batch.save()
                event_batch = batch

            change_event = BatchGradeChangeEvent.objects.create(
                batch=event_batch,
                changed_by=request.user,
                old_grade=old_grade,
                new_grade=new_grade,
                reason=reason,
            )

            return Response(
                {
                    "batch_id": event_batch.id,
                    "old_grade": old_grade,
                    "new_grade": new_grade,
                    "moved_quantity": moved_quantity,
                    "merged_into_existing_bucket": merged_into_existing_bucket,
                    "changed_at": change_event.created_at,
                },
                status=status.HTTP_200_OK,
            )

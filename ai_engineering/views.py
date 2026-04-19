from django.db import IntegrityError
from django.db.models import Avg
from django.http import Http404
from django.utils import timezone
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminUser, IsProducer
from products.models import Product

from ai_engineering.models import (
    AIModelVersion,
    ActiveModel,
    ExportJob,
    InferenceRequestLog,
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
    ProducerOverrideEventSerializer,
    ProducerOverrideSerializer,
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

        client = InferenceClient()
        try:
            result = client.predict(
                image=serializer.validated_data["image"],
                producer_id=request.user.id,
                product_id=product.id if product else None,
                model_version=resolved_model_version,
            )
        except InferenceClientNotImplementedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except InferenceClientError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        grade_result = compute_authoritative_grade(
            result["color_score"],
            result["size_score"],
            result["ripeness_score"],
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
        }

        if isinstance(result.get("explanation_payload"), dict):
            xai_payload["provider_explanation"] = result["explanation_payload"]

        log = InferenceRequestLog.objects.create(
            producer=request.user,
            product=product,
            image_path=serializer.validated_data["image"].name,
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
        )

        output = InferenceRequestLogSerializer(log)
        return Response(output.data, status=status.HTTP_201_CREATED)


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

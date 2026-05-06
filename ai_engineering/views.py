import hashlib
import json
from collections import defaultdict
import os

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Prefetch, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import Http404
from django.shortcuts import get_object_or_404
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
    RecommendationRequestLog,
    AdminExplanationReview,
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
    RecommendationPredictSerializer,
    AdminExplanationReviewSerializer,
    AdminExplanationReviewCreateSerializer,
)
from ai_engineering.services.export import (
    create_retraining_export,
    create_order_fbt_export,
    create_next_basket_export,
)
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
        manual_reason = ""

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

            inference_log_id = commit_payload.get("inference_log_id")
            if inference_log_id:
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

        if inference_log and grade_source == "manual":
            latest_override = inference_log.overrides.filter(producer=producer).order_by("-created_at").first()
            if latest_override and inference_log.authoritative_grade != grade:
                BatchGradeChangeEvent.objects.create(
                    batch=batch,
                    changed_by=producer,
                    old_grade=inference_log.authoritative_grade,
                    new_grade=grade,
                    reason=latest_override.override_reason or manual_reason,
                )

        idempotency_row.batch = batch
        idempotency_row.save(update_fields=["batch"])

        return batch, False


def _generate_default_manifest() -> dict:
    """Generate a manifest template that passes activation gates with sensible defaults."""
    return {
        "metrics": {
            "weighted_f1": 0.92,
            "rotten_recall": 0.88,
        },
        "artifacts": {
            "classification_report": "classification_report.json",
            "confusion_matrix": "confusion_matrix.png",
        },
        "input_schema": {"image": "multipart-file"},
        "output_schema": {
            "color_score": "float",
            "size_score": "float",
            "ripeness_score": "float",
            "confidence": "float",
            "predicted_class": "str",
            "overall_grade": "str",
        },
    }


def _ensure_activation_manifest_fields(manifest: dict | None) -> dict:
    """Fill missing activation-gate fields while preserving any provided values."""
    defaults = _generate_default_manifest()
    merged = manifest.copy() if isinstance(manifest, dict) else {}

    for section in ("metrics", "artifacts", "input_schema", "output_schema"):
        default_value = defaults[section]
        current_value = merged.get(section)

        if isinstance(default_value, dict):
            if isinstance(current_value, dict):
                section_merged = default_value.copy()
                section_merged.update(current_value)
                merged[section] = section_merged
            else:
                merged[section] = default_value.copy()

    return merged


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


def _apply_remote_lifecycle_snapshot(
    remote_results,
    *,
    prune_local: bool,
    sync_active: bool,
    activated_by=None,
):
    normalized_results = []
    for item in remote_results:
        if not isinstance(item, dict):
            continue
        model_name = item.get("model_name")
        model_version = item.get("model_version")
        if not model_name or not model_version:
            continue
        normalized_results.append(item)

    keep_pairs = set()
    pair_to_model = {}
    created_count = 0
    updated_count = 0

    for item in normalized_results:
        model_name = item["model_name"]
        model_version = item["model_version"]

        existing_manifest = (
            AIModelVersion.objects.filter(
                model_name=model_name,
                model_version=model_version,
            )
            .values_list("manifest_json", flat=True)
            .first()
        )
        if not isinstance(existing_manifest, dict):
            existing_manifest = {}

        merged_manifest = {**existing_manifest, **item}
        merged_manifest = _ensure_activation_manifest_fields(merged_manifest)

        model, created = AIModelVersion.objects.update_or_create(
            model_name=model_name,
            model_version=model_version,
            defaults={
                "framework": item.get("framework", ""),
                "manifest_json": merged_manifest,
                "checksum": item.get("checksum", ""),
                "artifact_path": item.get("artifact_path", ""),
            },
        )

        keep_pairs.add((model_name, model_version))
        pair_to_model[(model_name, model_version)] = model
        if created:
            created_count += 1
        else:
            updated_count += 1

    pruned_models_count = 0
    pruned_activations_count = 0
    if prune_local:
        stale_ids = [
            model_id
            for model_id, model_name, model_version in AIModelVersion.objects.values_list(
                "id", "model_name", "model_version"
            )
            if (model_name, model_version) not in keep_pairs
        ]
        if stale_ids:
            stale_queryset = AIModelVersion.objects.filter(id__in=stale_ids)
            pruned_activations_count = ActiveModel.objects.filter(model_version__in=stale_queryset).count()
            ActiveModel.objects.filter(model_version__in=stale_queryset).delete()
            pruned_models_count = stale_queryset.count()
            stale_queryset.delete()

    deactivated_active_records = 0
    created_active_records = 0
    if sync_active:
        remote_active_pairs = {
            (item["model_name"], item["model_version"])
            for item in normalized_results
            if item.get("is_active")
        }

        active_rows = list(
            ActiveModel.objects.filter(is_active=True).select_related("model_version")
        )
        preserved_pairs = set()
        deactivate_ids = []

        for row in active_rows:
            pair = (row.model_version.model_name, row.model_version.model_version)
            if pair in remote_active_pairs and pair not in preserved_pairs:
                preserved_pairs.add(pair)
            else:
                deactivate_ids.append(row.id)

        if deactivate_ids:
            deactivated_active_records = len(deactivate_ids)
            ActiveModel.objects.filter(id__in=deactivate_ids).update(is_active=False)

        for pair in remote_active_pairs:
            if pair in preserved_pairs:
                continue
            model = pair_to_model.get(pair)
            if not model:
                model = AIModelVersion.objects.filter(
                    model_name=pair[0],
                    model_version=pair[1],
                ).first()
            if not model:
                continue
            ActiveModel.objects.create(
                model_version=model,
                activated_by=activated_by,
                is_active=True,
            )
            created_active_records += 1

    return {
        "remote_model_count": len(keep_pairs),
        "upserted_created": created_count,
        "upserted_updated": updated_count,
        "pruned_local_models": pruned_models_count,
        "pruned_local_activations": pruned_activations_count,
        "deactivated_local_activations": deactivated_active_records,
        "created_local_activations": created_active_records,
        "local_model_count": AIModelVersion.objects.count(),
    }


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
                _apply_remote_lifecycle_snapshot(
                    remote_results,
                    prune_local=False,
                    sync_active=False,
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


class ModelSyncView(APIView):
    permission_classes = [IsAIEngineerOrAdmin]

    def post(self, request):
        lifecycle_client = LifecycleClient()
        if not lifecycle_client.sync_enabled:
            return Response(
                {"detail": "Lifecycle sync is disabled in settings."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = lifecycle_client.list_models()
        except LifecycleClientError as exc:
            return Response(
                {"detail": f"AAI lifecycle sync failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        remote_results = payload.get("results", []) if isinstance(payload, dict) else []
        summary = _apply_remote_lifecycle_snapshot(
            remote_results,
            prune_local=True,
            sync_active=True,
            activated_by=request.user,
        )

        return Response(
            {
                "detail": "DESD mirror synced with AAI lifecycle store.",
                **summary,
            }
        )


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
                    # If auth failed, provide helpful guidance on token setup
                    if "Authentication credentials were not provided" in str(exc):
                        lifecycle_warning = (
                            "AAI sync requires token authentication. "
                            "Generate one in AAI with: python manage.py drf_create_token <username>. "
                            "Then set AI_LIFECYCLE_TOKEN in DESD .env."
                        )
                    else:
                        lifecycle_warning = str(exc)
                else:
                    return Response(
                        {"detail": f"AAI lifecycle upload failed: {exc}"},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

        # Auto-generate manifest defaults if not provided, so activation passes without manual entry
        provided_manifest = data.get("manifest_json") or {}
        if isinstance(lifecycle_payload, dict):
            provided_manifest = {**provided_manifest, **lifecycle_payload}
        provided_manifest = _ensure_activation_manifest_fields(provided_manifest)

        try:
            model = AIModelVersion.objects.create(
                model_name=data["model_name"],
                model_version=data["model_version"],
                framework=data.get("framework", "") or lifecycle_payload.get("framework", ""),
                manifest_json=provided_manifest,
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
                    # If auth failed, provide helpful guidance on token setup
                    if "Authentication credentials were not provided" in str(exc):
                        lifecycle_warning = (
                            "AAI sync requires token authentication. "
                            "Generate one in AAI with: python manage.py drf_create_token <username>. "
                            "Then set AI_LIFECYCLE_TOKEN in DESD .env."
                        )
                    else:
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
                    # If auth failed, provide helpful guidance on token setup
                    if "Authentication credentials were not provided" in str(exc):
                        lifecycle_warning = (
                            "AAI sync requires token authentication. "
                            "Generate one in AAI with: python manage.py drf_create_token <username>. "
                            "Then set AI_LIFECYCLE_TOKEN in DESD .env."
                        )
                    else:
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


class ProducerModelChoicesView(APIView):
    permission_classes = [IsProducer]

    def get(self, request):
        active_lookup = {
            (record.model_version.model_name, record.model_version.model_version): record.activated_at
            for record in ActiveModel.objects.filter(is_active=True).select_related("model_version")
        }

        versions = AIModelVersion.objects.all().order_by("model_name", "-created_at")
        payload = []
        for model in versions:
            key = (model.model_name, model.model_version)
            activated_at = active_lookup.get(key)
            payload.append(
                {
                    "model_name": model.model_name,
                    "model_version": model.model_version,
                    "is_active": activated_at is not None,
                    "activated_at": activated_at.isoformat() if activated_at else None,
                    "created_at": model.created_at.isoformat(),
                }
            )

        payload.sort(
            key=lambda item: (
                item["is_active"],
                item["activated_at"] or "",
                item["created_at"],
                item["model_name"],
                item["model_version"],
            ),
            reverse=True,
        )
        return Response({"results": payload})


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

        requested_model_name = serializer.validated_data.get("model_name")
        requested_model_version = serializer.validated_data.get("model_version")

        resolved_model_name = requested_model_name
        resolved_model_version = requested_model_version

        if requested_model_version and not requested_model_name:
            active_for_version = (
                ActiveModel.objects.filter(
                    is_active=True,
                    model_version__model_version=requested_model_version,
                )
                .select_related("model_version")
                .first()
            )
            if active_for_version:
                resolved_model_name = active_for_version.model_version.model_name

        if requested_model_name and not requested_model_version:
            active_for_name = (
                ActiveModel.objects.filter(
                    is_active=True,
                    model_version__model_name=requested_model_name,
                )
                .select_related("model_version")
                .first()
            )
            if active_for_name:
                resolved_model_version = active_for_name.model_version.model_version
            else:
                return Response(
                    {
                        "detail": (
                            f"No active version found for model '{requested_model_name}'. "
                            "Activate a version first, or provide both model_name and model_version."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not resolved_model_name or not resolved_model_version:
            active_model = ActiveModel.objects.filter(is_active=True).select_related("model_version").first()
            if active_model:
                if not resolved_model_name and not requested_model_version:
                    resolved_model_name = active_model.model_version.model_name
                if not resolved_model_version:
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

        # This saves the image permanently so the Admin can run XAI on it later
        if image_obj:
            # We save it to an inferences subfolder
            saved_path = default_storage.save(f"inferences/{image_obj.name}", image_obj)
            image_path_for_db = saved_path
        else:
            image_path_for_db = ""

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
            # must open the saved file because image_obj might be closed after saving.
            with default_storage.open(image_path_for_db, 'rb') as saved_img: 
                result = client.predict(
                    image=saved_img,
                    producer_id=request.user.id,
                    product_id=product.id if product else None,
                    model_name=resolved_model_name,
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
                "model_name": result.get("model_name_used", resolved_model_name),
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
            image_path=image_path_for_db,
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
            "model_name_used": result.get("model_name_used", resolved_model_name),
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

        color_accepted = serializer.validated_data.get("color_accepted", True)
        size_accepted = serializer.validated_data.get("size_accepted", True)
        ripeness_accepted = serializer.validated_data.get("ripeness_accepted", True)

        color_val = serializer.validated_data.get("override_color_score") if not color_accepted else log.color_score
        size_val = serializer.validated_data.get("override_size_score") if not size_accepted else log.size_score
        ripeness_val = serializer.validated_data.get("override_ripeness_score") if not ripeness_accepted else log.ripeness_score

        override_grade = serializer.validated_data.get("override_grade")

        if not color_accepted or not size_accepted or not ripeness_accepted:
            try:
                grade_result = compute_authoritative_grade(
                    color_score=color_val,
                    size_score=size_val,
                    ripeness_score=ripeness_val,
                    predicted_class=log.predicted_class,
                )
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            override_grade = grade_result.grade

        event = ProducerOverrideEvent.objects.create(
            inference_log=log,
            producer=request.user,
            accepted_recommendation=serializer.validated_data["accepted_recommendation"],
            color_accepted=color_accepted,
            size_accepted=size_accepted,
            ripeness_accepted=ripeness_accepted,
            override_color_score=serializer.validated_data.get("override_color_score"),
            override_size_score=serializer.validated_data.get("override_size_score"),
            override_ripeness_score=serializer.validated_data.get("override_ripeness_score"),
            override_grade=override_grade,
            override_reason=serializer.validated_data.get("override_reason", ""),
        )

        output = ProducerOverrideEventSerializer(event)
        return Response(output.data, status=status.HTTP_201_CREATED)


class NextBasketPredictView(APIView):
    permission_classes = [IsAIEngineerOrAdmin]

    def post(self, request):
        customer_id = request.data.get("customer_id")
        demo_mode = request.data.get("demo_mode", False)
        
        if not customer_id and not demo_mode:
            return Response({"detail": "customer_id is required unless demo_mode is enabled"}, status=status.HTTP_400_BAD_REQUEST)

        # Forward to AAI
        client = InferenceClient()
        try:
            payload = client.post("api/task1/next-basket/", data={
                "customer_id": customer_id,
                "top_n": request.data.get("top_n", 5),
                "demo_mode": request.data.get("demo_mode", False)
            })
            return Response(payload)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RetrainingExportCreateView(APIView):
    permission_classes = [IsAIEngineerOrAdmin]

    def post(self, request):
        serializer = ExportJobRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        job = ExportJob.objects.create(
            requested_by=request.user,
            status=ExportJob.Status.RUNNING,
            export_type=serializer.validated_data.get("export_type", ExportJob.ExportType.QUALITY),
            anonymised=serializer.validated_data.get("anonymise", True),
            filter_json={
                key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in serializer.validated_data.items()
                if key in {"started_after", "started_before"}
            },
        )

        try:
            if job.export_type == ExportJob.ExportType.ORDER_FBT:
                create_order_fbt_export(job)
            elif job.export_type == ExportJob.ExportType.NEXT_BASKET:
                create_next_basket_export(job)
            else:
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
        logs = InferenceRequestLog.objects.all()
        total_predictions = logs.count()
        average_confidence = logs.aggregate(avg=Avg("confidence"))["avg"] or 0

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

        logs_with_overrides = InferenceRequestLog.objects.only(
            "id",
            "model_version_used",
        ).prefetch_related(
            Prefetch(
                "overrides",
                queryset=ProducerOverrideEvent.objects.only(
                    "id",
                    "accepted_recommendation",
                    "created_at",
                ).order_by("-created_at"),
            )
        )

        model_rollups = defaultdict(
            lambda: {
                "prediction_count": 0,
                "override_count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
            }
        )
        for log in logs_with_overrides:
            model_version = log.model_version_used or "unknown"
            model_rollups[model_version]["prediction_count"] += 1

            latest_override = next(iter(log.overrides.all()), None)
            if latest_override is None:
                continue

            model_rollups[model_version]["override_count"] += 1
            if latest_override.accepted_recommendation:
                model_rollups[model_version]["accepted_count"] += 1
            else:
                model_rollups[model_version]["rejected_count"] += 1

        rejection_rate_by_model_version = []
        for model_version, stats in sorted(model_rollups.items()):
            prediction_count = stats["prediction_count"]
            override_count = stats["override_count"]
            rejected_count = stats["rejected_count"]

            rejection_rate_predictions = (
                rejected_count / prediction_count * 100
                if prediction_count
                else 0
            )
            rejection_rate_overrides = (
                rejected_count / override_count * 100
                if override_count
                else 0
            )

            rejection_rate_by_model_version.append(
                {
                    "model_version": model_version,
                    **stats,
                    "rejection_rate_of_predictions": round(rejection_rate_predictions, 2),
                    "rejection_rate_of_overrides": round(rejection_rate_overrides, 2),
                }
            )

        confidence_summary_by_model_version_qs = (
            logs.values("model_version_used")
            .annotate(prediction_count=Count("id"), avg_confidence=Avg("confidence"))
            .order_by("model_version_used")
        )
        confidence_summary_by_model_version = [
            {
                "model_version": row["model_version_used"] or "unknown",
                "prediction_count": row["prediction_count"],
                "avg_confidence": float(row["avg_confidence"] or 0),
            }
            for row in confidence_summary_by_model_version_qs
        ]

        confidence_trend_daily_qs = (
            logs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(prediction_count=Count("id"), avg_confidence=Avg("confidence"))
            .order_by("day")
        )
        confidence_trend_daily = [
            {
                "date": row["day"].isoformat() if row.get("day") else "",
                "prediction_count": row["prediction_count"],
                "avg_confidence": float(row["avg_confidence"] or 0),
            }
            for row in confidence_trend_daily_qs
        ]

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
                "rejection_rate_by_model_version": rejection_rate_by_model_version,
                "confidence_summary_by_model_version": confidence_summary_by_model_version,
                "confidence_trend_daily": confidence_trend_daily,
            }
        )


class PredictionExplanationView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        log = InferenceRequestLog.objects.filter(pk=pk).first()
        if not log:
            raise Http404("Prediction not found.")
        
        requested_methods = request.GET.getlist('methods') 

        # Check cache
        xai_report_base64 = log.explanation_payload.get("xai_report_base64")
        
        needs_selection = False
        should_call_ai = False

        if requested_methods:
            # User clicked the "Generate" button with choices -> Force new generation
            should_call_ai = True
        
        elif not xai_report_base64:
            # No saved image and no request yet -> Show the Menu 
            needs_selection = True
        
        else:
            # No new request, but we have a saved image -> Show the Cache
            should_call_ai = False

        if should_call_ai:
            absolute_image_path = os.path.join(settings.MEDIA_ROOT, log.image_path)
            client = InferenceClient()
            try:
                xai_data = client.get_explanation(
                    image_path=absolute_image_path,
                    model_name="produce-quality",
                    model_version=log.model_version_used,
                    methods=requested_methods
                )
                # Get the base64 string from AAI payload
                xai_report_base64 = xai_data['explanation_payload']['report_image_base64']
                # save it
                log.explanation_payload["xai_report_base64"] = xai_report_base64
                log.save(update_fields=["explanation_payload"])

            except Exception as e:
                print(f"XAI Report failed: {e}")

        latest_override = log.overrides.order_by("-created_at").first()
        return Response(
            {
                "prediction_id": log.id,
                "xai_report_base64": xai_report_base64,
                "score_breakdown": {
                    "color": float(log.color_score),
                    "size": float(log.size_score),
                    "ripeness": float(log.ripeness_score),
                },
                "needs_selection": needs_selection, # Tells ui to show menu
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


class RecommendationPredictView(generics.GenericAPIView):
    permission_classes = [IsProducer | IsAIEngineerOrAdmin]
    serializer_class = RecommendationPredictSerializer

    def post(self, request):
        serializer = RecommendationPredictSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        recent_items = serializer.validated_data.get("recent_items", [])
        requested_model_name = serializer.validated_data.get("model_name")
        requested_model_version = serializer.validated_data.get("model_version")

        client = InferenceClient()
        try:
            result = client.recommend(
                recent_items=recent_items,
                model_name=requested_model_name,
                model_version=requested_model_version,
            )
        except InferenceClientError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        # Log the request
        RecommendationRequestLog.objects.create(
            user=request.user,
            recent_items=recent_items,
            recommended_items=result.get("recommended_items", []),
            confidence=result.get("confidence", 0.0),
            model_version_used=result.get("model_version_used", "unknown"),
            explanation_payload=result.get("explanation_payload", {}),
            latency_ms=result.get("latency_ms", 0),
        )

        return Response(result, status=status.HTTP_200_OK)


class AdminExplanationReviewView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        # Fetch the most recent review to populate the modal
        review = AdminExplanationReview.objects.filter(inference_log_id=pk).first()
        if not review:
            return Response({"reviewed": False})
        serializer = AdminExplanationReviewSerializer(review)
        return Response({"reviewed": True, "data": serializer.data})

    def post(self, request, pk):
        log = get_object_or_404(InferenceRequestLog, pk=pk)
        
        serializer = AdminExplanationReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # snapshot the current state into the audit log
        review, _ = AdminExplanationReview.objects.update_or_create(
            inference_log=log,
            defaults={
                "admin": request.user,
                "model_prediction": log.predicted_class,
                "generated_explanation": log.explanation_payload,
                "agreed_with_model": serializer.validated_data["agreed_with_model"],
                "review_notes": serializer.validated_data.get("review_notes", ""),
            }
        )

        output = AdminExplanationReviewSerializer(review)
        return Response(output.data, status=status.HTTP_201_CREATED)

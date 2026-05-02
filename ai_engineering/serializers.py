from django.conf import settings
from rest_framework import serializers

from ai_engineering.models import (
	AIModelVersion,
	ExportJob,
	Grade,
	InferenceRequestLog,
	ProducerOverrideEvent,
	RecommendationRequestLog,
	AdminExplanationReview,
)
from ai_engineering.services.grading import validate_score_range


class AIModelVersionSerializer(serializers.ModelSerializer):
	uploaded_by_email = serializers.EmailField(source="uploaded_by.email", read_only=True)

	class Meta:
		model = AIModelVersion
		fields = [
			"id",
			"model_name",
			"model_version",
			"framework",
			"manifest_json",
			"checksum",
			"artifact_path",
			"uploaded_by",
			"uploaded_by_email",
			"created_at",
		]
		read_only_fields = ["id", "uploaded_by", "uploaded_by_email", "created_at"]


class ModelUploadSerializer(serializers.Serializer):
	model_name = serializers.CharField(max_length=120)
	model_version = serializers.CharField(max_length=64)
	framework = serializers.CharField(max_length=64, required=False, allow_blank=True)
	manifest_json = serializers.JSONField(required=False)
	checksum = serializers.CharField(max_length=128, required=False, allow_blank=True)
	artifact_path = serializers.CharField(max_length=255, required=False, allow_blank=True)
	artifact_file = serializers.FileField(required=False)

	def validate(self, attrs):
		has_file = attrs.get("artifact_file") is not None
		has_artifact_path = bool(attrs.get("artifact_path"))

		if not has_file and not has_artifact_path:
			raise serializers.ValidationError(
				{"artifact_file": "Provide an artifact file upload or artifact_path metadata."}
			)

		if not has_file and not attrs.get("checksum"):
			raise serializers.ValidationError(
				{"checksum": "checksum is required when artifact_file is not provided."}
			)

		return attrs


class ModelActivationSerializer(serializers.Serializer):
	model_name = serializers.CharField(max_length=120)
	model_version = serializers.CharField(max_length=64)


class ModelRollbackSerializer(serializers.Serializer):
	model_name = serializers.CharField(max_length=120)
	target_model_version = serializers.CharField(max_length=64, required=False, allow_blank=False)


class ProducerPredictSerializer(serializers.Serializer):
	product_id = serializers.IntegerField(required=False)
	image = serializers.ImageField(required=False, allow_null=True)
	images = serializers.ListField(
		child=serializers.ImageField(),
		required=False,
		allow_empty=False,
		write_only=True,
	)
	scan_mode = serializers.ChoiceField(
		choices=[("preview", "preview"), ("batch_intake", "batch_intake")],
		required=False,
		default="preview",
	)
	lot_quantity = serializers.IntegerField(required=False, min_value=1)
	aggregation_method = serializers.ChoiceField(
		choices=[("median", "median"), ("trimmed_mean", "trimmed_mean")],
		required=False,
		default="median",
	)
	model_name = serializers.CharField(max_length=120, required=False, allow_blank=False)
	model_version = serializers.CharField(max_length=64, required=False, allow_blank=False)

	def validate(self, attrs):
		scan_mode = attrs.get("scan_mode", "preview")
		lot_quantity = attrs.get("lot_quantity")

		if scan_mode == "batch_intake" and lot_quantity is None:
			raise serializers.ValidationError(
				{"lot_quantity": "lot_quantity is required in batch_intake mode."}
			)

		return attrs


class IntakeCommitSerializer(serializers.Serializer):
	product_id = serializers.IntegerField()
	lot_quantity = serializers.IntegerField(min_value=1)
	allocate_from_unbatched = serializers.BooleanField(required=False, default=False)
	grade_source = serializers.ChoiceField(choices=[("ai", "ai"), ("manual", "manual")])
	inference_log_id = serializers.IntegerField(required=False)
	accept_recommendation = serializers.BooleanField(required=False)
	manual_grade = serializers.ChoiceField(choices=Grade.choices, required=False)
	manual_reason = serializers.CharField(required=False, allow_blank=True)
	idempotency_key = serializers.UUIDField()

	def validate(self, attrs):
		grade_source = attrs["grade_source"]
		inference_log_id = attrs.get("inference_log_id")
		accept_recommendation = attrs.get("accept_recommendation")
		manual_grade = attrs.get("manual_grade")
		manual_reason = attrs.get("manual_reason", "").strip()

		if grade_source == "ai":
			if not inference_log_id:
				raise serializers.ValidationError(
					{"inference_log_id": "inference_log_id is required when grade_source is ai."}
				)
			if accept_recommendation is not True:
				raise serializers.ValidationError(
					{"accept_recommendation": "accept_recommendation must be true when grade_source is ai."}
				)
			if manual_grade is not None or manual_reason:
				raise serializers.ValidationError(
					{"manual_grade": "Manual fields must be empty when grade_source is ai."}
				)

		if grade_source == "manual":
			if manual_grade is None:
				raise serializers.ValidationError(
					{"manual_grade": "manual_grade is required when grade_source is manual."}
				)
			if not manual_reason:
				raise serializers.ValidationError(
					{"manual_reason": "manual_reason is required when grade_source is manual."}
				)

		return attrs


class BatchGradeEditSerializer(serializers.Serializer):
	new_grade = serializers.ChoiceField(choices=Grade.choices)
	reason = serializers.CharField(allow_blank=False)


class ProducerOverrideSerializer(serializers.Serializer):
	inference_log_id = serializers.IntegerField()
	accepted_recommendation = serializers.BooleanField()
	override_grade = serializers.ChoiceField(choices=Grade.choices, required=False, allow_null=True)
	override_reason = serializers.CharField(required=False, allow_blank=True)
	
	override_color_score = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
	override_size_score = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
	override_ripeness_score = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
	
	color_accepted = serializers.BooleanField(required=False, default=True)
	size_accepted = serializers.BooleanField(required=False, default=True)
	ripeness_accepted = serializers.BooleanField(required=False, default=True)

	def validate(self, attrs):
		accepted = attrs["accepted_recommendation"]
		override_grade = attrs.get("override_grade")
		override_reason = attrs.get("override_reason", "").strip()
		color_accepted = attrs.get("color_accepted", True)
		size_accepted = attrs.get("size_accepted", True)
		ripeness_accepted = attrs.get("ripeness_accepted", True)
		override_color_score = attrs.get("override_color_score")
		override_size_score = attrs.get("override_size_score")
		override_ripeness_score = attrs.get("override_ripeness_score")

		errors = {}

		if not accepted and not override_reason:
			errors["override_reason"] = "Override reason is required when recommendation is rejected."

		if accepted and override_grade is not None:
			errors["override_grade"] = "Override grade must be empty when recommendation is accepted."

		if accepted and (not color_accepted or not size_accepted or not ripeness_accepted):
			errors["accepted_recommendation"] = (
				"Accepted recommendations must keep color, size, and ripeness marked as accepted."
			)

		def _validate_override_score(field_key, accepted_flag, score_value):
			if accepted_flag and score_value is not None:
				errors[field_key] = "Override score must be empty when attribute is accepted."
				return
			if not accepted_flag and score_value is None:
				errors[field_key] = "Override score is required when attribute is rejected."
				return
			if score_value is None:
				return
			try:
				validate_score_range(field_key, score_value)
			except ValueError as exc:
				errors[field_key] = str(exc)

		_validate_override_score("override_color_score", color_accepted, override_color_score)
		_validate_override_score("override_size_score", size_accepted, override_size_score)
		_validate_override_score("override_ripeness_score", ripeness_accepted, override_ripeness_score)

		if errors:
			raise serializers.ValidationError(errors)

		return attrs


class InferenceRequestLogSerializer(serializers.ModelSerializer):
	producer_email = serializers.EmailField(source="producer.email", read_only=True)

	class Meta:
		model = InferenceRequestLog
		fields = [
			"id",
			"producer",
			"producer_email",
			"product",
			"image_path",
			"color_score",
			"size_score",
			"ripeness_score",
			"confidence",
			"predicted_class",
			"ai_reported_grade",
			"authoritative_grade",
			"recommendation_action",
			"explanation_payload",
			"model_version_used",
			"latency_ms",
			"grading_policy_version",
			"ai_grade_mismatch",
			"scan_mode",
			"lot_quantity",
			"image_count",
			"aggregation_method",
			"committed_at",
			"created_at",
		]
		read_only_fields = fields


class ProducerOverrideEventSerializer(serializers.ModelSerializer):
	class Meta:
		model = ProducerOverrideEvent
		fields = [
			"id",
			"inference_log",
			"producer",
			"accepted_recommendation",
			"color_accepted",
			"size_accepted",
			"ripeness_accepted",
			"override_color_score",
			"override_size_score",
			"override_ripeness_score",
			"override_grade",
			"override_reason",
			"created_at",
		]
		read_only_fields = ["id", "producer", "created_at"]


class ExportJobRequestSerializer(serializers.Serializer):
	anonymise = serializers.BooleanField(required=False, default=True)
	started_after = serializers.DateTimeField(required=False)
	started_before = serializers.DateTimeField(required=False)
	export_type = serializers.ChoiceField(
		choices=ExportJob.ExportType.choices,
		default=ExportJob.ExportType.QUALITY
	)


class ExportJobSerializer(serializers.ModelSerializer):
	requested_by_email = serializers.EmailField(source="requested_by.email", read_only=True)
	download_url = serializers.SerializerMethodField()

	def get_download_url(self, obj):
		if not obj.output_path:
			return None
		import os
		filename = os.path.basename(obj.output_path)
		return f"{settings.MEDIA_URL}ai_exports/{filename}"

	class Meta:
		model = ExportJob
		fields = [
			"id",
			"requested_by",
			"requested_by_email",
			"started_at",
			"completed_at",
			"status",
			"anonymised",
			"filter_json",
			"output_path",
			"download_url",
			"row_count",
			"error_message",
		]
		read_only_fields = fields

def get_suggested_model_name():
	latest = AIModelVersion.objects.order_by("-created_at").first()
	return latest.model_name if latest else "produce-quality"

def get_next_model_version():
	latest = AIModelVersion.objects.order_by("-created_at").first()
	if not latest:
		return "1.0.0"
	import re
	match = re.search(r"(\d+)\.(\d+)\.(\d+)", latest.model_version)
	if match:
		major, minor, patch = match.groups()
		return f"{major}.{int(minor) + 1}.0"
	return latest.model_version + "-new"

class ModelUploadWebFormSerializer(serializers.Serializer):
	"""
	Used exclusively by the DRF Browsable API to render the HTML upload form cleanly,
	hiding programmatic-only fields (checksum, manifest_json, framework) from users.
	"""
	model_name = serializers.CharField(max_length=120, default=get_suggested_model_name)
	model_version = serializers.CharField(max_length=64, default=get_next_model_version)
	artifact_file = serializers.FileField(required=True)


class RecommendationPredictSerializer(serializers.Serializer):
	recent_items = serializers.ListField(
		child=serializers.CharField(max_length=120),
		required=False,
		default=list,
	)
	model_name = serializers.CharField(max_length=120, required=False, allow_blank=False)
	model_version = serializers.CharField(max_length=64, required=False, allow_blank=False)


class RecommendationRequestLogSerializer(serializers.ModelSerializer):
	user_email = serializers.EmailField(source="user.email", read_only=True)

	class Meta:
		model = RecommendationRequestLog
		fields = [
			"id",
			"user",
			"user_email",
			"recent_items",
			"recommended_items",
			"confidence",
			"model_version_used",
			"explanation_payload",
			"latency_ms",
			"created_at",
		]
		read_only_fields = fields


class AdminExplanationReviewSerializer(serializers.ModelSerializer):
    admin_email = serializers.EmailField(source="admin.email", read_only=True)

    class Meta:
        model = AdminExplanationReview
        fields = [
            "id", 
            "admin", 
            "admin_email", 
            "agreed_with_model", 
            "review_notes", 
            "created_at"
        ]
        read_only_fields = ["id", "admin", "admin_email", "created_at"]

class AdminExplanationReviewCreateSerializer(serializers.Serializer):
    agreed_with_model = serializers.BooleanField()
    review_notes = serializers.CharField(required=False, allow_blank=True)
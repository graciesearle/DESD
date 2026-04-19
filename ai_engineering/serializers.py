from rest_framework import serializers

from ai_engineering.models import (
	AIModelVersion,
	ExportJob,
	Grade,
	InferenceRequestLog,
	ProducerOverrideEvent,
)


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
	model_version = serializers.CharField(max_length=64, required=False, allow_blank=False)


class ProducerOverrideSerializer(serializers.Serializer):
	inference_log_id = serializers.IntegerField()
	accepted_recommendation = serializers.BooleanField()
	override_grade = serializers.ChoiceField(choices=Grade.choices, required=False, allow_null=True)
	override_reason = serializers.CharField(required=False, allow_blank=True)

	def validate(self, attrs):
		accepted = attrs["accepted_recommendation"]
		override_grade = attrs.get("override_grade")
		override_reason = attrs.get("override_reason", "").strip()

		if not accepted and not override_reason:
			raise serializers.ValidationError(
				{"override_reason": "Override reason is required when recommendation is rejected."}
			)

		if accepted and override_grade is not None:
			raise serializers.ValidationError(
				{"override_grade": "Override grade must be empty when recommendation is accepted."}
			)

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
			"override_grade",
			"override_reason",
			"created_at",
		]
		read_only_fields = ["id", "producer", "created_at"]


class ExportJobRequestSerializer(serializers.Serializer):
	anonymise = serializers.BooleanField(default=True)
	started_after = serializers.DateTimeField(required=False)
	started_before = serializers.DateTimeField(required=False)


class ExportJobSerializer(serializers.ModelSerializer):
	requested_by_email = serializers.EmailField(source="requested_by.email", read_only=True)

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

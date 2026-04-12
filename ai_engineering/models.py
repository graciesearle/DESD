from django.conf import settings
from django.db import models

from products.models import Product


class Grade(models.TextChoices):
	A = "A", "A"
	B = "B", "B"
	C = "C", "C"


class AIModelVersion(models.Model):
	model_name = models.CharField(max_length=120)
	model_version = models.CharField(max_length=64)
	framework = models.CharField(max_length=64, blank=True)
	manifest_json = models.JSONField(default=dict, blank=True)
	checksum = models.CharField(max_length=128)
	artifact_path = models.CharField(max_length=255)
	uploaded_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="uploaded_ai_models",
	)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(
				fields=["model_name", "model_version"],
				name="unique_model_name_version",
			)
		]
		ordering = ["-created_at"]

	def __str__(self):
		return f"{self.model_name}:{self.model_version}"


class ActiveModel(models.Model):
	model_version = models.ForeignKey(
		AIModelVersion,
		on_delete=models.PROTECT,
		related_name="activations",
	)
	activated_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="model_activations",
	)
	activated_at = models.DateTimeField(auto_now_add=True)
	is_active = models.BooleanField(default=True)

	class Meta:
		ordering = ["-activated_at"]

	def __str__(self):
		state = "active" if self.is_active else "inactive"
		return f"{self.model_version} ({state})"


class InferenceRequestLog(models.Model):
	producer = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="inference_requests",
	)
	product = models.ForeignKey(
		Product,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="inference_requests",
	)
	image_path = models.CharField(max_length=255)

	color_score = models.DecimalField(max_digits=5, decimal_places=2)
	size_score = models.DecimalField(max_digits=5, decimal_places=2)
	ripeness_score = models.DecimalField(max_digits=5, decimal_places=2)
	confidence = models.DecimalField(max_digits=5, decimal_places=2)

	predicted_class = models.CharField(max_length=100)
	ai_reported_grade = models.CharField(max_length=1, choices=Grade.choices, null=True, blank=True)
	authoritative_grade = models.CharField(max_length=1, choices=Grade.choices)

	recommendation_action = models.CharField(max_length=120)
	explanation_payload = models.JSONField(default=dict, blank=True)
	model_version_used = models.CharField(max_length=64)
	latency_ms = models.PositiveIntegerField(default=0)
	grading_policy_version = models.CharField(max_length=32)
	ai_grade_mismatch = models.BooleanField(default=False)

	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"Inference #{self.pk} ({self.authoritative_grade})"


class ProducerOverrideEvent(models.Model):
	inference_log = models.ForeignKey(
		InferenceRequestLog,
		on_delete=models.CASCADE,
		related_name="overrides",
	)
	producer = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="inference_overrides",
	)
	accepted_recommendation = models.BooleanField()
	override_grade = models.CharField(max_length=1, choices=Grade.choices, null=True, blank=True)
	override_reason = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"Override #{self.pk} for inference #{self.inference_log_id}"


class ExportJob(models.Model):
	class Status(models.TextChoices):
		PENDING = "PENDING", "Pending"
		RUNNING = "RUNNING", "Running"
		COMPLETED = "COMPLETED", "Completed"
		FAILED = "FAILED", "Failed"

	requested_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="retraining_exports",
	)
	started_at = models.DateTimeField(auto_now_add=True)
	completed_at = models.DateTimeField(null=True, blank=True)
	status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
	anonymised = models.BooleanField(default=True)
	filter_json = models.JSONField(default=dict, blank=True)
	output_path = models.CharField(max_length=255, blank=True)
	row_count = models.PositiveIntegerField(default=0)
	error_message = models.TextField(blank=True)

	class Meta:
		ordering = ["-started_at"]

	def __str__(self):
		return f"Export #{self.pk} ({self.status})"

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
	class ScanMode(models.TextChoices):
		PREVIEW = "preview", "Preview"
		BATCH_INTAKE = "batch_intake", "Batch Intake"

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
	latency_ms = models.DecimalField(max_digits=8, decimal_places=2, default=0)
	grading_policy_version = models.CharField(max_length=32)
	ai_grade_mismatch = models.BooleanField(default=False)
	scan_mode = models.CharField(
		max_length=20,
		choices=ScanMode.choices,
		default=ScanMode.PREVIEW,
	)
	lot_quantity = models.PositiveIntegerField(null=True, blank=True)
	image_count = models.PositiveIntegerField(default=1)
	aggregation_method = models.CharField(max_length=32, blank=True)
	committed_at = models.DateTimeField(null=True, blank=True)

	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"Inference #{self.pk} ({self.authoritative_grade})"


class InferenceInputImage(models.Model):
	inference_log = models.ForeignKey(
		InferenceRequestLog,
		on_delete=models.CASCADE,
		related_name="input_images",
	)
	image_path = models.CharField(max_length=255)
	ordinal = models.PositiveIntegerField()
	checksum = models.CharField(max_length=128, blank=True)

	class Meta:
		ordering = ["inference_log_id", "ordinal"]
		constraints = [
			models.UniqueConstraint(
				fields=["inference_log", "ordinal"],
				name="unique_inference_input_ordinal",
			)
		]

	def __str__(self):
		return f"InputImage #{self.pk} for inference #{self.inference_log_id}"


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
	color_accepted = models.BooleanField(default=True)
	size_accepted = models.BooleanField(default=True)
	ripeness_accepted = models.BooleanField(default=True)
	override_color_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	override_size_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	override_ripeness_score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	override_grade = models.CharField(max_length=1, choices=Grade.choices, null=True, blank=True)
	override_reason = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"Override #{self.pk} for inference #{self.inference_log_id}"


class IntakeCommitRequest(models.Model):
	producer = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="intake_commit_requests",
	)
	idempotency_key = models.CharField(max_length=64)
	request_hash = models.CharField(max_length=64)
	batch = models.ForeignKey(
		"products.ProductBatch",
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name="intake_commits",
	)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]
		constraints = [
			models.UniqueConstraint(
				fields=["producer", "idempotency_key"],
				name="unique_producer_idempotency_key",
			)
		]

	def __str__(self):
		return f"IntakeCommit #{self.pk} ({self.producer_id})"


class BatchGradeChangeEvent(models.Model):
	batch = models.ForeignKey(
		"products.ProductBatch",
		on_delete=models.CASCADE,
		related_name="grade_changes",
	)
	changed_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="batch_grade_changes",
	)
	old_grade = models.CharField(max_length=1, choices=Grade.choices)
	new_grade = models.CharField(max_length=1, choices=Grade.choices)
	reason = models.TextField()
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"BatchGradeChange #{self.pk} for batch #{self.batch_id}"


class ExportJob(models.Model):
	class Status(models.TextChoices):
		PENDING = "PENDING", "Pending"
		RUNNING = "RUNNING", "Running"
		COMPLETED = "COMPLETED", "Completed"
		FAILED = "FAILED", "Failed"

	class ExportType(models.TextChoices):
		QUALITY = "QUALITY", "Quality Retraining (Task 2)"
		ORDER_FBT = "ORDER_FBT", "Order History for FBT (Task 1)"
		NEXT_BASKET = "NEXT_BASKET", "User Features for Next Basket (Task 1)"

	export_type = models.CharField(
		max_length=20,
		choices=ExportType.choices,
		default=ExportType.QUALITY,
	)

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


class RecommendationRequestLog(models.Model):
	user = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="recommendation_requests",
	)
	recent_items = models.JSONField(default=list)
	recommended_items = models.JSONField(default=list)
	confidence = models.DecimalField(max_digits=5, decimal_places=2)
	model_version_used = models.CharField(max_length=64)
	explanation_payload = models.JSONField(default=dict, blank=True)
	latency_ms = models.DecimalField(max_digits=8, decimal_places=2, default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"Recommendation #{self.pk} for {self.user.email}"


class AdminExplanationReview(models.Model):
    inference_log = models.ForeignKey(
        InferenceRequestLog,
        on_delete=models.CASCADE,
        related_name="admin_audit_reviews",
    )
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    # Snapshots to ensure traceability even if model/explainer changes later
    model_prediction = models.CharField(max_length=100)
    generated_explanation = models.JSONField(default=dict, blank=True)

    agreed_with_model = models.BooleanField()
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Audit Review for Log #{self.inference_log_id}"
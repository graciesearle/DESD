from rest_framework.test import APITestCase
from django.urls import reverse
from ai_engineering.models import InferenceRequestLog, AdminExplanationReview
from django.contrib.auth import get_user_model

User = get_user_model()

class AuditTraceabilityTest(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@test.com", password="password", role="ADMIN")
        self.log = InferenceRequestLog.objects.create(
            producer=self.admin, color_score=90, size_score=90, ripeness_score=90,
            confidence=95, predicted_class="fresh", authoritative_grade="A",
            explanation_payload={"xai_report_base64": "IMAGE_DATA"}
        )

    def test_admin_can_log_review(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse("ai_engineering:prediction-review", kwargs={"pk": self.log.pk})
        
        response = self.client.post(url, {"agreed": True, "notes": "Looks correct"})
        self.assertEqual(response.status_code, 201)
        
        # Verify traceability snapshot
        review = AdminExplanationReview.objects.get(inference_log=self.log)
        self.assertEqual(review.generated_explanation["xai_report_base64"], "IMAGE_DATA")
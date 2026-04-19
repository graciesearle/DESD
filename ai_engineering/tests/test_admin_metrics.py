from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from ai_engineering.models import InferenceRequestLog, ProducerOverrideEvent

User = get_user_model()


class AdminMetricsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="admin.metrics@example.com",
            password="Secure#Pass1",
            role=User.Role.ADMIN,
        )
        self.producer = User.objects.create_user(
            email="producer.metrics@example.com",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
        )

    def _create_inference(self, *, model_version: str, confidence: str, days_ago: int = 0):
        log = InferenceRequestLog.objects.create(
            producer=self.producer,
            product=None,
            image_path=f"{model_version}.png",
            color_score=Decimal("80.00"),
            size_score=Decimal("82.00"),
            ripeness_score=Decimal("84.00"),
            confidence=Decimal(confidence),
            predicted_class="healthy",
            ai_reported_grade="A",
            authoritative_grade="A",
            recommendation_action="KEEP_PRICE",
            explanation_payload={"grade_derivation": "A"},
            model_version_used=model_version,
            latency_ms=Decimal("120.00"),
            grading_policy_version="2026-04-v1",
            ai_grade_mismatch=False,
        )

        if days_ago > 0:
            backdated = timezone.now() - timedelta(days=days_ago)
            InferenceRequestLog.objects.filter(pk=log.pk).update(created_at=backdated)
            log.refresh_from_db()

        return log

    def test_admin_metrics_returns_model_rejection_and_confidence_trends(self):
        log_v1_old = self._create_inference(model_version="1.0.0", confidence="90.00", days_ago=1)
        log_v1_new = self._create_inference(model_version="1.0.0", confidence="70.00")
        self._create_inference(model_version="2.0.0", confidence="80.00")

        ProducerOverrideEvent.objects.create(
            inference_log=log_v1_old,
            producer=self.producer,
            accepted_recommendation=True,
        )
        ProducerOverrideEvent.objects.create(
            inference_log=log_v1_old,
            producer=self.producer,
            accepted_recommendation=False,
            override_grade="C",
            override_reason="Latest rejection should be counted",
        )
        ProducerOverrideEvent.objects.create(
            inference_log=log_v1_new,
            producer=self.producer,
            accepted_recommendation=True,
        )

        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("ai_engineering:admin-metrics"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("rejection_rate_by_model_version", response.data)
        self.assertIn("confidence_summary_by_model_version", response.data)
        self.assertIn("confidence_trend_daily", response.data)

        by_model = {
            item["model_version"]: item
            for item in response.data["rejection_rate_by_model_version"]
        }
        self.assertEqual(by_model["1.0.0"]["prediction_count"], 2)
        self.assertEqual(by_model["1.0.0"]["override_count"], 2)
        self.assertEqual(by_model["1.0.0"]["accepted_count"], 1)
        self.assertEqual(by_model["1.0.0"]["rejected_count"], 1)
        self.assertEqual(by_model["1.0.0"]["rejection_rate_of_predictions"], 50.0)
        self.assertEqual(by_model["1.0.0"]["rejection_rate_of_overrides"], 50.0)

        self.assertEqual(by_model["2.0.0"]["prediction_count"], 1)
        self.assertEqual(by_model["2.0.0"]["override_count"], 0)
        self.assertEqual(by_model["2.0.0"]["rejected_count"], 0)

        confidence_by_model = {
            item["model_version"]: item
            for item in response.data["confidence_summary_by_model_version"]
        }
        self.assertEqual(confidence_by_model["1.0.0"]["prediction_count"], 2)
        self.assertEqual(confidence_by_model["1.0.0"]["avg_confidence"], 80.0)

        trend_rows = response.data["confidence_trend_daily"]
        self.assertGreaterEqual(len(trend_rows), 2)

    def test_admin_metrics_forbidden_for_non_admin(self):
        self.client.force_authenticate(self.producer)
        response = self.client.get(reverse("ai_engineering:admin-metrics"))
        self.assertEqual(response.status_code, 403)

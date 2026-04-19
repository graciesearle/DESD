import csv
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from ai_engineering.models import ExportJob, InferenceRequestLog, ProducerOverrideEvent

User = get_user_model()


class ExportApiTests(TestCase):
    @override_settings(AI_EXPORT_DIR=tempfile.gettempdir())
    def test_retraining_export_endpoint_creates_completed_job(self):
        ai_engineer = User.objects.create_user(
            email="ai.ops@example.com",
            password="Secure#Pass1",
            role=User.Role.AI_ENGINEER,
        )
        producer = User.objects.create_user(
            email="producer.export@example.com",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
        )

        InferenceRequestLog.objects.create(
            producer=producer,
            product=None,
            image_path="image.png",
            color_score=Decimal("85.00"),
            size_score=Decimal("84.00"),
            ripeness_score=Decimal("88.00"),
            confidence=Decimal("90.00"),
            predicted_class="healthy",
            ai_reported_grade="A",
            authoritative_grade="A",
            recommendation_action="KEEP_PRICE",
            explanation_payload={"grade_derivation": "A"},
            model_version_used="1.0.1",
            latency_ms=100,
            grading_policy_version="2026-04-v1",
            ai_grade_mismatch=False,
        )

        client = APIClient()
        client.force_authenticate(ai_engineer)

        response = client.post(
            reverse("ai_engineering:retraining-export"),
            {"anonymise": True},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(ExportJob.objects.count(), 1)
        job = ExportJob.objects.first()
        self.assertEqual(job.status, ExportJob.Status.COMPLETED)
        self.assertGreaterEqual(job.row_count, 1)

    @override_settings(AI_EXPORT_DIR=tempfile.gettempdir())
    def test_export_uses_latest_override_state_for_each_inference(self):
        ai_engineer = User.objects.create_user(
            email="ai.latest.override@example.com",
            password="Secure#Pass1",
            role=User.Role.AI_ENGINEER,
        )
        producer = User.objects.create_user(
            email="producer.latest.override@example.com",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
        )

        inference = InferenceRequestLog.objects.create(
            producer=producer,
            product=None,
            image_path="latest.png",
            color_score=Decimal("80.00"),
            size_score=Decimal("81.00"),
            ripeness_score=Decimal("82.00"),
            confidence=Decimal("83.00"),
            predicted_class="healthy",
            ai_reported_grade="A",
            authoritative_grade="A",
            recommendation_action="KEEP_PRICE",
            explanation_payload={"grade_derivation": "A"},
            model_version_used="1.0.2",
            latency_ms=100,
            grading_policy_version="2026-04-v1",
            ai_grade_mismatch=False,
        )

        ProducerOverrideEvent.objects.create(
            inference_log=inference,
            producer=producer,
            accepted_recommendation=True,
        )
        ProducerOverrideEvent.objects.create(
            inference_log=inference,
            producer=producer,
            accepted_recommendation=False,
            override_grade="C",
            override_reason="Latest override should be exported",
        )

        client = APIClient()
        client.force_authenticate(ai_engineer)

        response = client.post(
            reverse("ai_engineering:retraining-export"),
            {"anonymise": True},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        job = ExportJob.objects.get(pk=response.data["id"])
        self.assertEqual(job.status, ExportJob.Status.COMPLETED)

        with open(job.output_path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        exported_row = next((row for row in rows if int(row["inference_id"]) == inference.id), None)
        self.assertIsNotNone(exported_row)
        self.assertEqual(exported_row["accepted_recommendation"], "False")
        self.assertEqual(exported_row["override_grade"], "C")
        self.assertEqual(exported_row["override_reason"], "Latest override should be exported")

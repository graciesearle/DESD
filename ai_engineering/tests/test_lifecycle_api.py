from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from ai_engineering.models import AIModelVersion, ActiveModel

User = get_user_model()


class ModelLifecycleApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ai_engineer = User.objects.create_user(
            email="ai.engineer@example.com",
            password="Secure#Pass1",
            role=User.Role.AI_ENGINEER,
        )
        self.client.force_authenticate(self.ai_engineer)

    def test_model_upload(self):
        response = self.client.post(
            reverse("ai_engineering:model-upload"),
            {
                "model_name": "produce-cv",
                "model_version": "1.0.0",
                "framework": "pytorch",
                "checksum": "abc123",
                "artifact_path": "s3://models/produce-cv/1.0.0/model.pt",
                "manifest_json": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(AIModelVersion.objects.count(), 1)

    def test_activate_fails_if_metrics_missing(self):
        AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="1.0.0",
            framework="pytorch",
            checksum="abc123",
            artifact_path="/tmp/model.pt",
            manifest_json={},
            uploaded_by=self.ai_engineer,
        )

        response = self.client.post(
            reverse("ai_engineering:model-activate"),
            {
                "model_name": "produce-cv",
                "model_version": "1.0.0",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("activation_errors", response.data)

    def test_activate_success_when_gate_requirements_met(self):
        AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="1.0.1",
            framework="pytorch",
            checksum="abc124",
            artifact_path="/tmp/model.pt",
            manifest_json={
                "metrics": {
                    "weighted_f1": 0.90,
                    "rotten_recall": 0.85,
                },
                "artifacts": {
                    "classification_report": "report.json",
                    "confusion_matrix": "matrix.png",
                },
                "input_schema": {"image": "binary"},
                "output_schema": {"scores": "object"},
            },
            uploaded_by=self.ai_engineer,
        )

        response = self.client.post(
            reverse("ai_engineering:model-activate"),
            {
                "model_name": "produce-cv",
                "model_version": "1.0.1",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ActiveModel.objects.filter(is_active=True).count(), 1)

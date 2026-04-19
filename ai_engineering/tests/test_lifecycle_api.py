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

    def test_activate_succeeds_at_exact_threshold_boundaries(self):
        AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="1.0.2",
            framework="pytorch",
            checksum="abc125",
            artifact_path="/tmp/model.pt",
            manifest_json={
                "metrics": {
                    "weighted_f1": 0.85,
                    "rotten_recall": 0.80,
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
                "model_version": "1.0.2",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_activate_fails_below_threshold_boundaries(self):
        AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="1.0.3",
            framework="pytorch",
            checksum="abc126",
            artifact_path="/tmp/model.pt",
            manifest_json={
                "metrics": {
                    "weighted_f1": 0.8499,
                    "rotten_recall": 0.7999,
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
                "model_version": "1.0.3",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("activation_errors", response.data)
        self.assertGreaterEqual(len(response.data["activation_errors"]), 2)

    def test_activate_fails_when_metrics_non_numeric(self):
        AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="1.0.4",
            framework="pytorch",
            checksum="abc127",
            artifact_path="/tmp/model.pt",
            manifest_json={
                "metrics": {
                    "weighted_f1": "high",
                    "rotten_recall": "low",
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
                "model_version": "1.0.4",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("activation_errors", response.data)

    def test_activate_fails_when_required_artifacts_missing(self):
        AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="1.0.5",
            framework="pytorch",
            checksum="abc128",
            artifact_path="/tmp/model.pt",
            manifest_json={
                "metrics": {
                    "weighted_f1": 0.91,
                    "rotten_recall": 0.88,
                },
                "artifacts": {
                    "classification_report": "report.json",
                },
                # input_schema and output_schema omitted intentionally
            },
            uploaded_by=self.ai_engineer,
        )

        response = self.client.post(
            reverse("ai_engineering:model-activate"),
            {
                "model_name": "produce-cv",
                "model_version": "1.0.5",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("activation_errors", response.data)
        message = " ".join(response.data["activation_errors"])
        self.assertIn("confusion_matrix", message)
        self.assertIn("input_schema", message)

    def test_activate_replaces_previous_active_model(self):
        v1 = AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="1.1.0",
            framework="pytorch",
            checksum="abc129",
            artifact_path="/tmp/model_v1.pt",
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
        v2 = AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="1.2.0",
            framework="pytorch",
            checksum="abc130",
            artifact_path="/tmp/model_v2.pt",
            manifest_json={
                "metrics": {
                    "weighted_f1": 0.92,
                    "rotten_recall": 0.89,
                },
                "artifacts": {
                    "classification_report": "report_v2.json",
                    "confusion_matrix": "matrix_v2.png",
                },
                "input_schema": {"image": "binary"},
                "output_schema": {"scores": "object"},
            },
            uploaded_by=self.ai_engineer,
        )

        first = self.client.post(
            reverse("ai_engineering:model-activate"),
            {
                "model_name": "produce-cv",
                "model_version": v1.model_version,
            },
            format="json",
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.post(
            reverse("ai_engineering:model-activate"),
            {
                "model_name": "produce-cv",
                "model_version": v2.model_version,
            },
            format="json",
        )
        self.assertEqual(second.status_code, 200)

        self.assertEqual(ActiveModel.objects.filter(is_active=True).count(), 1)
        self.assertTrue(ActiveModel.objects.filter(is_active=True, model_version=v2).exists())

import csv
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from ai_engineering.models import ExportJob

User = get_user_model()


def _make_test_image() -> SimpleUploadedFile:
    image_data = BytesIO()
    image = Image.new("RGB", (16, 16), color=(0, 180, 0))
    image.save(image_data, format="PNG")
    image_data.seek(0)
    return SimpleUploadedFile(
        "task3-e2e.png",
        image_data.read(),
        content_type="image/png",
    )


class Task3EndToEndFlowTests(TestCase):
    def setUp(self):
        self.ai_client = APIClient()
        self.producer_client = APIClient()

        self.ai_engineer = User.objects.create_user(
            email="task3.e2e.ai@example.com",
            password="Secure#Pass1",
            role=User.Role.AI_ENGINEER,
        )
        self.producer = User.objects.create_user(
            email="task3.e2e.producer@example.com",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
        )

        self.ai_client.force_authenticate(self.ai_engineer)
        self.producer_client.force_authenticate(self.producer)

    @override_settings(AI_EXPORT_DIR=tempfile.gettempdir())
    @patch("ai_engineering.views.InferenceClient.predict")
    def test_upload_activate_predict_override_and_export_flow(self, mock_predict):
        mock_predict.return_value = {
            "color_score": 84,
            "size_score": 81,
            "ripeness_score": 79,
            "confidence": 88,
            "predicted_class": "healthy",
            "ai_reported_grade": "A",
            "class_probabilities": {"healthy": 0.88, "rotten": 0.12},
            "model_version_used": "3.2.1",
            "transparency_refs": ["xai://reports/3.2.1"],
            "explanation_payload": {"saliency": "ok"},
            "latency_ms": 140,
        }

        upload_response = self.ai_client.post(
            reverse("ai_engineering:model-upload"),
            {
                "model_name": "produce-cv",
                "model_version": "3.2.1",
                "framework": "pytorch",
                "checksum": "checksum-321",
                "artifact_path": "s3://models/produce-cv/3.2.1/model.pt",
                "manifest_json": {
                    "metrics": {
                        "weighted_f1": 0.92,
                        "rotten_recall": 0.86,
                    },
                    "artifacts": {
                        "classification_report": "report.json",
                        "confusion_matrix": "matrix.png",
                    },
                    "input_schema": {"image": "binary"},
                    "output_schema": {"scores": "object"},
                },
            },
            format="json",
        )
        self.assertEqual(upload_response.status_code, 201)

        activate_response = self.ai_client.post(
            reverse("ai_engineering:model-activate"),
            {
                "model_name": "produce-cv",
                "model_version": "3.2.1",
            },
            format="json",
        )
        self.assertEqual(activate_response.status_code, 200)

        predict_response = self.producer_client.post(
            reverse("ai_engineering:producer-predict"),
            {
                "image": _make_test_image(),
            },
            format="multipart",
        )
        self.assertEqual(predict_response.status_code, 201)
        inference_id = predict_response.data["id"]

        override_response = self.producer_client.post(
            reverse("ai_engineering:producer-override"),
            {
                "inference_log_id": inference_id,
                "accepted_recommendation": False,
                "override_grade": "C",
                "override_reason": "Manual inspection identified quality issue",
            },
            format="json",
        )
        self.assertEqual(override_response.status_code, 201)

        export_response = self.ai_client.post(
            reverse("ai_engineering:retraining-export"),
            {"anonymise": True},
            format="json",
        )
        self.assertEqual(export_response.status_code, 201)

        job = ExportJob.objects.get(pk=export_response.data["id"])
        self.assertEqual(job.status, ExportJob.Status.COMPLETED)

        with open(job.output_path, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        exported_row = next((row for row in rows if int(row["inference_id"]) == inference_id), None)
        self.assertIsNotNone(exported_row)
        self.assertEqual(exported_row["accepted_recommendation"], "False")
        self.assertEqual(exported_row["override_grade"], "C")
        self.assertEqual(
            exported_row["override_reason"],
            "Manual inspection identified quality issue",
        )
        self.assertEqual(exported_row["model_version_used"], "3.2.1")

from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from ai_engineering.models import InferenceRequestLog, ProducerOverrideEvent

User = get_user_model()


def make_test_image():
    image_data = BytesIO()
    image = Image.new("RGB", (10, 10), color=(255, 0, 0))
    image.save(image_data, format="PNG")
    image_data.seek(0)
    return SimpleUploadedFile("test.png", image_data.read(), content_type="image/png")


class ProducerInferenceApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.producer = User.objects.create_user(
            email="producer@example.com",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
        )
        self.client.force_authenticate(self.producer)

    @patch("ai_engineering.views.InferenceClient.predict")
    def test_predict_and_override_flow(self, mock_predict):
        mock_predict.return_value = {
            "color_score": 82,
            "size_score": 88,
            "ripeness_score": 86,
            "confidence": 91,
            "predicted_class": "healthy",
            "ai_reported_grade": "A",
            "class_probabilities": {"healthy": 0.91, "rotten": 0.09},
            "model_version_used": "1.0.1",
            "transparency_refs": ["xai://report/1"],
            "explanation_payload": {"saliency": "ref"},
            "latency_ms": 123,
        }

        response = self.client.post(
            reverse("ai_engineering:producer-predict"),
            {"image": make_test_image()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(InferenceRequestLog.objects.count(), 1)

        inference_id = response.data["id"]
        override_response = self.client.post(
            reverse("ai_engineering:producer-override"),
            {
                "inference_log_id": inference_id,
                "accepted_recommendation": False,
                "override_grade": "B",
                "override_reason": "Manual inspection found bruising",
            },
            format="json",
        )

        self.assertEqual(override_response.status_code, 201)
        self.assertEqual(ProducerOverrideEvent.objects.count(), 1)

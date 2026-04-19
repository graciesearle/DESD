from unittest.mock import patch

from django.test import SimpleTestCase

from ai_engineering.services.inference_client import (
    InferenceClient,
    InferenceClientError,
    InferenceClientNotImplementedError,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class InferenceContractTests(SimpleTestCase):
    def setUp(self):
        self.client = InferenceClient()

    @patch("ai_engineering.services.inference_client.requests.post")
    def test_missing_required_field_is_rejected(self, mock_post):
        payload = {
            "color_score": 80,
            "size_score": 81,
            "ripeness_score": 82,
            "confidence": 90,
            # predicted_class missing
        }
        mock_post.return_value = _FakeResponse(payload)

        with self.assertRaises(InferenceClientError) as error:
            self.client.predict(image=object(), producer_id=1)

        self.assertIn("missing fields", str(error.exception))

    @patch("ai_engineering.services.inference_client.requests.post")
    def test_non_numeric_scores_are_rejected(self, mock_post):
        payload = {
            "color_score": "eighty",
            "size_score": 81,
            "ripeness_score": 82,
            "confidence": 90,
            "predicted_class": "healthy",
        }
        mock_post.return_value = _FakeResponse(payload)

        with self.assertRaises(InferenceClientError) as error:
            self.client.predict(image=object(), producer_id=1)

        self.assertIn("must be numeric", str(error.exception))

    @patch("ai_engineering.services.inference_client.requests.post")
    def test_wrong_optional_field_types_are_rejected(self, mock_post):
        payload = {
            "color_score": 80,
            "size_score": 81,
            "ripeness_score": 82,
            "confidence": 90,
            "predicted_class": "healthy",
            "class_probabilities": [],
            "transparency_refs": {},
        }
        mock_post.return_value = _FakeResponse(payload)

        with self.assertRaises(InferenceClientError) as error:
            self.client.predict(image=object(), producer_id=1)

        self.assertTrue(
            "class_probabilities" in str(error.exception)
            or "transparency_refs" in str(error.exception)
        )

    @patch("ai_engineering.services.inference_client.requests.post")
    def test_valid_payload_passes_contract_checks(self, mock_post):
        payload = {
            "color_score": 80,
            "size_score": 81,
            "ripeness_score": 82,
            "confidence": 90,
            "predicted_class": "healthy",
            "class_probabilities": {"healthy": 0.9, "rotten": 0.1},
            "transparency_refs": ["xai://artifact/1"],
            "explanation_payload": {"cam": "ok"},
        }
        mock_post.return_value = _FakeResponse(payload)

        result = self.client.predict(image=object(), producer_id=1, model_version="1.2.0")

        self.assertEqual(result["predicted_class"], "healthy")
        self.assertEqual(result["model_version_used"], "1.2.0")
        self.assertIn("latency_ms", result)

    @patch("ai_engineering.services.inference_client.requests.post")
    def test_stub_payload_is_reported_as_not_implemented(self, mock_post):
        payload = {
            "color_score": 84.5,
            "size_score": 81.2,
            "ripeness_score": 79.8,
            "confidence": 91,
            "predicted_class": "fresh",
            "overall_grade": "A",
            "class_probabilities": {"fresh": 0.91, "rotten": 0.09},
            "explanation_payload": {"note": "stub-response"},
            "transparency_refs": ["xai://placeholder"],
            "model_version_used": "1.0.0",
        }
        mock_post.return_value = _FakeResponse(payload)

        with self.assertRaises(InferenceClientNotImplementedError) as error:
            self.client.predict(image=object(), producer_id=1)

        self.assertIn("not implemented in AAI yet", str(error.exception))
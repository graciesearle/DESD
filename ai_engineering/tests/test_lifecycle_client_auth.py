from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ai_engineering.services.lifecycle_client import LifecycleClient


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


@override_settings(
    AI_LIFECYCLE_SYNC_ENABLED=True,
    AI_LIFECYCLE_ALLOW_LOCAL_FALLBACK=True,
    AI_LIFECYCLE_BASE_URL="http://aai:8001",
    AI_LIFECYCLE_TIMEOUT_SECONDS=5,
    AI_MODEL_LIST_PATH="/api/task3/models/",
    AI_MODEL_UPLOAD_PATH="/api/task3/models/upload/",
    AI_MODEL_ACTIVATE_PATH="/api/task3/models/activate/",
    AI_MODEL_ROLLBACK_PATH="/api/task3/models/rollback/",
)
class LifecycleClientAuthTests(SimpleTestCase):
    @override_settings(AI_LIFECYCLE_TOKEN="secret-token")
    @patch("ai_engineering.services.lifecycle_client.requests.get")
    def test_list_models_sends_authorization_header(self, mock_get):
        mock_get.return_value = _FakeResponse({"count": 0, "results": []})

        client = LifecycleClient()
        client.list_models()

        self.assertTrue(mock_get.called)
        kwargs = mock_get.call_args.kwargs
        self.assertEqual(kwargs.get("headers"), {"Authorization": "Token secret-token"})

    @override_settings(AI_LIFECYCLE_TOKEN="secret-token")
    @patch("ai_engineering.services.lifecycle_client.requests.post")
    def test_activate_model_sends_authorization_header(self, mock_post):
        mock_post.return_value = _FakeResponse({"detail": "ok"})

        client = LifecycleClient()
        client.activate_model(model_name="produce-quality", model_version="1.0.0")

        self.assertTrue(mock_post.called)
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs.get("headers"), {"Authorization": "Token secret-token"})

    @override_settings(AI_LIFECYCLE_TOKEN="")
    @patch("ai_engineering.services.lifecycle_client.requests.get")
    def test_list_models_omits_authorization_header_without_token(self, mock_get):
        mock_get.return_value = _FakeResponse({"count": 0, "results": []})

        client = LifecycleClient()
        client.list_models()

        self.assertTrue(mock_get.called)
        kwargs = mock_get.call_args.kwargs
        self.assertEqual(kwargs.get("headers"), {})

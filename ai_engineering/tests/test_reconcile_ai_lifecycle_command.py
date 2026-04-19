from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from ai_engineering.models import AIModelVersion, ActiveModel


class ReconcileAILifecycleCommandTests(TestCase):
    @patch("ai_engineering.management.commands.reconcile_ai_lifecycle.LifecycleClient.list_models")
    def test_strict_mode_raises_when_drift_detected(self, mock_list_models):
        AIModelVersion.objects.create(
            model_name="produce-quality",
            model_version="1.0.0",
            framework="pytorch",
            checksum="local-checksum",
            artifact_path="artifacts/local-model.pth",
            manifest_json={"task_profile": "task2_quality"},
        )

        local_model = AIModelVersion.objects.get(model_name="produce-quality", model_version="1.0.0")
        ActiveModel.objects.create(model_version=local_model, is_active=True)

        mock_list_models.return_value = {
            "count": 1,
            "results": [
                {
                    "model_name": "produce-quality",
                    "model_version": "1.1.0",
                    "framework": "pytorch",
                    "checksum": "remote-checksum",
                    "artifact_path": "artifacts/remote-model.pth",
                    "task_profile": "task2_quality",
                    "is_active": True,
                }
            ],
        }

        with self.assertRaises(CommandError):
            call_command("reconcile_ai_lifecycle", "--strict")

        self.assertFalse(AIModelVersion.objects.filter(model_name="produce-quality", model_version="1.1.0").exists())

    @patch("ai_engineering.management.commands.reconcile_ai_lifecycle.LifecycleClient.list_models")
    def test_apply_mode_reconciles_models_and_active_version(self, mock_list_models):
        local_model = AIModelVersion.objects.create(
            model_name="produce-quality",
            model_version="1.0.0",
            framework="pytorch",
            checksum="local-checksum",
            artifact_path="artifacts/local-model.pth",
            manifest_json={"task_profile": "task2_quality"},
        )
        ActiveModel.objects.create(model_version=local_model, is_active=True)

        mock_list_models.return_value = {
            "count": 1,
            "results": [
                {
                    "model_name": "produce-quality",
                    "model_version": "1.1.0",
                    "framework": "pytorch",
                    "checksum": "remote-checksum",
                    "artifact_path": "artifacts/remote-model.pth",
                    "task_profile": "task2_quality",
                    "is_active": True,
                }
            ],
        }

        stdout = StringIO()
        call_command("reconcile_ai_lifecycle", "--apply", stdout=stdout)

        self.assertTrue(AIModelVersion.objects.filter(model_name="produce-quality", model_version="1.1.0").exists())

        self.assertTrue(
            ActiveModel.objects.filter(
                is_active=True,
                model_version__model_name="produce-quality",
                model_version__model_version="1.1.0",
            ).exists()
        )

        self.assertFalse(
            ActiveModel.objects.filter(
                is_active=True,
                model_version__model_name="produce-quality",
                model_version__model_version="1.0.0",
            ).exists()
        )

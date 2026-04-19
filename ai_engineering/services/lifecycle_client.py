from __future__ import annotations

from typing import Any

import requests
from django.conf import settings


class LifecycleClientError(Exception):
    pass


class LifecycleClient:
    def __init__(self):
        self.sync_enabled = settings.AI_LIFECYCLE_SYNC_ENABLED
        self.allow_local_fallback = settings.AI_LIFECYCLE_ALLOW_LOCAL_FALLBACK
        self.base_url = settings.AI_LIFECYCLE_BASE_URL.rstrip("/")
        self.timeout = settings.AI_LIFECYCLE_TIMEOUT_SECONDS
        self.token = settings.AI_LIFECYCLE_TOKEN

        self.model_list_path = settings.AI_MODEL_LIST_PATH
        self.model_upload_path = settings.AI_MODEL_UPLOAD_PATH
        self.model_activate_path = settings.AI_MODEL_ACTIVATE_PATH
        self.model_rollback_path = settings.AI_MODEL_ROLLBACK_PATH

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _handle_response(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            detail = detail or f"AI lifecycle request failed with status {response.status_code}"
            raise LifecycleClientError(str(detail))

        if not isinstance(payload, dict):
            raise LifecycleClientError("AI lifecycle response must be a JSON object")

        return payload

    def _post(self, path: str, *, data=None, files=None, json_payload=None) -> dict[str, Any]:
        try:
            response = requests.post(
                self._url(path),
                data=data,
                files=files,
                json=json_payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LifecycleClientError(f"AI lifecycle request failed: {exc}") from exc

        return self._handle_response(response)

    def _get(self, path: str, *, params=None) -> dict[str, Any]:
        try:
            response = requests.get(
                self._url(path),
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LifecycleClientError(f"AI lifecycle request failed: {exc}") from exc

        return self._handle_response(response)

    def list_models(self, *, task_profile: str | None = None) -> dict[str, Any]:
        params = {}
        if task_profile:
            params["task_profile"] = task_profile
        return self._get(self.model_list_path, params=params)

    def upload_model(
        self,
        *,
        model_name: str,
        model_version: str,
        framework: str,
        manifest_json: dict[str, Any] | None = None,
        artifact_file=None,
    ) -> dict[str, Any]:
        if artifact_file is not None:
            files = {
                "artifact": (
                    getattr(artifact_file, "name", "model.bin"),
                    artifact_file,
                    getattr(artifact_file, "content_type", "application/octet-stream"),
                )
            }
            data = {
                "model_name": model_name,
                "model_version": model_version,
                "framework": framework,
            }
            return self._post(self.model_upload_path, data=data, files=files)

        payload = {
            "model_name": model_name,
            "model_version": model_version,
            "framework": framework,
            "manifest_json": manifest_json or {},
        }
        return self._post(self.model_upload_path, json_payload=payload)

    def activate_model(self, *, model_name: str, model_version: str) -> dict[str, Any]:
        return self._post(
            self.model_activate_path,
            json_payload={
                "model_name": model_name,
                "model_version": model_version,
            },
        )

    def rollback_model(self, *, model_name: str, target_model_version: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model_name": model_name}
        if target_model_version:
            payload["target_model_version"] = target_model_version
        return self._post(self.model_rollback_path, json_payload=payload)

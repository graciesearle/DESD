import time
from typing import Any, Dict

import requests
from django.conf import settings


class InferenceClientError(Exception):
    pass


class InferenceClientNotImplementedError(InferenceClientError):
    pass


_REQUIRED_FIELDS = {
    "color_score",
    "size_score",
    "ripeness_score",
    "confidence",
    "predicted_class",
}


def _as_float_field(payload: Dict[str, Any], field_name: str) -> float:
    value = payload.get(field_name)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise InferenceClientError(f"Inference response field '{field_name}' must be numeric") from exc


def _as_dict_field(payload: Dict[str, Any], field_name: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    value = payload.get(field_name, default if default is not None else {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InferenceClientError(f"Inference response field '{field_name}' must be an object")
    return value


def _as_list_field(payload: Dict[str, Any], field_name: str, default=None):
    if default is None:
        default = []
    value = payload.get(field_name, default)
    if value is None:
        return []
    if not isinstance(value, list):
        raise InferenceClientError(f"Inference response field '{field_name}' must be a list")
    return value


def _validate_payload_schema(
    payload: Dict[str, Any],
    fallback_model_name: str | None = None,
    fallback_model_version: str | None = None,
) -> Dict[str, Any]:
    missing = _REQUIRED_FIELDS.difference(payload.keys())
    if missing:
        missing_values = ", ".join(sorted(missing))
        raise InferenceClientError(f"Inference response missing fields: {missing_values}")

    predicted_class = payload.get("predicted_class")
    if not isinstance(predicted_class, str) or not predicted_class.strip():
        raise InferenceClientError("Inference response field 'predicted_class' must be a non-empty string")

    model_name_used = payload.get("model_name_used", fallback_model_name or "unknown")
    if not isinstance(model_name_used, str) or not model_name_used.strip():
        raise InferenceClientError("Inference response field 'model_name_used' must be a non-empty string")

    model_version_used = payload.get("model_version_used", fallback_model_version or "unknown")
    if not isinstance(model_version_used, str) or not model_version_used.strip():
        raise InferenceClientError("Inference response field 'model_version_used' must be a non-empty string")

    explanation_payload = _as_dict_field(payload, "explanation_payload", default={})
    explanation_note = explanation_payload.get("note")
    if isinstance(explanation_note, str) and explanation_note.strip().lower() == "stub-response":
        raise InferenceClientNotImplementedError(
            "Task 2 inference is not implemented in AAI yet. Please wait for the updated model."
        )

    return {
        "color_score": _as_float_field(payload, "color_score"),
        "size_score": _as_float_field(payload, "size_score"),
        "ripeness_score": _as_float_field(payload, "ripeness_score"),
        "confidence": _as_float_field(payload, "confidence"),
        "predicted_class": predicted_class,
        "ai_reported_grade": payload.get("overall_grade"),
        "model_name_used": model_name_used,
        "class_probabilities": _as_dict_field(payload, "class_probabilities", default={}),
        "model_version_used": model_version_used,
        "transparency_refs": _as_list_field(payload, "transparency_refs", default=[]),
        "explanation_payload": explanation_payload,
        "inventory_action": _as_dict_field(payload, "inventory_action", default={}),
    }


class InferenceClient:
    def __init__(self):
        self.base_url = settings.AI_INFERENCE_BASE_URL.rstrip("/")
        self.predict_path = settings.AI_INFERENCE_PREDICT_PATH
        self.recommend_path = getattr(settings, "AI_RECOMMEND_PATH", "/api/task1/recommend/")
        self.timeout = settings.AI_INFERENCE_TIMEOUT_SECONDS
        self.token = getattr(settings, "AI_LIFECYCLE_TOKEN", "")

    def _headers(self) -> Dict[str, str]:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def predict(
        self,
        image,
        producer_id: int,
        product_id: int | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> Dict[str, Any]:
        endpoint = f"{self.base_url}{self.predict_path}"

        data = {
            "producer_id": producer_id,
        }
        if product_id is not None:
            data["product_id"] = product_id
        if model_name:
            data["model_name"] = model_name
        if model_version:
            data["model_version"] = model_version

        started_at = time.perf_counter()
        try:
            response = requests.post(
                endpoint,
                data=data,
                files={"image": image},
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise InferenceClientError(f"Inference request failed: {exc}") from exc
        except ValueError as exc:
            raise InferenceClientError("Inference response was not valid JSON") from exc

        latency_ms = int((time.perf_counter() - started_at) * 1000)

        result = _validate_payload_schema(
            payload,
            fallback_model_name=model_name,
            fallback_model_version=model_version,
        )
        result["latency_ms"] = latency_ms
        return result

    def recommend(
        self,
        recent_items: list[str],
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> Dict[str, Any]:
        endpoint = f"{self.base_url}{self.recommend_path}"

        json_payload = {
            "recent_items": recent_items,
        }
        if model_name:
            json_payload["model_name"] = model_name
        if model_version:
            json_payload["model_version"] = model_version

        started_at = time.perf_counter()
        try:
            response = requests.post(
                endpoint,
                json=json_payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise InferenceClientError(f"Recommendation request failed: {exc}") from exc
        except ValueError as exc:
            raise InferenceClientError("Recommendation response was not valid JSON") from exc

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        payload["latency_ms"] = latency_ms
        return payload

    def get_explanation(self, image_path, model_name, model_version, methods=None):
        """
        Calls the AAI Task 4 endpoint to get the visual audit report.
        """
        explain_path = getattr(settings, "AI_EXPLAIN_PATH", "/api/task4/explain/")
        endpoint = f"{self.base_url}{explain_path}"
        
        with open(image_path, 'rb') as img_file:
            files = {'image': img_file}
            data = {
                'model_name': model_name,
                'model_version': model_version
            }

            if methods:
                data['methods'] = ",".join(methods)
            
            response = requests.post(endpoint, data=data, files=files, headers=self._headers(), timeout=100)
            response.raise_for_status()
            return response.json()

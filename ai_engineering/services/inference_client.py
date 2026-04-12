import time
from typing import Any, Dict

import requests
from django.conf import settings


class InferenceClientError(Exception):
    pass


_REQUIRED_FIELDS = {
    "color_score",
    "size_score",
    "ripeness_score",
    "confidence",
    "predicted_class",
}


class InferenceClient:
    def __init__(self):
        self.base_url = settings.AI_INFERENCE_BASE_URL.rstrip("/")
        self.predict_path = settings.AI_INFERENCE_PREDICT_PATH
        self.timeout = settings.AI_INFERENCE_TIMEOUT_SECONDS

    def predict(self, image, producer_id: int, product_id: int | None = None, model_version: str | None = None) -> Dict[str, Any]:
        endpoint = f"{self.base_url}{self.predict_path}"

        data = {
            "producer_id": producer_id,
        }
        if product_id is not None:
            data["product_id"] = product_id
        if model_version:
            data["model_version"] = model_version

        started_at = time.perf_counter()
        try:
            response = requests.post(
                endpoint,
                data=data,
                files={"image": image},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise InferenceClientError(f"Inference request failed: {exc}") from exc
        except ValueError as exc:
            raise InferenceClientError("Inference response was not valid JSON") from exc

        latency_ms = int((time.perf_counter() - started_at) * 1000)

        missing = _REQUIRED_FIELDS.difference(payload.keys())
        if missing:
            missing_values = ", ".join(sorted(missing))
            raise InferenceClientError(f"Inference response missing fields: {missing_values}")

        result = {
            "color_score": float(payload["color_score"]),
            "size_score": float(payload["size_score"]),
            "ripeness_score": float(payload["ripeness_score"]),
            "confidence": float(payload["confidence"]),
            "predicted_class": str(payload["predicted_class"]),
            "ai_reported_grade": payload.get("overall_grade"),
            "class_probabilities": payload.get("class_probabilities", {}),
            "model_version_used": payload.get("model_version_used", model_version or "unknown"),
            "transparency_refs": payload.get("transparency_refs", []),
            "explanation_payload": payload.get("explanation_payload", {}),
            "latency_ms": latency_ms,
        }
        return result

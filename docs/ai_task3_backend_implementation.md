# AI Task 3 Backend Implementation (DESD)

## Purpose

This document describes the Django-side implementation for Task 3 (AI engineer lifecycle) and Task 2 producer quality integration in DESD.

Advanced AI model development remains in the separate Advanced AI repository. DESD handles integration, controls, and auditability.

## Scope Implemented

- `ai_engineering` app scaffold and routing under `/api/ai/`
- AI engineer role support (`AI_ENGINEER`) in `accounts`
- Model registry, activation, rollback APIs
- Producer predict and override APIs
- Retraining export API and command
- Admin metrics and prediction explanation APIs
- Activation gate checks (minimum quality + schema checks)
- Baseline tests for grading, permissions, lifecycle, inference, and export

## App Structure

- `ai_engineering/models.py`
  - `AIModelVersion`
  - `ActiveModel`
  - `InferenceRequestLog`
  - `ProducerOverrideEvent`
  - `ExportJob`
- `ai_engineering/views.py`
  - lifecycle endpoints
  - producer quality endpoints
  - export and admin endpoints
- `ai_engineering/services/`
  - `grading.py`
  - `recommendation.py`
  - `inference_client.py`
  - `export.py`

## Key API Endpoints

- `GET /api/ai/health/`
- `GET /api/ai/models/`
- `POST /api/ai/models/upload/`
- `POST /api/ai/models/activate/`
- `POST /api/ai/models/rollback/`
- `POST /api/ai/producer-quality/predict/`
- `POST /api/ai/producer-quality/override/`
- `POST /api/ai/exports/retraining/`
- `GET /api/ai/exports/<id>/`
- `GET /api/ai/admin/metrics/`
- `GET /api/ai/admin/predictions/<id>/explanation/`

## Activation Gates

Activation is blocked unless the uploaded model manifest satisfies all of:

- `metrics.weighted_f1 >= 0.85`
- `metrics.rotten_recall >= 0.80`
- `artifacts.classification_report` present
- `artifacts.confusion_matrix` present
- `input_schema` and `output_schema` present

## Grade Ownership

DESD computes and stores the authoritative grade from score breakdown values (`color`, `size`, `ripeness`).

The AI service may return a diagnostic grade. Differences are logged (`ai_grade_mismatch`) for governance and model monitoring.

## Configuration

Add to environment:

- `AI_INFERENCE_BASE_URL`
- `AI_INFERENCE_PREDICT_PATH`
- `AI_INFERENCE_TIMEOUT_SECONDS`
- `AI_EXPORT_DIR`

## Run and Validate (Docker Compose)

- Run migrations:
  - `docker compose exec web python manage.py migrate`
- Run app checks:
  - `docker compose exec web python manage.py check`
- Run tests:
  - `docker compose exec web python manage.py test ai_engineering`

## Notes for Assessment Alignment

- Keep AI model development/evaluation/XAI artifacts in the Advanced AI repo.
- Keep DESD focused on deployable integration, controls, audit trails, and service interfaces.
- Demonstrate the link between both repos during technical demo and report evidence.

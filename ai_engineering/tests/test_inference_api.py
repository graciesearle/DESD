from io import BytesIO
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from ai_engineering.models import AIModelVersion, ActiveModel, InferenceRequestLog, ProducerOverrideEvent
from ai_engineering.services.inference_client import InferenceClientError, InferenceClientNotImplementedError
from marketplace.models import Category
from products.models import Farm, Product, ProductBatch

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

        self.category = Category.objects.create(name="Vegetables", slug="veg")
        self.farm = Farm.objects.create(
            producer=self.producer,
            name="Inference Farm",
            postcode="BS1 1AA",
        )
        self.product = Product.objects.create(
            producer=self.producer,
            farm=self.farm,
            name="Inference Carrots",
            description="Test produce",
            price="3.00",
            unit="kg",
            stock_quantity=10,
            category=self.category,
            is_available=True,
        )

    def _make_inference_log(self):
        return InferenceRequestLog.objects.create(
            producer=self.producer,
            product=self.product,
            image_path="scan.png",
            color_score=60,
            size_score=60,
            ripeness_score=60,
            confidence=90,
            predicted_class="healthy",
            authoritative_grade="B",
            recommendation_action="Discount and relabel",
            explanation_payload={"inventory_action": {"discount_percent": 10}},
            model_version_used="1.0.1",
            latency_ms=123.45,
            grading_policy_version="v2",
            ai_grade_mismatch=False,
        )

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

    @patch("ai_engineering.views.InferenceClient.predict")
    def test_predict_returns_502_on_inference_contract_error(self, mock_predict):
        mock_predict.side_effect = InferenceClientError(
            "Inference response missing fields: predicted_class"
        )

        response = self.client.post(
            reverse("ai_engineering:producer-predict"),
            {"image": make_test_image()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("detail", response.data)
        self.assertEqual(InferenceRequestLog.objects.count(), 0)

    @patch("ai_engineering.views.InferenceClient.predict")
    def test_predict_returns_503_when_aai_not_implemented(self, mock_predict):
        mock_predict.side_effect = InferenceClientNotImplementedError(
            "Task 2 inference is not implemented in AAI yet. Please wait for the updated model."
        )

        response = self.client.post(
            reverse("ai_engineering:producer-predict"),
            {"image": make_test_image()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("not implemented in AAI yet", response.data.get("detail", ""))
        self.assertEqual(InferenceRequestLog.objects.count(), 0)

    @patch("ai_engineering.views.InferenceClient.predict")
    def test_predict_uses_active_model_version_when_omitted(self, mock_predict):
        model_version = AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="2.1.0",
            framework="pytorch",
            checksum="abc-active-210",
            artifact_path="/tmp/model-2.1.0.pt",
            uploaded_by=self.producer,
        )
        ActiveModel.objects.create(
            model_version=model_version,
            activated_by=self.producer,
            is_active=True,
        )

        mock_predict.return_value = {
            "color_score": 82,
            "size_score": 88,
            "ripeness_score": 86,
            "confidence": 91,
            "predicted_class": "healthy",
            "ai_reported_grade": "A",
            "class_probabilities": {"healthy": 0.91, "rotten": 0.09},
            "model_version_used": "2.1.0",
            "transparency_refs": ["xai://report/210"],
            "explanation_payload": {"saliency": "ref"},
            "latency_ms": 123,
        }

        response = self.client.post(
            reverse("ai_engineering:producer-predict"),
            {"image": make_test_image()},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(mock_predict.call_args.kwargs["model_version"], "2.1.0")

    @patch("ai_engineering.views.InferenceClient.predict")
    def test_predict_respects_explicit_model_version_override(self, mock_predict):
        model_version = AIModelVersion.objects.create(
            model_name="produce-cv",
            model_version="2.1.0",
            framework="pytorch",
            checksum="abc-active-211",
            artifact_path="/tmp/model-2.1.0.pt",
            uploaded_by=self.producer,
        )
        ActiveModel.objects.create(
            model_version=model_version,
            activated_by=self.producer,
            is_active=True,
        )

        mock_predict.return_value = {
            "color_score": 60,
            "size_score": 60,
            "ripeness_score": 60,
            "confidence": 84,
            "predicted_class": "mixed",
            "ai_reported_grade": "B",
            "class_probabilities": {"healthy": 0.40, "rotten": 0.60},
            "model_version_used": "9.9.9",
            "transparency_refs": ["xai://report/999"],
            "explanation_payload": {"saliency": "ref"},
            "latency_ms": 124,
        }

        response = self.client.post(
            reverse("ai_engineering:producer-predict"),
            {"image": make_test_image(), "model_version": "9.9.9"},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(mock_predict.call_args.kwargs["model_version"], "9.9.9")

    def test_predict_requires_image_or_saved_product_image(self):
        response = self.client.post(
            reverse("ai_engineering:producer-predict"),
            {},
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("upload an image", response.data.get("detail", "").lower())

    @patch("ai_engineering.views.InferenceClient.predict")
    def test_predict_uses_saved_product_image_when_upload_omitted(self, mock_predict):
        self.product.image = make_test_image()
        self.product.save(update_fields=["image"])

        mock_predict.return_value = {
            "color_score": 60,
            "size_score": 60,
            "ripeness_score": 60,
            "confidence": 89,
            "predicted_class": "healthy",
            "ai_reported_grade": "B",
            "class_probabilities": {"healthy": 0.89, "rotten": 0.11},
            "model_version_used": "1.0.1",
            "transparency_refs": ["xai://report/saved-image"],
            "explanation_payload": {"saliency": "ref"},
            "latency_ms": 132,
        }

        response = self.client.post(
            reverse("ai_engineering:producer-predict"),
            {"product_id": self.product.id},
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["product"], self.product.id)
        self.assertEqual(mock_predict.call_args.kwargs["product_id"], self.product.id)

        log = InferenceRequestLog.objects.get(pk=response.data["id"])
        self.assertEqual(log.image_path, self.product.image.name)

    def test_batch_create_requires_accepted_override(self):
        log = self._make_inference_log()

        resp = self.client.post(
            reverse("ai_engineering:batch-create"),
            {"inference_log_id": log.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("accepted", resp.data["detail"].lower())

        ProducerOverrideEvent.objects.create(
            inference_log=log,
            producer=self.producer,
            accepted_recommendation=False,
            override_grade="C",
            override_reason="Manual rejection",
        )
        resp = self.client.post(
            reverse("ai_engineering:batch-create"),
            {"inference_log_id": log.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_batch_create_allocates_only_unbatched_stock(self):
        ProductBatch.objects.create(
            product=self.product,
            grade="A",
            stock_quantity=6,
            base_price=self.product.price,
            discount_percent=0,
        )
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=10)
        self.product.refresh_from_db()

        log = self._make_inference_log()
        ProducerOverrideEvent.objects.create(
            inference_log=log,
            producer=self.producer,
            accepted_recommendation=True,
        )

        resp = self.client.post(
            reverse("ai_engineering:batch-create"),
            {"inference_log_id": log.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

        created_batch = ProductBatch.objects.get(pk=resp.data["batch_id"])
        self.assertEqual(created_batch.stock_quantity, 4)

    def test_intake_commit_ai_creates_batch_and_override(self):
        log = self._make_inference_log()
        log.scan_mode = "batch_intake"
        log.lot_quantity = 5
        log.save(update_fields=["scan_mode", "lot_quantity"])

        payload = {
            "product_id": self.product.id,
            "lot_quantity": 5,
            "grade_source": "ai",
            "inference_log_id": log.id,
            "accept_recommendation": True,
            "idempotency_key": str(uuid.uuid4()),
        }

        resp = self.client.post(
            reverse("ai_engineering:intake-commit"),
            payload,
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["grade"], log.authoritative_grade)
        self.assertEqual(resp.data["stock_quantity"], 5)
        self.assertEqual(ProducerOverrideEvent.objects.filter(inference_log=log, accepted_recommendation=True).count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 15)

    def test_intake_commit_manual_creates_batch_without_log(self):
        payload = {
            "product_id": self.product.id,
            "lot_quantity": 3,
            "grade_source": "manual",
            "manual_grade": "C",
            "manual_reason": "Visible bruising in lot",
            "idempotency_key": str(uuid.uuid4()),
        }

        resp = self.client.post(
            reverse("ai_engineering:intake-commit"),
            payload,
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        batch = ProductBatch.objects.get(pk=resp.data["batch_id"])
        self.assertEqual(batch.grade, "C")
        self.assertIsNone(batch.inference_log)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 13)

    def test_intake_commit_allocate_from_unbatched_keeps_total_stock_constant(self):
        payload = {
            "product_id": self.product.id,
            "lot_quantity": 4,
            "allocate_from_unbatched": True,
            "grade_source": "manual",
            "manual_grade": "A",
            "manual_reason": "Initial grade assignment from existing stock",
            "idempotency_key": str(uuid.uuid4()),
        }

        resp = self.client.post(
            reverse("ai_engineering:intake-commit"),
            payload,
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        batch = ProductBatch.objects.get(pk=resp.data["batch_id"])
        self.assertEqual(batch.stock_quantity, 4)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(self.product.unbatched_stock_quantity, 6)

    def test_intake_commit_rejects_allocate_from_unbatched_over_available(self):
        payload = {
            "product_id": self.product.id,
            "lot_quantity": 99,
            "allocate_from_unbatched": True,
            "grade_source": "manual",
            "manual_grade": "A",
            "manual_reason": "Should fail due to insufficient ungraded stock",
            "idempotency_key": str(uuid.uuid4()),
        }

        resp = self.client.post(
            reverse("ai_engineering:intake-commit"),
            payload,
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertIn("available ungraded stock", resp.data["detail"].lower())

    def test_intake_commit_is_idempotent_for_repeated_key(self):
        payload = {
            "product_id": self.product.id,
            "lot_quantity": 2,
            "grade_source": "manual",
            "manual_grade": "B",
            "manual_reason": "Manual grading",
            "idempotency_key": str(uuid.uuid4()),
        }

        first = self.client.post(
            reverse("ai_engineering:intake-commit"),
            payload,
            format="json",
        )
        second = self.client.post(
            reverse("ai_engineering:intake-commit"),
            payload,
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ProductBatch.objects.filter(product=self.product).count(), 1)
        self.assertTrue(second.data["idempotent_replay"])

    def test_batch_grade_edit_endpoint_updates_grade(self):
        batch = ProductBatch.objects.create(
            product=self.product,
            grade="B",
            stock_quantity=4,
            base_price=self.product.price,
            discount_percent=0,
        )

        resp = self.client.patch(
            reverse("ai_engineering:batch-grade-edit", args=[batch.id]),
            {"new_grade": "A", "reason": "Sample quality improved"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.grade, "A")

    def test_batch_grade_edit_endpoint_merges_existing_target_grade_bucket(self):
        source_batch = ProductBatch.objects.create(
            product=self.product,
            grade="B",
            stock_quantity=4,
            base_price=self.product.price,
            discount_percent=10,
        )
        target_batch = ProductBatch.objects.create(
            product=self.product,
            grade="A",
            stock_quantity=3,
            base_price=self.product.price,
            discount_percent=0,
        )

        resp = self.client.patch(
            reverse("ai_engineering:batch-grade-edit", args=[source_batch.id]),
            {"new_grade": "A", "reason": "Manual quality regrade"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["merged_into_existing_bucket"])
        self.assertEqual(resp.data["batch_id"], target_batch.id)

        source_batch.refresh_from_db()
        target_batch.refresh_from_db()
        self.assertEqual(source_batch.stock_quantity, 0)
        self.assertFalse(source_batch.is_active)
        self.assertEqual(target_batch.stock_quantity, 7)

    def test_intake_commit_merges_existing_active_grade_bucket(self):
        existing_batch = ProductBatch.objects.create(
            product=self.product,
            grade="B",
            stock_quantity=4,
            base_price=self.product.price,
            discount_percent=10,
        )

        log = self._make_inference_log()
        log.scan_mode = "batch_intake"
        log.lot_quantity = 5
        log.save(update_fields=["scan_mode", "lot_quantity"])

        resp = self.client.post(
            reverse("ai_engineering:intake-commit"),
            {
                "product_id": self.product.id,
                "lot_quantity": 5,
                "grade_source": "ai",
                "inference_log_id": log.id,
                "accept_recommendation": True,
                "idempotency_key": str(uuid.uuid4()),
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["batch_id"], existing_batch.id)

        existing_batch.refresh_from_db()
        self.assertEqual(existing_batch.stock_quantity, 9)
        self.assertEqual(ProductBatch.objects.filter(product=self.product, grade="B").count(), 1)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 19)

    def test_intake_commit_merges_by_grade_even_when_legacy_discount_differs(self):
        existing_batch = ProductBatch.objects.create(
            product=self.product,
            grade="C",
            stock_quantity=4,
            base_price=self.product.price,
            discount_percent=0,
        )

        resp = self.client.post(
            reverse("ai_engineering:intake-commit"),
            {
                "product_id": self.product.id,
                "lot_quantity": 3,
                "grade_source": "manual",
                "manual_grade": "C",
                "manual_reason": "Manual quality classification",
                "idempotency_key": str(uuid.uuid4()),
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["batch_id"], existing_batch.id)

        existing_batch.refresh_from_db()
        self.assertEqual(existing_batch.stock_quantity, 7)
        self.assertEqual(float(existing_batch.discount_percent), 25.0)
        self.assertEqual(ProductBatch.objects.filter(product=self.product, grade="C", is_active=True).count(), 1)

    def test_intake_commit_blocks_duplicate_commit_for_same_scan(self):
        ProductBatch.objects.create(
            product=self.product,
            grade="B",
            stock_quantity=4,
            base_price=self.product.price,
            discount_percent=10,
        )

        log = self._make_inference_log()
        log.scan_mode = "batch_intake"
        log.lot_quantity = 2
        log.save(update_fields=["scan_mode", "lot_quantity"])

        first = self.client.post(
            reverse("ai_engineering:intake-commit"),
            {
                "product_id": self.product.id,
                "lot_quantity": 2,
                "grade_source": "ai",
                "inference_log_id": log.id,
                "accept_recommendation": True,
                "idempotency_key": str(uuid.uuid4()),
            },
            format="json",
        )
        second = self.client.post(
            reverse("ai_engineering:intake-commit"),
            {
                "product_id": self.product.id,
                "lot_quantity": 2,
                "grade_source": "ai",
                "inference_log_id": log.id,
                "accept_recommendation": True,
                "idempotency_key": str(uuid.uuid4()),
            },
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertIn("already been created", second.data["detail"].lower())
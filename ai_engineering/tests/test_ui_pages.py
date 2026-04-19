from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class AIUiPageAccessTests(TestCase):
    def setUp(self):
        self.producer = User.objects.create_user(
            email="producer.ui@example.com",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
        )
        self.ai_engineer = User.objects.create_user(
            email="engineer.ui@example.com",
            password="Secure#Pass1",
            role=User.Role.AI_ENGINEER,
        )
        self.admin = User.objects.create_user(
            email="admin.ui@example.com",
            password="Secure#Pass1",
            role=User.Role.ADMIN,
        )
        self.customer = User.objects.create_user(
            email="customer.ui@example.com",
            password="Secure#Pass1",
            role=User.Role.CUSTOMER,
        )

    def test_engineer_dashboard_allows_ai_engineer(self):
        self.client.force_login(self.ai_engineer)

        response = self.client.get(reverse("ai_web:engineer_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ai_engineering/ai_engineer_dashboard.html")
        self.assertContains(response, "AI Engineer")
        self.assertContains(response, "Lifecycle Actions")
        self.assertContains(response, reverse("ai_web:engineer_models"))
        self.assertContains(response, reverse("ai_web:engineer_upload"))

    def test_engineer_lifecycle_pages_allow_ai_engineer(self):
        self.client.force_login(self.ai_engineer)

        route_names = [
            "ai_web:engineer_models",
            "ai_web:engineer_upload",
            "ai_web:engineer_activate",
            "ai_web:engineer_rollback",
            "ai_web:engineer_export",
        ]

        for route_name in route_names:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "ai_engineering/ai_engineer_lifecycle_action.html")
                self.assertContains(response, "Structured Form Mode")
                self.assertContains(response, "Use request body input (JSON)")

    def test_engineer_lifecycle_pages_block_producer(self):
        self.client.force_login(self.producer)

        route_names = [
            "ai_web:engineer_models",
            "ai_web:engineer_upload",
            "ai_web:engineer_activate",
            "ai_web:engineer_rollback",
            "ai_web:engineer_export",
        ]

        for route_name in route_names:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertRedirects(response, reverse("marketplace:product_list"))

    def test_engineer_dashboard_allows_admin(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("ai_web:engineer_dashboard"))

        self.assertEqual(response.status_code, 200)

    def test_engineer_dashboard_blocks_producer(self):
        self.client.force_login(self.producer)

        response = self.client.get(reverse("ai_web:engineer_dashboard"))

        self.assertRedirects(response, reverse("marketplace:product_list"))

    def test_producer_workbench_allows_producer(self):
        self.client.force_login(self.producer)

        response = self.client.get(reverse("ai_web:producer_workbench"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ai_engineering/producer_ai_workbench.html")
        self.assertContains(response, "AI Workbench")

    def test_producer_workbench_blocks_customer(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse("ai_web:producer_workbench"))

        self.assertRedirects(response, reverse("marketplace:product_list"))

    def test_admin_insights_allows_admin(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("ai_web:admin_insights"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ai_engineering/admin_ai_insights.html")
        self.assertContains(response, "AI Insights")

    def test_admin_insights_blocks_ai_engineer(self):
        self.client.force_login(self.ai_engineer)

        response = self.client.get(reverse("ai_web:admin_insights"))

        self.assertRedirects(response, reverse("marketplace:product_list"))

    def test_ai_pages_require_login(self):
        response = self.client.get(reverse("ai_web:producer_workbench"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

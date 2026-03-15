"""
Tests for the Producer Product Dashboard feature (TC-003).

Covers:
    - accounts.views.producer_dashboard
    - marketplace.views.product_edit
    - marketplace.views.product_toggle
    - marketplace.views.product_delete

Every view is tested for:
    1. Authentication gating (anonymous users redirected to login)
    2. Role gating (non-producer roles denied)
    3. Ownership enforcement (producer A cannot touch producer B's products)
    4. Happy-path behaviour (correct template, context, DB mutations)
    5. Edge cases (empty state, soft-delete audit trail, toggle idempotency)
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import ProducerProfile
from marketplace.models import Category
from products.models import Product, Farm

User = get_user_model()


class ProducerDashboardTestBase(TestCase):
    """
    Shared setup for all producer dashboard tests.

    Creates two producers (each with a farm and products) and one
    customer so ownership and role isolation can be verified.
    """

    @classmethod
    def setUpTestData(cls):
        # ----- Producer A (primary test subject) ----- #
        cls.producer_a = User.objects.create_user(
            email="alice@farm.co.uk",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
        )
        ProducerProfile.objects.create(
            user=cls.producer_a,
            business_name="Alice's Organics",
            contact_name="Alice Smith",
            address="1 Farm Lane",
            postcode="BS1 1AA",
        )
        cls.farm_a = Farm.objects.create(
            producer=cls.producer_a,
            name="Greenfield Farm",
            postcode="BS1 1AA",
        )
        cls.category = Category.objects.create(
            name="Vegetables",
            slug="vegetables",
        )

        cls.active_product = Product.objects.create(
            producer=cls.producer_a,
            farm=cls.farm_a,
            name="Organic Carrots",
            description="Fresh organic carrots.",
            price=Decimal("2.50"),
            unit="kg",
            stock_quantity=50,
            category=cls.category,
            is_available=True,
        )
        cls.inactive_product = Product.objects.create(
            producer=cls.producer_a,
            farm=cls.farm_a,
            name="Winter Kale",
            description="Seasonal kale.",
            price=Decimal("3.00"),
            unit="bunch",
            stock_quantity=0,
            category=cls.category,
            is_available=False,
        )

        # ----- Producer B (for ownership isolation) ----- #
        cls.producer_b = User.objects.create_user(
            email="bob@farm.co.uk",
            password="Secure#Pass2",
            role=User.Role.PRODUCER,
        )
        cls.farm_b = Farm.objects.create(
            producer=cls.producer_b,
            name="Hillside Farm",
            postcode="BS2 2BB",
        )
        cls.other_product = Product.objects.create(
            producer=cls.producer_b,
            farm=cls.farm_b,
            name="Free Range Eggs",
            description="Farm fresh eggs.",
            price=Decimal("4.00"),
            unit="dozen",
            stock_quantity=20,
            category=cls.category,
            is_available=True,
        )

        # ----- Customer (for role isolation) ----- #
        cls.customer = User.objects.create_user(
            email="charlie@example.com",
            password="Secure#Pass3",
            role=User.Role.CUSTOMER,
        )

    def setUp(self):
        self.client = Client()


# ===================================================================
# accounts.views.producer_dashboard
# ===================================================================


class ProducerDashboardViewTests(ProducerDashboardTestBase):
    """Tests for the main dashboard view at /accounts/producer/dashboard/."""

    def url(self):
        return reverse("producer_dashboard")

    # -- Authentication & authorisation -- #

    def test_anonymous_user_redirected_to_login(self):
        """Unauthenticated requests must redirect to the login page."""
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_customer_role_denied(self):
        """Non-producer roles must receive a 403 Forbidden."""
        self.client.login(email="charlie@example.com", password="Secure#Pass3")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 403)

    # -- Happy path -- #

    def test_producer_can_access_dashboard(self):
        """A producer should receive a 200 with the correct template."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/producer_dashboard.html")

    def test_context_contains_all_products(self):
        """Dashboard must show both active and inactive products."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        products = list(response.context["products"])
        self.assertIn(self.active_product, products)
        self.assertIn(self.inactive_product, products)

    def test_context_excludes_other_producer_products(self):
        """A producer must never see another producer's products."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        products = list(response.context["products"])
        self.assertNotIn(self.other_product, products)

    def test_summary_counts_are_correct(self):
        """Aggregate stats must match the producer's actual inventory."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        self.assertEqual(response.context["total_count"], 2)
        self.assertEqual(response.context["active_count"], 1)
        self.assertEqual(response.context["inactive_count"], 1)
        # Winter Kale has stock_quantity=0
        self.assertEqual(response.context["out_of_stock_count"], 1)

    def test_dashboard_shows_business_name(self):
        """The page should display the producer's business name."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        self.assertContains(response, "Alice&#x27;s Organics")

    def test_dashboard_shows_email(self):
        """The page should display the producer's email as a subtitle."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        self.assertContains(response, "alice@farm.co.uk")

    def test_products_ordered_by_updated_at_desc(self):
        """Products should appear most-recently-updated first."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        # Touch inactive_product to make it the most recent.
        self.inactive_product.save()
        response = self.client.get(self.url())
        products = list(response.context["products"])
        self.assertEqual(products[0], self.inactive_product)

    # -- Empty state -- #

    def test_empty_state_for_new_producer(self):
        """A producer with no products should see the empty-state message."""
        new_producer = User.objects.create_user(
            email="dawn@farm.co.uk",
            password="Secure#Pass4",
            role=User.Role.PRODUCER,
        )
        self.client.login(email="dawn@farm.co.uk", password="Secure#Pass4")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You have not listed any products yet.")
        self.assertEqual(response.context["total_count"], 0)

    # -- Soft-deleted products hidden -- #

    def test_soft_deleted_products_are_hidden(self):
        """Soft-deleted products must not appear on the dashboard."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        self.active_product.delete()  # Soft-delete
        response = self.client.get(self.url())
        products = list(response.context["products"])
        self.assertNotIn(self.active_product, products)
        self.assertEqual(response.context["total_count"], 1)
        # Restore for other tests.
        self.active_product.is_deleted = False
        self.active_product.deleted_at = None
        self.active_product.save()


# ===================================================================
# marketplace.views.product_edit
# ===================================================================


class ProductEditViewTests(ProducerDashboardTestBase):
    """Tests for the product edit view at /marketplace/edit/<pk>/."""

    def url(self, pk=None):
        return reverse("marketplace:product_edit", args=[pk or self.active_product.pk])

    # -- Authentication & authorisation -- #

    def test_anonymous_user_redirected(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_customer_denied(self):
        self.client.login(email="charlie@example.com", password="Secure#Pass3")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 403)

    # -- Ownership -- #

    def test_producer_cannot_edit_other_producers_product(self):
        """Accessing another producer's product must return 404, not 403."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url(pk=self.other_product.pk))
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_product_returns_404(self):
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url(pk=99999))
        self.assertEqual(response.status_code, 404)

    # -- GET (display form) -- #

    def test_edit_form_loads_with_product_data(self):
        """The form should be pre-populated with the existing product values."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "marketplace/product_form.html")
        self.assertTrue(response.context["editing"])
        self.assertEqual(response.context["product"], self.active_product)

    def test_edit_form_heading(self):
        """The template should render 'Edit Product', not 'Add Produce'."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        self.assertContains(response, "Edit Product")
        self.assertNotContains(response, "Add Produce")

    # -- POST (submit edit) -- #

    def test_valid_edit_updates_product(self):
        """A valid POST should update the product and redirect to dashboard."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(self.url(), {
            "name": "Updated Carrots",
            "description": "Now even fresher.",
            "price": "3.00",
            "unit": "kg",
            "stock_quantity": "40",
            "low_stock_threshold": "5",
            "category": self.category.pk,
            "farm": self.farm_a.pk,
            "is_available": "on",
        })
        self.assertRedirects(response, reverse("producer_dashboard"))
        self.active_product.refresh_from_db()
        self.assertEqual(self.active_product.name, "Updated Carrots")
        self.assertEqual(self.active_product.price, Decimal("3.00"))

    def test_edit_success_message_uses_new_name(self):
        """Flash message should reference the updated name, not the old one."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(self.url(), {
            "name": "Renamed Carrots",
            "description": "New description.",
            "price": "2.50",
            "unit": "kg",
            "stock_quantity": "50",
            "low_stock_threshold": "5",
            "category": self.category.pk,
            "farm": self.farm_a.pk,
            "is_available": "on",
        }, follow=True)
        messages = list(response.context["messages"])
        self.assertEqual(len(messages), 1)
        self.assertIn("Renamed Carrots", str(messages[0]))

    def test_invalid_edit_redisplays_form(self):
        """An invalid POST (e.g. missing name) should re-render the form with errors."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(self.url(), {
            "name": "",  # Required field left blank.
            "description": "Still valid.",
            "price": "2.50",
            "unit": "kg",
            "stock_quantity": "50",
            "category": self.category.pk,
            "farm": self.farm_a.pk,
        })
        self.assertEqual(response.status_code, 200)  # Form re-rendered, not redirect.
        self.assertTrue(response.context["form"].errors)


# ===================================================================
# marketplace.views.product_toggle
# ===================================================================


class ProductToggleViewTests(ProducerDashboardTestBase):
    """Tests for the toggle view at /marketplace/toggle/<pk>/."""

    def url(self, pk=None):
        return reverse("marketplace:product_toggle", args=[pk or self.active_product.pk])

    # -- HTTP method enforcement -- #

    def test_get_request_not_allowed(self):
        """GET requests must be rejected (POST-only endpoint)."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 405)

    # -- Authentication & authorisation -- #

    def test_anonymous_post_redirected(self):
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_customer_denied(self):
        self.client.login(email="charlie@example.com", password="Secure#Pass3")
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 403)

    # -- Ownership -- #

    def test_cannot_toggle_other_producers_product(self):
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(self.url(pk=self.other_product.pk))
        self.assertEqual(response.status_code, 404)

    # -- Happy path -- #

    def test_toggle_deactivates_active_product(self):
        """Toggling an active product should set is_available=False."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        self.assertTrue(self.active_product.is_available)
        response = self.client.post(self.url())
        self.assertRedirects(response, reverse("producer_dashboard"))
        self.active_product.refresh_from_db()
        self.assertFalse(self.active_product.is_available)
        # Restore.
        self.active_product.is_available = True
        self.active_product.save()

    def test_toggle_activates_inactive_product(self):
        """Toggling an inactive product should set is_available=True."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        self.assertFalse(self.inactive_product.is_available)
        response = self.client.post(self.url(pk=self.inactive_product.pk))
        self.assertRedirects(response, reverse("producer_dashboard"))
        self.inactive_product.refresh_from_db()
        self.assertTrue(self.inactive_product.is_available)
        # Restore.
        self.inactive_product.is_available = False
        self.inactive_product.save()

    def test_toggle_flash_message_deactivated(self):
        """Flash message should say 'deactivated' when turning off."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(self.url(), follow=True)
        messages = list(response.context["messages"])
        self.assertIn("deactivated", str(messages[0]))
        # Restore.
        self.active_product.is_available = True
        self.active_product.save()

    def test_toggle_flash_message_activated(self):
        """Flash message should say 'activated' when turning on."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(self.url(pk=self.inactive_product.pk), follow=True)
        messages = list(response.context["messages"])
        self.assertIn("activated", str(messages[0]))
        # Restore.
        self.inactive_product.is_available = False
        self.inactive_product.save()

    def test_double_toggle_is_idempotent(self):
        """Toggling twice should return the product to its original state."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        original = self.active_product.is_available
        self.client.post(self.url())
        self.client.post(self.url())
        self.active_product.refresh_from_db()
        self.assertEqual(self.active_product.is_available, original)


# ===================================================================
# marketplace.views.product_delete
# ===================================================================


class ProductDeleteViewTests(ProducerDashboardTestBase):
    """Tests for the delete view at /marketplace/delete/<pk>/."""

    def url(self, pk=None):
        return reverse("marketplace:product_delete", args=[pk or self.active_product.pk])

    # -- HTTP method enforcement -- #

    def test_get_request_not_allowed(self):
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 405)

    # -- Authentication & authorisation -- #

    def test_anonymous_post_redirected(self):
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_customer_denied(self):
        self.client.login(email="charlie@example.com", password="Secure#Pass3")
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 403)

    # -- Ownership -- #

    def test_cannot_delete_other_producers_product(self):
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(self.url(pk=self.other_product.pk))
        self.assertEqual(response.status_code, 404)

    # -- Happy path -- #

    def test_delete_soft_deletes_product(self):
        """
        Deleting a product should soft-delete it: the record stays in
        the database but is hidden from the default manager.
        """
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        # Create a disposable product for this test.
        product = Product.objects.create(
            producer=self.producer_a,
            farm=self.farm_a,
            name="Disposable Lettuce",
            description="For deletion test.",
            price=Decimal("1.50"),
            unit="each",
            stock_quantity=10,
            category=self.category,
            is_available=True,
        )
        response = self.client.post(self.url(pk=product.pk))
        self.assertRedirects(response, reverse("producer_dashboard"))

        # Invisible to default manager.
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())
        # Still in the database via the audit manager.
        audit_record = Product.all_objects.get(pk=product.pk)
        self.assertTrue(audit_record.is_deleted)
        self.assertIsNotNone(audit_record.deleted_at)

    def test_delete_flash_message(self):
        """Flash message should confirm the product was removed by name."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        product = Product.objects.create(
            producer=self.producer_a,
            farm=self.farm_a,
            name="Spinach Bunch",
            description="For flash test.",
            price=Decimal("2.00"),
            unit="bunch",
            stock_quantity=5,
            category=self.category,
            is_available=True,
        )
        response = self.client.post(self.url(pk=product.pk), follow=True)
        messages = list(response.context["messages"])
        self.assertIn("Spinach Bunch", str(messages[0]))
        self.assertIn("removed", str(messages[0]))

    def test_delete_nonexistent_product_returns_404(self):
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(self.url(pk=99999))
        self.assertEqual(response.status_code, 404)


# ===================================================================
# Navigation and redirect integration
# ===================================================================


class DashboardNavigationTests(ProducerDashboardTestBase):
    """Tests that navigation links and redirects are wired correctly."""

    def test_nav_shows_my_products_link_for_producer(self):
        """The navbar should contain a 'My Products' link for producers."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(reverse("marketplace:product_list"))
        self.assertContains(response, reverse("producer_dashboard"))
        self.assertContains(response, "My Products")

    def test_nav_hides_my_products_link_for_customer(self):
        """Customers should not see the 'My Products' link."""
        self.client.login(email="charlie@example.com", password="Secure#Pass3")
        response = self.client.get(reverse("marketplace:product_list"))
        self.assertNotContains(response, "My Products")

    def test_product_add_redirects_to_dashboard(self):
        """After successfully adding a product, the producer lands on the dashboard."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.post(reverse("marketplace:product_add"), {
            "name": "New Broccoli",
            "description": "Very green.",
            "price": "1.80",
            "unit": "each",
            "stock_quantity": "25",
            "low_stock_threshold": "5",
            "category": self.category.pk,
            "farm": self.farm_a.pk,
            "is_available": "on",
        })
        self.assertRedirects(response, reverse("producer_dashboard"))

    def test_product_edit_cancel_links_to_dashboard(self):
        """The cancel button on the edit form should link back to the dashboard."""
        self.client.login(email="alice@farm.co.uk", password="Secure#Pass1")
        response = self.client.get(
            reverse("marketplace:product_edit", args=[self.active_product.pk])
        )
        self.assertContains(response, reverse("producer_dashboard"))

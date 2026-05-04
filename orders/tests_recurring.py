from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.core import mail
from django.contrib.auth import get_user_model
from accounts.models import CustomerProfile

from .forms import CheckoutForm
from .models import Notification, RecurringOrderTemplate, RecurringOrderItem, Order
from .services.recurring_orders import generate_draft_from_template
from .tests.test_orders import OrderTestHelperMixin
from decimal import Decimal

from unittest.mock import patch

User = get_user_model()

class RecurringOrderSystemTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        # Create a Restaurant user
        self.chef = User.objects.create_user(email="chef@bristol-eats.com", password="pass", role="RESTAURANT")
        CustomerProfile.objects.create(user=self.chef, full_name="Head Chef", delivery_address="123 Kitchen St", postcode="BS1 1AA")
        
        # Create a Producer
        self.producer = self._create_producer(email="farm@test.com", lead_time_hours=72) # 3 days lead time
        self.product = self._create_product(self.producer, name="Heritage Potatoes", stock=10)
        
        # Setup Template
        self.template = RecurringOrderTemplate.objects.create(
            customer=self.chef,
            frequency='WEEKLY',
            order_day=0, # Monday
            delivery_day=4, # Friday (4 days gap > 72h)
            delivery_address="123 Kitchen St",
            delivery_postcode="BS1 1AA",
            next_order_date=timezone.localdate()
        )
        self.t_item = RecurringOrderItem.objects.create(
            template=self.template, product=self.product, quantity=5, unit_price_at_setup=self.product.price
        )

    # =========================================================================
    # 1. ACCESS CONTROL
    # =========================================================================
    def test_only_restaurants_can_access_recurring_dashboard(self):
        """Ensure regular customers are blocked from recurring management."""
        # 1. Create a customer role
        regular_user = self._create_customer(email="regular-buyer@test.com")
        
        # 2. Verify role is not restaurant
        self.assertEqual(regular_user.role, "CUSTOMER")

        # 3. Login using the credentials of the user object
        self.client.login(email=regular_user.email, password="TestPass123!")
        
        # 4. Attempt to access restaurant-only dashboard
        response = self.client.get(reverse('orders:recurring_management'))
        
        # 5. Assert: they are kicked out (302 Redirect)
        self.assertEqual(response.status_code, 302)
        
        # 6. Verify they were sent to the right place (e.g., order list)
        self.assertIn(reverse('orders:order_list'), response.url)

    # =========================================================================
    # 2. LEAD TIME VALIDATION
    # =========================================================================
    def test_checkout_enforces_max_producer_lead_time(self):
        """Verify the checkout form blocks recurring schedules that violate producer lead times."""
        self.client.login(email="chef@bristol-eats.com", password="pass")
        
        # Producer requires 72h (3 days). 
        # We try to set Order: Monday (0), Delivery: Tuesday (1). Gap = 24h.
        form = CheckoutForm(data={
            'delivery_address': 'Test',
            'delivery_postcode': 'BS1',
            'is_recurring': True,
            'frequency': 'WEEKLY',
            'order_day': 0,
            'delivery_day': 1 
        }, max_lead_time_hours=72)
        
        self.assertFalse(form.is_valid())
        self.assertIn("Delivery day must be at least 72 hours after the order day", form.errors['__all__'][0])

    # =========================================================================
    # 3. ISOLATION (DRAFT VS TEMPLATE)
    # =========================================================================
    def test_draft_modification_does_not_change_template(self):
        """Verify modification applies only to next order, not the template."""
        draft_order = generate_draft_from_template(self.template)
        item = draft_order.items.first()

        self.client.login(email="chef@bristol-eats.com", password="pass")
        # Change quantity of this draft to 2 (from 5)
        self.client.post(reverse('orders:review_draft', args=[draft_order.order_number]), {
            'action': 'update',
            f'item_qty_{item.id}': 2
        })

        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)
        
        # Template must still be 5
        self.t_item.refresh_from_db()
        self.assertEqual(self.t_item.quantity, 5)

    # =========================================================================
    # 4. NOTIFICATIONS & EMAILS
    # =========================================================================
    def test_notifications_sent_on_draft_generation(self):
        """Test that the customer receives an email and notification when a draft is ready."""
        mail.outbox = [] # Clear mailbox
        generate_draft_from_template(self.template)

        # 1. Check Database Notification
        self.assertTrue(Notification.objects.filter(
            recipient=self.chef, 
            notification_type=Notification.Type.RECURRING_DRAFT
        ).exists())

        # 2. Check Email Output
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Update regarding your Recurring Order", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [self.chef.email])

    def test_stock_issue_triggers_alert_notification(self):
        """Unavailable products in recurring orders trigger alerts."""
        # Set stock to lower than template quantity
        self.product.stock_quantity = 2 
        self.product.save()

        generate_draft_from_template(self.template)

        notif = Notification.objects.filter(recipient=self.chef).latest('created_at')
        self.assertEqual(notif.notification_type, Notification.Type.RECURRING_ISSUE)
        self.assertIn("Stock Alert", notif.message)
        self.assertIn("Heritage Potatoes", notif.message)

    def test_producer_receives_notice_via_forecast(self):
        """Producers receive advance notice."""
        # Forecast is built from RecurringOrderItem (the templates)
        self.client.login(email="farm@test.com", password="TestPass123!")
        response = self.client.get(reverse('orders:producer_recurring_forecast'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Heritage Potatoes")
        self.assertContains(response, "5") # The expected quantity


    # =========================================================================
    # 5. PRICE CHANGE TESTS
    # =========================================================================

    def test_price_change_logic(self):
        """Verify that price changes are detected by the model."""
        # Change the product price in the database
        new_price = Decimal("4.00")
        self.product.price = new_price
        self.product.save()

        draft_order = generate_draft_from_template(self.template)
        o_item = draft_order.items.first()
        self.assertTrue(o_item.has_price_change(), "OrderItem should detect the price differs from the template.")

    @patch('stripe.checkout.Session.retrieve')
    def test_payment_success_updates_template_contract_price(self, mock_retrieve):
        mock_session = type('MockSession', (), {'payment_status': 'paid', 'payment_intent': 'pi_123', 'id': 'cs_123'})
        mock_retrieve.return_value = mock_session

        # Setup Order and Price Change
        self.product.price = Decimal("5.00")
        self.product.save()
        draft_order = generate_draft_from_template(self.template)
        draft_order.status = Order.Status.PENDING
        draft_order.save()

        # Call payment_success
        self.client.login(email="chef@bristol-eats.com", password="pass")
        response = self.client.get(reverse('orders:payment_success'), {
            'session_id': 'test_session',
            'order_number': draft_order.order_number
        })
        
        self.assertEqual(response.status_code, 302)
        
        # Verify Template was updated
        self.t_item.refresh_from_db()
        self.assertEqual(self.t_item.unit_price_at_setup, Decimal("5.00"))
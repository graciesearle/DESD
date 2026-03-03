from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import ProducerProfile, CustomerProfile
from cart.models import Cart, CartItem
from marketplace.models import Category
from products.models import Farm, Product

from .models import Order, OrderItem, Payment, Notification

User = get_user_model()


class OrderTestHelperMixin:
    """Shared fixtures for order tests."""

    def _create_producer(self, email="producer@test.com"):
        user = User.objects.create_user(
            email=email, password="TestPass123!", role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=user,
            business_name="Test Farm Co",
            contact_name="Jane Farmer",
            address="123 Farm Lane",
            postcode="BS1 1AA",
            lead_time_hours=48,
        )
        return user

    def _create_customer(self, email="customer@test.com"):
        user = User.objects.create_user(
            email=email, password="TestPass123!", role="CUSTOMER",
        )
        CustomerProfile.objects.create(
            user=user,
            full_name="John Buyer",
            delivery_address="456 High Street",
            postcode="BS2 2BB",
        )
        return user

    def _create_product(self, producer, name="Organic Carrots", price="3.50", stock=100):
        category = Category.objects.get_or_create(
            name="Vegetables",
            defaults={"description": "Fresh veg"},
        )[0]
        farm = Farm.objects.create(
            producer=producer,
            name="Sunny Farm",
            postcode="BS3 3CC",
        )
        return Product.objects.create(
            producer=producer,
            farm=farm,
            name=name,
            description="Freshly picked",
            price=Decimal(price),
            unit="kg",
            stock_quantity=stock,
            category=category,
            is_available=True,
        )

    def _add_to_cart(self, user, product, quantity=2):
        cart, _ = Cart.objects.get_or_create(user=user, status="active")
        item, created = CartItem.objects.get_or_create(
            cart=cart, product=product,
            defaults={"quantity": quantity},
        )
        if not created:
            item.quantity = quantity
            item.save()
        return cart

    def _valid_delivery_date(self):
        """Return a date that is safely beyond the 48-hour lead time."""
        return (timezone.now() + timedelta(hours=72)).date()


# ==========================================================================
# Model tests
# ==========================================================================

class OrderModelTests(OrderTestHelperMixin, TestCase):

    # Check that saving an order auto-generates an ORD-XXXXXXXX number.
    def test_order_number_generated_on_save(self):
        producer = self._create_producer()
        customer = self._create_customer()
        order = Order.objects.create(
            customer=customer,
            producer=producer,
            delivery_address="123 Street",
            delivery_postcode="BS1 1AA",
            delivery_date=self._valid_delivery_date(),
            subtotal=Decimal("10.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("0.50"),
            total=Decimal("10.50"),
            producer_payment=Decimal("9.50"),
        )
        self.assertTrue(order.order_number.startswith("ORD-"))
        self.assertEqual(len(order.order_number), 12)  # ORD- + 8 hex chars

    # Check that new orders default to PENDING status.
    def test_order_status_default_pending(self):
        producer = self._create_producer()
        customer = self._create_customer()
        order = Order.objects.create(
            customer=customer,
            producer=producer,
            delivery_address="123 Street",
            delivery_postcode="BS1 1AA",
            delivery_date=self._valid_delivery_date(),
            subtotal=0, commission_rate=Decimal("0.05"),
            commission_amount=0, total=0, producer_payment=0,
        )
        self.assertEqual(order.status, Order.Status.PENDING)

    # Verify subtotal, commission, and producer payment are computed correctly.
    def test_calculate_financials(self):
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="10.00")

        order = Order.objects.create(
            customer=customer,
            producer=producer,
            delivery_address="123 Street",
            delivery_postcode="BS1 1AA",
            delivery_date=self._valid_delivery_date(),
            subtotal=0,
            commission_rate=Decimal("0.05"),
            commission_amount=0,
            total=0,
            producer_payment=0,
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            unit_price=Decimal("10.00"),
            quantity=3,
        )
        order.calculate_financials()
        # TC-025: commission is included in total, not added on top
        self.assertEqual(order.subtotal, Decimal("30.00"))
        self.assertEqual(order.total, Decimal("30.00"))
        self.assertEqual(order.commission_amount, Decimal("1.50"))
        self.assertEqual(order.producer_payment, Decimal("28.50"))
        # Verify: commission + producer_payment == total
        self.assertEqual(
            order.commission_amount + order.producer_payment,
            order.total,
        )


class PaymentModelTests(OrderTestHelperMixin, TestCase):

    # Check that saving a payment auto-generates a TXN- transaction ID.
    def test_transaction_id_generated(self):
        producer = self._create_producer()
        customer = self._create_customer()
        order = Order.objects.create(
            customer=customer, producer=producer,
            delivery_address="x", delivery_postcode="x",
            delivery_date=self._valid_delivery_date(),
            subtotal=10, commission_rate=Decimal("0.05"),
            commission_amount=Decimal("0.50"), total=Decimal("10.50"),
            producer_payment=Decimal("9.50"),
        )
        payment = Payment.objects.create(
            order=order, amount=Decimal("10.50"),
            status=Payment.Status.SUCCESS,
        )
        self.assertTrue(payment.transaction_id.startswith("TXN-"))


# ==========================================================================
# Form tests
# ==========================================================================

class CheckoutFormTests(OrderTestHelperMixin, TestCase):

    # Delivery date before the producer lead time should be rejected.
    def test_delivery_date_too_early_rejected(self):
        from .forms import CheckoutForm

        form = CheckoutForm(data={
            "delivery_address": "123 Street",
            "delivery_postcode": "BS1 1AA",
            "delivery_date": timezone.now().date().isoformat(),  # today = too early
        }, lead_time_hours=48)
        self.assertFalse(form.is_valid())
        self.assertIn("delivery_date", form.errors)

    # Delivery date beyond the lead time should be accepted.
    def test_valid_delivery_date_accepted(self):
        from .forms import CheckoutForm

        future = self._valid_delivery_date()
        form = CheckoutForm(data={
            "delivery_address": "123 Street",
            "delivery_postcode": "BS1 1AA",
            "delivery_date": future.isoformat(),
        }, lead_time_hours=48)
        self.assertTrue(form.is_valid())


# ==========================================================================
# View / integration tests
# ==========================================================================

class CheckoutViewTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self.cart = self._add_to_cart(self.customer, self.product, quantity=2)
        self.client.login(email="customer@test.com", password="TestPass123!")

    # Checkout page renders and displays the cart products.
    def test_checkout_page_loads(self):
        response = self.client.get(reverse("orders:checkout"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Checkout")
        self.assertContains(response, "Organic Carrots")

    # An empty cart should redirect away from checkout.
    def test_checkout_redirects_empty_cart(self):
        CartItem.objects.all().delete()
        response = self.client.get(reverse("orders:checkout"))
        self.assertRedirects(response, reverse("cart:cart_detail"))

    # Cart with items from multiple producers should be blocked. TODO: implement multi-producer carts and remove this test.
    def test_checkout_blocks_multi_producer(self):
        """Cart with items from two producers should redirect back."""
        producer2 = self._create_producer(email="producer2@test.com")
        product2 = self._create_product(producer2, name="Tomatoes")
        self._add_to_cart(self.customer, product2, quantity=1)
        response = self.client.get(reverse("orders:checkout"))
        self.assertRedirects(response, reverse("cart:cart_detail"))

    # Valid checkout creates an order with correct financial breakdown.
    def test_successful_checkout_creates_order(self):
        delivery = self._valid_delivery_date()
        response = self.client.post(reverse("orders:checkout"), {
            "delivery_address": "789 New Road",
            "delivery_postcode": "BS4 4DD",
            "delivery_date": delivery.isoformat(),
        })
        # Should redirect to confirmation
        self.assertEqual(response.status_code, 302)

        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.delivery_address, "789 New Road")

        # Financial checks – TC-025: commission included in total
        expected_subtotal = Decimal("3.50") * 2  # £7.00
        expected_commission = Decimal("0.35")     # 5% of £7.00
        expected_producer_payment = Decimal("6.65")  # 95% of £7.00

        self.assertEqual(order.subtotal, expected_subtotal)
        self.assertEqual(order.total, expected_subtotal)  # total == subtotal
        self.assertEqual(order.commission_amount, expected_commission)
        self.assertEqual(order.producer_payment, expected_producer_payment)
        # commission + producer_payment == total
        self.assertEqual(
            order.commission_amount + order.producer_payment,
            order.total,
        )

    # Payment record is created with SUCCESS status after checkout.
    def test_payment_recorded(self):
        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "789 New Road",
            "delivery_postcode": "BS4 4DD",
            "delivery_date": delivery.isoformat(),
        })
        order = Order.objects.get(customer=self.customer)
        self.assertTrue(hasattr(order, "payment"))
        self.assertEqual(order.payment.status, Payment.Status.SUCCESS)
        self.assertEqual(order.payment.amount, order.total)

    # Cart status changes to 'ordered' after successful checkout.
    def test_cart_marked_ordered(self):
        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "789 New Road",
            "delivery_postcode": "BS4 4DD",
            "delivery_date": delivery.isoformat(),
        })
        self.cart.refresh_from_db()
        self.assertEqual(self.cart.status, "ordered")

    # Product stock quantity is reduced by the ordered amount.
    def test_stock_reduced_after_order(self):
        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "789 New Road",
            "delivery_postcode": "BS4 4DD",
            "delivery_date": delivery.isoformat(),
        })
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 98)  # 100 - 2

    # Notifications are sent to both producer and customer after order.
    def test_notifications_created(self):
        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "789 New Road",
            "delivery_postcode": "BS4 4DD",
            "delivery_date": delivery.isoformat(),
        })
        # Producer notification
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.producer,
                notification_type=Notification.Type.NEW_ORDER,
            ).exists()
        )
        # Customer notification
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer,
                notification_type=Notification.Type.ORDER_CONFIRMED,
            ).exists()
        )

    # Producers should not be able to access the checkout page.
    def test_producer_cannot_access_checkout(self):
        self.client.logout()
        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(reverse("orders:checkout"))
        self.assertNotEqual(response.status_code, 200)


class OrderConfirmationViewTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self._add_to_cart(self.customer, self.product, quantity=1)
        self.client.login(email="customer@test.com", password="TestPass123!")

        # Place an order
        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "Test Address",
            "delivery_postcode": "BS1 1AA",
            "delivery_date": delivery.isoformat(),
        })
        self.order = Order.objects.get(customer=self.customer)

    # Confirmation page loads and shows the order number.
    def test_confirmation_page_loads(self):
        response = self.client.get(
            reverse("orders:order_confirmation", args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, "Order Confirmed")

    # A different customer cannot view someone else's confirmation.
    def test_other_user_cannot_see_confirmation(self):
        other = self._create_customer(email="other@test.com")
        self.client.logout()
        self.client.login(email="other@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_confirmation", args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 404)


class OrderListViewTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self._add_to_cart(self.customer, self.product, quantity=1)
        self.client.login(email="customer@test.com", password="TestPass123!")

        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "Test", "delivery_postcode": "BS1 1AA",
            "delivery_date": delivery.isoformat(),
        })

    # Customer sees their own orders in the order list.
    def test_customer_sees_own_orders(self):
        response = self.client.get(reverse("orders:order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ORD-")

    # Producer sees incoming orders assigned to them.
    def test_producer_sees_incoming_orders(self):
        self.client.logout()
        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(reverse("orders:order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ORD-")


class OrderDetailViewTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self._add_to_cart(self.customer, self.product, quantity=1)
        self.client.login(email="customer@test.com", password="TestPass123!")

        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "Test", "delivery_postcode": "BS1 1AA",
            "delivery_date": delivery.isoformat(),
        })
        self.order = Order.objects.get(customer=self.customer)

    # Customer can view the detail page for their own order.
    def test_customer_can_view_detail(self):
        response = self.client.get(
            reverse("orders:order_detail", args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)

    # Producer can view the detail page for orders assigned to them.
    def test_producer_can_view_detail(self):
        self.client.logout()
        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_detail", args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)

    # An unrelated user is redirected away from another user's order.
    def test_other_user_cannot_view_detail(self):
        other = self._create_customer(email="other@test.com")
        self.client.logout()
        self.client.login(email="other@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_detail", args=[self.order.order_number])
        )
        self.assertRedirects(response, reverse("orders:order_list"))


class CommissionCalculationTests(OrderTestHelperMixin, TestCase):
    """
    TC-025: Verify the 5% network commission is accurately calculated.
    Uses the exact examples from the test case specification.
    """

    # £100 order should yield £5 commission and £95 producer payment.
    def test_tc025_single_producer_100(self):
        """TC-025 Step 8: order total £100 → commission £5, producer £95."""
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="50.00", stock=200)

        order = Order.objects.create(
            customer=customer,
            producer=producer,
            delivery_address="Test",
            delivery_postcode="BS1 1AA",
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
            subtotal=0, commission_amount=0, total=0, producer_payment=0,
        )
        # 2 × £50.00 = £100.00
        OrderItem.objects.create(
            order=order, product=product,
            product_name=product.name,
            unit_price=Decimal("50.00"), quantity=2,
        )
        order.calculate_financials()

        self.assertEqual(order.total, Decimal("100.00"))
        self.assertEqual(order.commission_amount, Decimal("5.00"))
        self.assertEqual(order.producer_payment, Decimal("95.00"))
        self.assertEqual(
            order.commission_amount + order.producer_payment,
            order.total,
        )

    # Commission is rounded to exactly 2 decimal places.
    def test_commission_accurate_to_2_decimal_places(self):
        """TC-025: Commission calculations are accurate to 2 decimal places."""
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="7.33", stock=200)

        order = Order.objects.create(
            customer=customer,
            producer=producer,
            delivery_address="Test",
            delivery_postcode="BS1 1AA",
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
            subtotal=0, commission_amount=0, total=0, producer_payment=0,
        )
        OrderItem.objects.create(
            order=order, product=product,
            product_name=product.name,
            unit_price=Decimal("7.33"), quantity=3,
        )
        order.calculate_financials()

        # subtotal = 3 × £7.33 = £21.99
        self.assertEqual(order.subtotal, Decimal("21.99"))
        self.assertEqual(order.total, Decimal("21.99"))
        # commission = 5% of £21.99 = £1.0995 → rounded to £1.10
        self.assertEqual(order.commission_amount, Decimal("1.10"))
        self.assertEqual(order.producer_payment, Decimal("20.89"))
        # Verify split sums to total
        self.assertEqual(
            order.commission_amount + order.producer_payment,
            order.total,
        )

    # Checkout page shows subtotal and 5% commission labels.
    def test_commission_displayed_on_checkout(self):
        """TC-007: Order summary shows subtotal and 5% commission."""
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="10.00")
        self._add_to_cart(customer, product, quantity=2)

        self.client.login(email="customer@test.com", password="TestPass123!")
        response = self.client.get(reverse("orders:checkout"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subtotal")
        self.assertContains(response, "Network Commission")
        self.assertContains(response, "5%")

    # Confirmation page displays the commission breakdown.
    def test_commission_displayed_on_confirmation(self):
        """TC-007: Confirmation page shows commission breakdown."""
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="10.00")
        self._add_to_cart(customer, product, quantity=1)

        self.client.login(email="customer@test.com", password="TestPass123!")
        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "Test",
            "delivery_postcode": "BS1 1AA",
            "delivery_date": delivery.isoformat(),
        })
        order = Order.objects.get(customer=customer)
        response = self.client.get(
            reverse("orders:order_confirmation", args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subtotal")
        self.assertContains(response, "Network Commission")

    # Order detail page includes commission breakdown for both roles.
    def test_commission_displayed_on_order_detail(self):
        """TC-007/TC-025: Order detail shows commission breakdown."""
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="10.00")
        self._add_to_cart(customer, product, quantity=1)

        self.client.login(email="customer@test.com", password="TestPass123!")
        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "Test",
            "delivery_postcode": "BS1 1AA",
            "delivery_date": delivery.isoformat(),
        })
        order = Order.objects.get(customer=customer)
        response = self.client.get(
            reverse("orders:order_detail", args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subtotal")
        self.assertContains(response, "Network Commission")

    # Producer's order detail shows their 95% payment amount.
    def test_producer_sees_their_payment_on_detail(self):
        """TC-025: Producer view shows their 95% payment."""
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="20.00")
        self._add_to_cart(customer, product, quantity=5)

        self.client.login(email="customer@test.com", password="TestPass123!")
        delivery = self._valid_delivery_date()
        self.client.post(reverse("orders:checkout"), {
            "delivery_address": "Test",
            "delivery_postcode": "BS1 1AA",
            "delivery_date": delivery.isoformat(),
        })
        order = Order.objects.get(customer=customer)

        # Switch to producer
        self.client.logout()
        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_detail", args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your Payment (95%)")
        # 5 × £20 = £100, producer gets £95
        self.assertContains(response, "95.00")

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import ProducerProfile, CustomerProfile
from cart.models import Cart, CartItem
from marketplace.models import Category
from products.models import Farm, Product

from .models import Order, OrderItem, Payment, Notification, ProducerOrder

User = get_user_model()


class OrderTestHelperMixin:
    """Shared fixtures for order tests."""

    def _create_producer(self, email="producer@test.com", business_name="Test Farm Co",
                         lead_time_hours=48):
        user = User.objects.create_user(
            email=email, password="TestPass123!", role="PRODUCER",
        )
        ProducerProfile.objects.create(
            user=user,
            business_name=business_name,
            contact_name="Jane Farmer",
            address="123 Farm Lane",
            postcode="BS1 1AA",
            lead_time_hours=lead_time_hours,
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
        farm = Farm.objects.get_or_create(
            producer=producer,
            name=f"Farm of {producer.email}",
            defaults={"postcode": "BS3 3CC"},
        )[0]
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

    def _valid_delivery_date(self, hours=72):
        """Return a date that is safely beyond the given lead time."""
        return (timezone.now() + timedelta(hours=hours)).date()

    def _checkout_post_data(self, producers):
        """
        Build POST data dict for the checkout form.
        ``producers`` is a list of (producer_user, delivery_date) tuples.
        """
        data = {
            "delivery_address": "789 New Road",
            "delivery_postcode": "BS4 4DD",
        }
        for producer, date in producers:
            prefix = f"producer_{producer.id}"
            data[f"{prefix}-delivery_date"] = date.isoformat()
        return data


# ==========================================================================
# Model tests
# ==========================================================================

class OrderModelTests(OrderTestHelperMixin, TestCase):

    def test_order_number_generated_on_save(self):
        customer = self._create_customer()
        order = Order.objects.create(
            customer=customer,
            delivery_address="123 Street",
            delivery_postcode="BS1 1AA",
            subtotal=Decimal("10.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("0.50"),
            total=Decimal("10.00"),
            producer_payment=Decimal("9.50"),
        )
        self.assertTrue(order.order_number.startswith("ORD-"))
        self.assertEqual(len(order.order_number), 12)

    def test_order_status_default_pending(self):
        producer = self._create_producer()
        customer = self._create_customer()
        order = Order.objects.create(
            customer=customer,
            delivery_address="123 Street",
            delivery_postcode="BS1 1AA",
            subtotal=0, commission_rate=Decimal("0.05"),
            commission_amount=0, total=0, producer_payment=0,
        )
        self.assertEqual(order.status, Order.Status.PENDING)

    def test_calculate_financials_from_sub_orders(self):
        """Order.calculate_financials aggregates from ProducerOrder children."""
        producer1 = self._create_producer()
        producer2 = self._create_producer(email="p2@test.com", business_name="Farm 2")
        customer = self._create_customer()
        prod1 = self._create_product(producer1, price="10.00")
        prod2 = self._create_product(producer2, name="Tomatoes", price="5.00")

        order = Order.objects.create(
            customer=customer,
            delivery_address="Test", delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"),
            subtotal=0, commission_amount=0, total=0, producer_payment=0,
        )

        so1 = ProducerOrder.objects.create(
            order=order, producer=producer1,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        OrderItem.objects.create(
            order=order, producer_order=so1, product=prod1,
            product_name=prod1.name, unit_price=Decimal("10.00"), quantity=3,
        )
        so1.calculate_financials()
        so1.save()

        so2 = ProducerOrder.objects.create(
            order=order, producer=producer2,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        OrderItem.objects.create(
            order=order, producer_order=so2, product=prod2,
            product_name=prod2.name, unit_price=Decimal("5.00"), quantity=4,
        )
        so2.calculate_financials()
        so2.save()

        order.calculate_financials()

        # so1: 3×10=30, so2: 4×5=20 → total=50
        self.assertEqual(order.subtotal, Decimal("50.00"))
        self.assertEqual(order.total, Decimal("50.00"))
        # Commission: 1.50 + 1.00 = 2.50
        self.assertEqual(order.commission_amount, Decimal("2.50"))
        self.assertEqual(order.producer_payment, Decimal("47.50"))

    def test_is_multi_vendor_property(self):
        producer1 = self._create_producer()
        producer2 = self._create_producer(email="p2@test.com", business_name="Farm 2")
        customer = self._create_customer()

        order = Order.objects.create(
            customer=customer, delivery_address="x", delivery_postcode="x",
            commission_rate=Decimal("0.05"),
            subtotal=0, commission_amount=0, total=0, producer_payment=0,
        )
        ProducerOrder.objects.create(
            order=order, producer=producer1,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        self.assertFalse(order.is_multi_vendor)

        ProducerOrder.objects.create(
            order=order, producer=producer2,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        self.assertTrue(order.is_multi_vendor)


class ProducerOrderModelTests(OrderTestHelperMixin, TestCase):

    def test_calculate_financials(self):
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="10.00")

        order = Order.objects.create(
            customer=customer, delivery_address="x", delivery_postcode="x",
            commission_rate=Decimal("0.05"),
            subtotal=0, commission_amount=0, total=0, producer_payment=0,
        )
        so = ProducerOrder.objects.create(
            order=order, producer=producer,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        OrderItem.objects.create(
            order=order, producer_order=so, product=product,
            product_name=product.name, unit_price=Decimal("10.00"), quantity=3,
        )
        so.calculate_financials()

        self.assertEqual(so.subtotal, Decimal("30.00"))
        self.assertEqual(so.commission_amount, Decimal("1.50"))
        self.assertEqual(so.producer_payment, Decimal("28.50"))


class PaymentModelTests(OrderTestHelperMixin, TestCase):

    def test_transaction_id_generated(self):
        customer = self._create_customer()
        order = Order.objects.create(
            customer=customer,
            delivery_address="x", delivery_postcode="x",
            subtotal=10, commission_rate=Decimal("0.05"),
            commission_amount=Decimal("0.50"), total=Decimal("10.00"),
            producer_payment=Decimal("9.50"),
        )
        payment = Payment.objects.create(
            order=order, amount=Decimal("10.00"),
            status=Payment.Status.SUCCESS,
        )
        self.assertTrue(payment.transaction_id.startswith("TXN-"))


# ==========================================================================
# Form tests
# ==========================================================================

class CheckoutFormTests(OrderTestHelperMixin, TestCase):

    def test_checkout_form_has_address_fields_only(self):
        from .forms import CheckoutForm
        form = CheckoutForm()
        self.assertIn("delivery_address", form.fields)
        self.assertIn("delivery_postcode", form.fields)
        self.assertNotIn("delivery_date", form.fields)


class ProducerDeliveryFormTests(OrderTestHelperMixin, TestCase):

    def test_delivery_date_too_early_rejected(self):
        from .forms import ProducerDeliveryForm

        form = ProducerDeliveryForm(data={
            "producer_99-delivery_date": timezone.now().date().isoformat(),
        }, lead_time_hours=48, producer_id=99)
        self.assertFalse(form.is_valid())
        self.assertIn("delivery_date", form.errors)

    def test_valid_delivery_date_accepted(self):
        from .forms import ProducerDeliveryForm

        future = self._valid_delivery_date()
        form = ProducerDeliveryForm(data={
            "producer_99-delivery_date": future.isoformat(),
        }, lead_time_hours=48, producer_id=99)
        self.assertTrue(form.is_valid())

    def test_prefix_isolation(self):
        """Two producer forms with different prefixes don't clash."""
        from .forms import ProducerDeliveryForm

        future = self._valid_delivery_date()
        form_a = ProducerDeliveryForm(
            data={"producer_1-delivery_date": future.isoformat()},
            producer_id=1, lead_time_hours=48,
        )
        form_b = ProducerDeliveryForm(
            data={"producer_2-delivery_date": future.isoformat()},
            producer_id=2, lead_time_hours=48,
        )
        self.assertTrue(form_a.is_valid())
        self.assertTrue(form_b.is_valid())


# ==========================================================================
# View / integration tests — Single Producer (TC-007 regression)
# ==========================================================================

class SingleProducerCheckoutTests(OrderTestHelperMixin, TestCase):
    """TC-007: Single-producer checkout still works after refactor."""

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self.cart = self._add_to_cart(self.customer, self.product, quantity=2)
        self.client.login(email="customer@test.com", password="TestPass123!")

    def test_checkout_page_loads(self):
        response = self.client.get(reverse("orders:checkout"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Checkout")
        self.assertContains(response, "Organic Carrots")

    def test_checkout_redirects_empty_cart(self):
        CartItem.objects.all().delete()
        response = self.client.get(reverse("orders:checkout"))
        self.assertRedirects(response, reverse("cart:cart_detail"))

    def test_successful_checkout_creates_order_and_sub_order(self):
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        response = self.client.post(reverse("orders:checkout"), data)
        self.assertEqual(response.status_code, 302)

        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.delivery_address, "789 New Road")

        # ProducerOrder created
        self.assertEqual(order.sub_orders.count(), 1)
        so = order.sub_orders.first()
        self.assertEqual(so.producer, self.producer)
        self.assertEqual(so.delivery_date, delivery)
        self.assertEqual(so.items.count(), 1)

        # Financial checks
        expected_subtotal = Decimal("3.50") * 2  # £7.00
        expected_commission = Decimal("0.35")
        expected_producer_payment = Decimal("6.65")

        self.assertEqual(order.subtotal, expected_subtotal)
        self.assertEqual(order.total, expected_subtotal)
        self.assertEqual(order.commission_amount, expected_commission)
        self.assertEqual(order.producer_payment, expected_producer_payment)
        self.assertEqual(
            order.commission_amount + order.producer_payment,
            order.total,
        )

    def test_payment_recorded(self):
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)
        order = Order.objects.get(customer=self.customer)
        self.assertTrue(hasattr(order, "payment"))
        self.assertEqual(order.payment.status, Payment.Status.SUCCESS)
        self.assertEqual(order.payment.amount, order.total)

    def test_cart_marked_ordered(self):
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)
        self.cart.refresh_from_db()
        self.assertEqual(self.cart.status, "ordered")

    def test_stock_reduced_after_order(self):
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 98)

    def test_notifications_created(self):
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.producer,
                notification_type=Notification.Type.NEW_ORDER,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer,
                notification_type=Notification.Type.ORDER_CONFIRMED,
            ).exists()
        )

    def test_producer_cannot_access_checkout(self):
        self.client.logout()
        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(reverse("orders:checkout"))
        self.assertNotEqual(response.status_code, 200)


# ==========================================================================
# View / integration tests — Multi-Producer (TC-008)
# ==========================================================================

class MultiProducerCheckoutTests(OrderTestHelperMixin, TestCase):
    """TC-008: Multi-vendor checkout end-to-end."""

    def setUp(self):
        self.client = Client()
        self.producer1 = self._create_producer(
            email="farm1@test.com", business_name="Bristol Valley Farm",
            lead_time_hours=48,
        )
        self.producer2 = self._create_producer(
            email="farm2@test.com", business_name="Hillside Dairy",
            lead_time_hours=72,
        )
        self.customer = self._create_customer()

        self.prod_a = self._create_product(self.producer1, name="Organic Carrots", price="3.50")
        self.prod_b = self._create_product(self.producer1, name="Organic Potatoes", price="2.00")
        self.prod_c = self._create_product(self.producer2, name="Fresh Milk", price="1.80")
        self.prod_d = self._create_product(self.producer2, name="Cheddar Cheese", price="5.50")

        self.cart = self._add_to_cart(self.customer, self.prod_a, quantity=2)
        self._add_to_cart(self.customer, self.prod_b, quantity=3)
        self._add_to_cart(self.customer, self.prod_c, quantity=4)
        self._add_to_cart(self.customer, self.prod_d, quantity=1)

        self.client.login(email="customer@test.com", password="TestPass123!")

    def _post_data(self):
        """Valid multi-producer POST data."""
        date1 = self._valid_delivery_date(hours=72)   # for producer1 (48h lead)
        date2 = self._valid_delivery_date(hours=96)   # for producer2 (72h lead)
        return self._checkout_post_data([
            (self.producer1, date1),
            (self.producer2, date2),
        ]), date1, date2

    def test_checkout_page_shows_multi_vendor_sections(self):
        """TC-008 Step 4-6: checkout groups by producer."""
        response = self.client.get(reverse("orders:checkout"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bristol Valley Farm")
        self.assertContains(response, "Hillside Dairy")
        self.assertContains(response, "2 producers")

    def test_multi_vendor_checkout_creates_single_order(self):
        """TC-008: Multi-vendor order recorded as single customer order."""
        data, date1, date2 = self._post_data()
        response = self.client.post(reverse("orders:checkout"), data)
        self.assertEqual(response.status_code, 302)

        # Exactly one Order
        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 1)
        order = Order.objects.get(customer=self.customer)

        # Two ProducerOrder sub-orders
        self.assertEqual(order.sub_orders.count(), 2)

    def test_sub_orders_linked_to_correct_producers(self):
        """TC-008: Individual producer sub-orders are created and linked."""
        data, date1, date2 = self._post_data()
        self.client.post(reverse("orders:checkout"), data)
        order = Order.objects.get(customer=self.customer)

        so1 = order.sub_orders.get(producer=self.producer1)
        so2 = order.sub_orders.get(producer=self.producer2)

        self.assertEqual(so1.delivery_date, date1)
        self.assertEqual(so2.delivery_date, date2)
        self.assertEqual(so1.items.count(), 2)  # carrots + potatoes
        self.assertEqual(so2.items.count(), 2)  # milk + cheese

    def test_per_producer_financial_split(self):
        """TC-008 / TC-025: Payment distribution per producer."""
        data, _, _ = self._post_data()
        self.client.post(reverse("orders:checkout"), data)
        order = Order.objects.get(customer=self.customer)

        so1 = order.sub_orders.get(producer=self.producer1)
        so2 = order.sub_orders.get(producer=self.producer2)

        # Producer 1: 2×3.50 + 3×2.00 = 7.00 + 6.00 = 13.00
        self.assertEqual(so1.subtotal, Decimal("13.00"))
        self.assertEqual(so1.commission_amount, Decimal("0.65"))
        self.assertEqual(so1.producer_payment, Decimal("12.35"))

        # Producer 2: 4×1.80 + 1×5.50 = 7.20 + 5.50 = 12.70
        self.assertEqual(so2.subtotal, Decimal("12.70"))
        self.assertEqual(so2.commission_amount, Decimal("0.64"))  # 0.635 → 0.64
        self.assertEqual(so2.producer_payment, Decimal("12.06"))

        # Master order totals
        self.assertEqual(order.subtotal, Decimal("25.70"))
        self.assertEqual(order.total, Decimal("25.70"))
        self.assertEqual(order.commission_amount, Decimal("1.29"))
        self.assertEqual(order.producer_payment, Decimal("24.41"))

    def test_stock_reduced_for_all_producers(self):
        """TC-008: Stock quantities decrease across all producers."""
        data, _, _ = self._post_data()
        self.client.post(reverse("orders:checkout"), data)

        self.prod_a.refresh_from_db()
        self.prod_b.refresh_from_db()
        self.prod_c.refresh_from_db()
        self.prod_d.refresh_from_db()
        self.assertEqual(self.prod_a.stock_quantity, 98)  # 100-2
        self.assertEqual(self.prod_b.stock_quantity, 97)  # 100-3
        self.assertEqual(self.prod_c.stock_quantity, 96)  # 100-4
        self.assertEqual(self.prod_d.stock_quantity, 99)  # 100-1

    def test_each_producer_receives_notification(self):
        """TC-008: Each producer receives notification only for their portion."""
        data, _, _ = self._post_data()
        self.client.post(reverse("orders:checkout"), data)

        notif1 = Notification.objects.filter(
            recipient=self.producer1,
            notification_type=Notification.Type.NEW_ORDER,
        )
        notif2 = Notification.objects.filter(
            recipient=self.producer2,
            notification_type=Notification.Type.NEW_ORDER,
        )
        self.assertEqual(notif1.count(), 1)
        self.assertEqual(notif2.count(), 1)

        # Customer gets one confirmation
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer,
                notification_type=Notification.Type.ORDER_CONFIRMED,
            ).exists()
        )

    def test_different_delivery_dates_per_producer(self):
        """TC-008 Step 8: different delivery dates per producer."""
        data, date1, date2 = self._post_data()
        self.client.post(reverse("orders:checkout"), data)
        order = Order.objects.get(customer=self.customer)

        so1 = order.sub_orders.get(producer=self.producer1)
        so2 = order.sub_orders.get(producer=self.producer2)
        self.assertNotEqual(so1.delivery_date, so2.delivery_date)

    def test_lead_time_enforced_per_producer(self):
        """TC-008: Each producer's lead time is individually enforced."""
        # Producer2 has 72h lead time; give it a date that's only 48h out
        too_early = self._valid_delivery_date(hours=48)
        ok_date = self._valid_delivery_date(hours=72)

        data = self._checkout_post_data([
            (self.producer1, ok_date),
            (self.producer2, too_early),  # violates 72h lead time
        ])
        response = self.client.post(reverse("orders:checkout"), data)
        # Should re-render form (not redirect)
        self.assertEqual(response.status_code, 200)
        # No order created
        self.assertFalse(Order.objects.filter(customer=self.customer).exists())

    def test_single_payment_for_multi_vendor(self):
        """TC-008: Single payment covers the full multi-vendor order."""
        data, _, _ = self._post_data()
        self.client.post(reverse("orders:checkout"), data)
        order = Order.objects.get(customer=self.customer)

        self.assertTrue(hasattr(order, "payment"))
        self.assertEqual(order.payment.status, Payment.Status.SUCCESS)
        self.assertEqual(order.payment.amount, order.total)


# ==========================================================================
# View tests — Order Confirmation, List, Detail
# ==========================================================================

class OrderConfirmationViewTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self._add_to_cart(self.customer, self.product, quantity=1)
        self.client.login(email="customer@test.com", password="TestPass123!")

        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)
        self.order = Order.objects.get(customer=self.customer)

    def test_confirmation_page_loads(self):
        response = self.client.get(
            reverse("orders:order_confirmation", args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, "Order Confirmed")

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
        data = self._checkout_post_data([(self.producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)

    def test_customer_sees_own_orders(self):
        response = self.client.get(reverse("orders:order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ORD-")

    def test_producer_sees_incoming_sub_orders(self):
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
        data = self._checkout_post_data([(self.producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)
        self.order = Order.objects.get(customer=self.customer)

    def test_customer_can_view_detail(self):
        response = self.client.get(
            reverse("orders:order_detail", args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)

    def test_producer_can_view_detail(self):
        self.client.logout()
        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_detail", args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)

    def test_other_user_cannot_view_detail(self):
        other = self._create_customer(email="other@test.com")
        self.client.logout()
        self.client.login(email="other@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_detail", args=[self.order.order_number])
        )
        self.assertRedirects(response, reverse("orders:order_list"))

    def test_producer_only_sees_own_sub_order(self):
        """TC-008: Each producer can view only their relevant order items."""
        # Create multi-vendor order
        producer2 = self._create_producer(email="p2@test.com", business_name="Other Farm")
        prod2 = self._create_product(producer2, name="Milk", price="2.00")

        # Need a new cart
        Cart.objects.filter(user=self.customer, status="active").delete()
        self._add_to_cart(self.customer, self.product, quantity=1)
        self._add_to_cart(self.customer, prod2, quantity=1)

        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([
            (self.producer, delivery),
            (producer2, delivery),
        ])
        self.client.post(reverse("orders:checkout"), data)

        order = Order.objects.filter(customer=self.customer).order_by("-created_at").first()

        # Login as producer2
        self.client.logout()
        self.client.login(email="p2@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_detail", args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        # Should see Milk but NOT Organic Carrots
        self.assertContains(response, "Milk")
        self.assertNotContains(response, "Organic Carrots")


# ==========================================================================
# Commission calculation tests (TC-025 regression)
# ==========================================================================

class CommissionCalculationTests(OrderTestHelperMixin, TestCase):

    def test_tc025_single_producer_100(self):
        """TC-025 Step 8: order total £100 → commission £5, producer £95."""
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="50.00", stock=200)

        order = Order.objects.create(
            customer=customer, delivery_address="Test", delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"),
            subtotal=0, commission_amount=0, total=0, producer_payment=0,
        )
        so = ProducerOrder.objects.create(
            order=order, producer=producer,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        OrderItem.objects.create(
            order=order, producer_order=so, product=product,
            product_name=product.name, unit_price=Decimal("50.00"), quantity=2,
        )
        so.calculate_financials()
        so.save()
        order.calculate_financials()

        self.assertEqual(order.total, Decimal("100.00"))
        self.assertEqual(order.commission_amount, Decimal("5.00"))
        self.assertEqual(order.producer_payment, Decimal("95.00"))

    def test_tc025_multi_vendor_150(self):
        """TC-025 Step 9: multi-vendor £150 (£80+£70) split."""
        producer1 = self._create_producer()
        producer2 = self._create_producer(email="p2@test.com", business_name="Farm 2")
        customer = self._create_customer()
        prod1 = self._create_product(producer1, price="40.00", stock=200)
        prod2 = self._create_product(producer2, name="Cheese", price="35.00", stock=200)

        order = Order.objects.create(
            customer=customer, delivery_address="Test", delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"),
            subtotal=0, commission_amount=0, total=0, producer_payment=0,
        )
        so1 = ProducerOrder.objects.create(
            order=order, producer=producer1,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        OrderItem.objects.create(
            order=order, producer_order=so1, product=prod1,
            product_name=prod1.name, unit_price=Decimal("40.00"), quantity=2,
        )
        so1.calculate_financials()
        so1.save()

        so2 = ProducerOrder.objects.create(
            order=order, producer=producer2,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        OrderItem.objects.create(
            order=order, producer_order=so2, product=prod2,
            product_name=prod2.name, unit_price=Decimal("35.00"), quantity=2,
        )
        so2.calculate_financials()
        so2.save()

        order.calculate_financials()

        # Producer 1: 2×40=80, commission=4.00, payment=76.00
        self.assertEqual(so1.subtotal, Decimal("80.00"))
        self.assertEqual(so1.commission_amount, Decimal("4.00"))
        self.assertEqual(so1.producer_payment, Decimal("76.00"))

        # Producer 2: 2×35=70, commission=3.50, payment=66.50
        self.assertEqual(so2.subtotal, Decimal("70.00"))
        self.assertEqual(so2.commission_amount, Decimal("3.50"))
        self.assertEqual(so2.producer_payment, Decimal("66.50"))

        # Order total
        self.assertEqual(order.total, Decimal("150.00"))
        self.assertEqual(order.commission_amount, Decimal("7.50"))
        self.assertEqual(order.producer_payment, Decimal("142.50"))

    def test_commission_accurate_to_2_decimal_places(self):
        """TC-025: Commission calculations are accurate to 2 decimal places."""
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="7.33", stock=200)

        order = Order.objects.create(
            customer=customer, delivery_address="Test", delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"),
            subtotal=0, commission_amount=0, total=0, producer_payment=0,
        )
        so = ProducerOrder.objects.create(
            order=order, producer=producer,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
        )
        OrderItem.objects.create(
            order=order, producer_order=so, product=product,
            product_name=product.name, unit_price=Decimal("7.33"), quantity=3,
        )
        so.calculate_financials()
        so.save()
        order.calculate_financials()

        self.assertEqual(order.subtotal, Decimal("21.99"))
        self.assertEqual(order.commission_amount, Decimal("1.10"))
        self.assertEqual(order.producer_payment, Decimal("20.89"))
        self.assertEqual(
            order.commission_amount + order.producer_payment,
            order.total,
        )

    def test_commission_displayed_on_checkout(self):
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

    def test_commission_displayed_on_confirmation(self):
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="10.00")
        self._add_to_cart(customer, product, quantity=1)

        self.client.login(email="customer@test.com", password="TestPass123!")
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)

        order = Order.objects.get(customer=customer)
        response = self.client.get(
            reverse("orders:order_confirmation", args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subtotal")
        self.assertContains(response, "Network Commission")

    def test_commission_displayed_on_order_detail(self):
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="10.00")
        self._add_to_cart(customer, product, quantity=1)

        self.client.login(email="customer@test.com", password="TestPass123!")
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)

        order = Order.objects.get(customer=customer)
        response = self.client.get(
            reverse("orders:order_detail", args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Subtotal")
        self.assertContains(response, "Network Commission")

    def test_producer_sees_their_payment_on_detail(self):
        producer = self._create_producer()
        customer = self._create_customer()
        product = self._create_product(producer, price="20.00")
        self._add_to_cart(customer, product, quantity=5)

        self.client.login(email="customer@test.com", password="TestPass123!")
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)

        order = Order.objects.get(customer=customer)
        self.client.logout()
        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_detail", args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        # The producer percentage is now rendered dynamically from the
        # view context rather than being hardcoded in the template.
        self.assertContains(response, "Your Payment (95%)")
        self.assertContains(response, "95.00")


# ==========================================================================
# Additional form validation tests
# ==========================================================================

class CheckoutFormValidationTests(OrderTestHelperMixin, TestCase):
    """Verify that required field validation works on CheckoutForm."""

    def test_empty_address_rejected(self):
        """An empty delivery address must be rejected."""
        from .forms import CheckoutForm
        form = CheckoutForm(data={
            "delivery_address": "",
            "delivery_postcode": "BS1 1AA",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("delivery_address", form.errors)

    def test_empty_postcode_rejected(self):
        """An empty postcode must be rejected."""
        from .forms import CheckoutForm
        form = CheckoutForm(data={
            "delivery_address": "123 Test Street",
            "delivery_postcode": "",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("delivery_postcode", form.errors)


# ==========================================================================
# Stock sufficiency tests
# ==========================================================================

class InsufficientStockCheckoutTests(OrderTestHelperMixin, TestCase):
    """Verify that checkout rejects orders when stock is too low."""

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        # Only 1 unit in stock but we'll try to buy more
        self.product = self._create_product(self.producer, stock=1)
        self._add_to_cart(self.customer, self.product, quantity=5)
        self.client.login(email="customer@test.com", password="TestPass123!")

    @patch("orders.views._validate_cart_items")
    def test_order_rejected_when_stock_insufficient(self, _mock_validate):
        """Checkout must refuse to create an order when stock is too low.

        We mock _validate_cart_items to simulate a race condition where
        another customer bought stock between the page load and the
        form submission.  The atomic stock check should still catch it.
        """
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        response = self.client.post(reverse("orders:checkout"), data)

        # Should stay on the checkout page (200), not redirect (302)
        self.assertEqual(response.status_code, 200)
        # No order should have been created
        self.assertFalse(Order.objects.filter(customer=self.customer).exists())

    @patch("orders.views._validate_cart_items")
    def test_stock_warning_message_shown(self, _mock_validate):
        """The customer should see a helpful message about low stock."""
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        response = self.client.post(reverse("orders:checkout"), data)
        self.assertContains(response, "only has 1 in stock")


# ==========================================================================
# REST API tests
# ==========================================================================

class ProducerOrderAPITests(OrderTestHelperMixin, TestCase):
    """Tests for the ProducerOrderListAPIView endpoint."""

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self._add_to_cart(self.customer, self.product, quantity=2)

        # Place an order through the checkout flow
        self.client.login(email="customer@test.com", password="TestPass123!")
        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        self.client.post(reverse("orders:checkout"), data)
        self.client.logout()

    def test_producer_receives_sub_orders_via_api(self):
        """A producer should see their sub-orders in the API response."""
        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(reverse("orders:api_producer_orders"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertIn("order_number", data[0])
        self.assertIn("items", data[0])

    def test_customer_gets_403_from_api(self):
        """A customer account should receive 403, not an empty list."""
        self.client.login(email="customer@test.com", password="TestPass123!")
        response = self.client.get(reverse("orders:api_producer_orders"))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_gets_403(self):
        """An unauthenticated user must not access the API."""
        response = self.client.get(reverse("orders:api_producer_orders"))
        # DRF's SessionAuthentication returns 403 for anonymous users
        self.assertEqual(response.status_code, 403)

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import ProducerProfile, CustomerProfile
from cart.models import Cart, CartItem
from marketplace.models import Category
from products.models import Farm, Product, Review, ProductBatch, sync_product_stock_from_active_batches

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


class SingleProducerCheckoutTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self.cart = self._add_to_cart(self.customer, self.product, quantity=2)
        self.client.login(email="customer@test.com", password="TestPass123!")

    @patch("stripe.checkout.Session.create")
    def test_successful_checkout_creates_pending_order_and_redirects(self, mock_stripe):
        mock_stripe.return_value.url = "https://checkout.stripe.com/pay/test"

        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        response = self.client.post(reverse("orders:checkout"), data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.stripe.com/pay/test")

        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.sub_orders.count(), 1)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 98)

    @patch("stripe.checkout.Session.create")
    def test_checkout_decrements_batch_and_syncs_product_stock(self, mock_stripe):
        mock_stripe.return_value.url = "https://checkout.stripe.com/pay/test"

        batch = ProductBatch.objects.create(
            product=self.product,
            grade="B",
            stock_quantity=5,
            base_price=self.product.price,
            discount_percent=10,
        )
        self.cart.items.all().delete()
        CartItem.objects.create(cart=self.cart, product=self.product, batch=batch, quantity=2)

        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        response = self.client.post(reverse("orders:checkout"), data)

        self.assertEqual(response.status_code, 302)
        batch.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(batch.stock_quantity, 3)
        self.assertEqual(self.product.stock_quantity, 103)

    @patch("stripe.checkout.Session.create")
    @patch("orders.views._validate_cart_items")
    def test_checkout_insufficient_stock_suggests_other_producer(
        self, mock_validate_cart_items, mock_stripe,
    ):
        """Insufficient stock message includes alternatives from other producers."""
        mock_validate_cart_items.return_value = None
        mock_stripe.return_value.url = "https://checkout.stripe.com/pay/test"

        self.product.stock_quantity = 1
        self.product.save()

        alt_producer = self._create_producer(
            email="alt-producer@test.com",
            business_name="Riverbank Farm",
        )
        self._create_product(
            alt_producer,
            name=self.product.name,
            price="3.20",
            stock=10,
        )

        delivery = self._valid_delivery_date()
        data = self._checkout_post_data([(self.producer, delivery)])
        response = self.client.post(reverse("orders:checkout"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alternative options:')
        self.assertContains(response, 'Riverbank Farm')
        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 0)
        mock_stripe.assert_not_called()

    @patch("stripe.checkout.Session.retrieve")
    def test_payment_success_finalises_order(self, mock_retrieve):
        order = Order.objects.create(
            customer=self.customer, delivery_address="Test", delivery_postcode="BS1",
            commission_rate=Decimal("0.05"), subtotal=7, commission_amount=0.35,
            total=7, producer_payment=6.65, status=Order.Status.PENDING
        )
        so = ProducerOrder.objects.create(order=order, producer=self.producer,
                                          delivery_date=self._valid_delivery_date(), commission_rate=Decimal("0.05"))

        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.payment_intent = "pi_test_123"
        mock_retrieve.return_value = mock_session

        response = self.client.get(reverse("orders:payment_success"), {
            "session_id": "cs_test_123",
            "order_number": order.order_number
        })

        self.assertRedirects(response, reverse("orders:order_confirmation", args=[order.order_number]))

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertTrue(hasattr(order, "payment"))
        self.assertEqual(order.payment.transaction_id, "pi_test_123")

        self.assertTrue(Notification.objects.filter(recipient=self.producer).exists())
        self.cart.refresh_from_db()
        self.assertEqual(self.cart.status, "ordered")

    def test_payment_cancel_restores_stock(self):
        order = Order.objects.create(
            customer=self.customer, delivery_address="Test", delivery_postcode="BS1",
            commission_rate=Decimal("0.05"), subtotal=7, commission_amount=0, total=7, producer_payment=0,
            status=Order.Status.PENDING
        )
        OrderItem.objects.create(
            order=order, producer_order=ProducerOrder.objects.create(order=order, producer=self.producer,
                                                                     delivery_date=self._valid_delivery_date(),
                                                                     commission_rate=Decimal("0.05")),
            product=self.product, product_name=self.product.name, unit_price=3.50, quantity=2
        )

        response = self.client.get(reverse("orders:payment_cancel"), {"order_number": order.order_number})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("orders:checkout"), response.url)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 102)

    def test_payment_cancel_restores_batch_and_product_stock(self):
        batch = ProductBatch.objects.create(
            product=self.product,
            grade="C",
            stock_quantity=4,
            base_price=self.product.price,
            discount_percent=25,
        )
        ProductBatch.objects.filter(pk=batch.pk).update(stock_quantity=2)
        sync_product_stock_from_active_batches(self.product.id)

        order = Order.objects.create(
            customer=self.customer, delivery_address="Test", delivery_postcode="BS1",
            commission_rate=Decimal("0.05"), subtotal=7, commission_amount=0, total=7, producer_payment=0,
            status=Order.Status.PENDING
        )
        OrderItem.objects.create(
            order=order,
            producer_order=ProducerOrder.objects.create(
                order=order,
                producer=self.producer,
                delivery_date=self._valid_delivery_date(),
                commission_rate=Decimal("0.05"),
            ),
            product=self.product,
            batch=batch,
            product_name=f"{self.product.name} (Grade {batch.grade})",
            unit_price=Decimal("2.63"),
            quantity=2,
        )

        response = self.client.get(reverse("orders:payment_cancel"), {"order_number": order.order_number})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("orders:checkout"), response.url)

        batch.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(batch.stock_quantity, 4)
        self.assertEqual(self.product.stock_quantity, 104)


class MultiProducerCheckoutTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer1 = self._create_producer(email="farm1@test.com", business_name="Bristol Valley Farm")
        self.producer2 = self._create_producer(email="farm2@test.com", business_name="Hillside Dairy")
        self.customer = self._create_customer()

        self.prod_a = self._create_product(self.producer1, name="Organic Carrots", price="3.50")
        self.prod_c = self._create_product(self.producer2, name="Fresh Milk", price="1.80")

        self.cart = self._add_to_cart(self.customer, self.prod_a, quantity=2)
        self._add_to_cart(self.customer, self.prod_c, quantity=4)

        self.client.login(email="customer@test.com", password="TestPass123!")

    @patch("stripe.checkout.Session.create")
    def test_multi_vendor_checkout_creates_single_order(self, mock_stripe):
        mock_stripe.return_value.url = "https://checkout.stripe.com/pay/test"

        date1 = self._valid_delivery_date(hours=72)
        date2 = self._valid_delivery_date(hours=96)
        data = self._checkout_post_data([(self.producer1, date1), (self.producer2, date2)])

        response = self.client.post(reverse("orders:checkout"), data)
        self.assertEqual(response.status_code, 302)

        self.assertEqual(Order.objects.filter(customer=self.customer).count(), 1)
        order = Order.objects.get(customer=self.customer)
        self.assertEqual(order.sub_orders.count(), 2)

    @patch("stripe.checkout.Session.create")
    def test_per_producer_financial_split(self, mock_stripe):
        mock_stripe.return_value.url = "https://checkout.stripe.com/pay/test"

        date1 = self._valid_delivery_date(hours=72)
        date2 = self._valid_delivery_date(hours=96)
        data = self._checkout_post_data([(self.producer1, date1), (self.producer2, date2)])
        self.client.post(reverse("orders:checkout"), data)

        order = Order.objects.get(customer=self.customer)
        so1 = order.sub_orders.get(producer=self.producer1)
        so2 = order.sub_orders.get(producer=self.producer2)

        self.assertEqual(so1.subtotal, Decimal("7.00"))
        self.assertEqual(so1.producer_payment, Decimal("6.65"))

        self.assertEqual(so2.subtotal, Decimal("7.20"))
        self.assertEqual(so2.producer_payment, Decimal("6.84"))


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
# View tests — Order Confirmation, List, Detail
# ==========================================================================

class OrderConfirmationViewTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer)
        self.client.login(email="customer@test.com", password="TestPass123!")

        self.order = Order.objects.create(
            customer=self.customer, delivery_address="Test", delivery_postcode="BS1",
            commission_rate=Decimal("0.05"), subtotal=Decimal("3.50"), commission_amount=Decimal("0.17"),
            total=Decimal("3.50"), producer_payment=Decimal("3.33"), status=Order.Status.CONFIRMED
        )
        Payment.objects.create(
            order=self.order, amount=Decimal("3.50"), status=Payment.Status.SUCCESS,
            transaction_id="pi_test_123"
        )
        so = ProducerOrder.objects.create(
            order=self.order, producer=self.producer, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("3.50"), commission_amount=Decimal("0.17"),
            producer_payment=Decimal("3.33"), status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=self.order, producer_order=so, product=self.product,
            product_name=self.product.name, unit_price=Decimal("3.50"), quantity=1, line_total=Decimal("3.50")
        )

    def test_confirmation_page_loads(self):
        response = self.client.get(
            reverse("orders:order_confirmation", args=[self.order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, "Order Confirmed")

    def test_other_user_cannot_see_confirmation(self):
        self._create_customer(email="other@test.com")
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
        self.client.login(email="customer@test.com", password="TestPass123!")

        self.order = Order.objects.create(
            customer=self.customer, delivery_address="Test", delivery_postcode="BS1",
            commission_rate=Decimal("0.05"), subtotal=Decimal("3.50"), commission_amount=Decimal("0.17"),
            total=Decimal("3.50"), producer_payment=Decimal("3.33"), status=Order.Status.CONFIRMED
        )
        so = ProducerOrder.objects.create(
            order=self.order, producer=self.producer, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("3.50"), commission_amount=Decimal("0.17"),
            producer_payment=Decimal("3.33"), status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=self.order, producer_order=so, product=self.product,
            product_name=self.product.name, unit_price=Decimal("3.50"), quantity=1, line_total=Decimal("3.50")
        )

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
        self.client.login(email="customer@test.com", password="TestPass123!")

        self.order = Order.objects.create(
            customer=self.customer, delivery_address="Test", delivery_postcode="BS1",
            commission_rate=Decimal("0.05"), subtotal=Decimal("3.50"), commission_amount=Decimal("0.17"),
            total=Decimal("3.50"), producer_payment=Decimal("3.33"), status=Order.Status.CONFIRMED
        )
        so = ProducerOrder.objects.create(
            order=self.order, producer=self.producer, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("3.50"), commission_amount=Decimal("0.17"),
            producer_payment=Decimal("3.33"), status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=self.order, producer_order=so, product=self.product,
            product_name=self.product.name, unit_price=Decimal("3.50"), quantity=1, line_total=Decimal("3.50")
        )

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
        self._create_customer(email="other@test.com")
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

        order = Order.objects.create(
            customer=self.customer, delivery_address="Test", delivery_postcode="BS1",
            commission_rate=Decimal("0.05"), subtotal=Decimal("5.50"), commission_amount=Decimal("0.28"),
            total=Decimal("5.50"), producer_payment=Decimal("5.22"), status=Order.Status.CONFIRMED
        )
        so1 = ProducerOrder.objects.create(
            order=order, producer=self.producer, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("3.50"), commission_amount=Decimal("0.17"),
            producer_payment=Decimal("3.33"), status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=order, producer_order=so1, product=self.product,
            product_name=self.product.name, unit_price=Decimal("3.50"), quantity=1, line_total=Decimal("3.50")
        )

        so2 = ProducerOrder.objects.create(
            order=order, producer=producer2, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("2.00"), commission_amount=Decimal("0.10"),
            producer_payment=Decimal("1.90"), status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=order, producer_order=so2, product=prod2,
            product_name=prod2.name, unit_price=Decimal("2.00"), quantity=1, line_total=Decimal("2.00")
        )


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


class ReviewWorkflowTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer, name="Organic Tomatoes", price="4.50")

    def _build_order(self, *, status=Order.Status.DELIVERED):
        order = Order.objects.create(
            customer=self.customer,
            delivery_address="Test Delivery Address",
            delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"),
            subtotal=Decimal("4.50"),
            commission_amount=Decimal("0.23"),
            total=Decimal("4.50"),
            producer_payment=Decimal("4.27"),
            status=status,
        )
        so = ProducerOrder.objects.create(
            order=order,
            producer=self.producer,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
            status=ProducerOrder.Status.DELIVERED if status == Order.Status.DELIVERED else ProducerOrder.Status.CONFIRMED,
        )
        item = OrderItem.objects.create(
            order=order,
            producer_order=so,
            product=self.product,
            product_name=self.product.name,
            unit_price=self.product.price,
            quantity=1,
            line_total=self.product.price,
        )
        return order, item

    def test_customer_can_submit_review_for_delivered_order_item(self):
        order, item = self._build_order(status=Order.Status.DELIVERED)
        self.client.login(email="customer@test.com", password="TestPass123!")

        response = self.client.post(
            reverse("orders:create_review", args=[order.order_number, item.id]),
            {
                "rating": 5,
                "title": "Excellent quality and flavour",
                "body": "These tomatoes were incredibly fresh and flavourful.",
                "is_anonymous": "on",
            },
        )

        self.assertRedirects(response, reverse("marketplace:product_detail", args=[self.product.id]))
        review = Review.objects.get(customer=self.customer, product=self.product, is_deleted=False)
        self.assertEqual(review.rating, 5)
        self.assertTrue(review.is_anonymous)

    def test_review_blocked_when_order_not_delivered(self):
        order, item = self._build_order(status=Order.Status.CONFIRMED)
        self.client.login(email="customer@test.com", password="TestPass123!")

        response = self.client.post(
            reverse("orders:create_review", args=[order.order_number, item.id]),
            {
                "rating": 5,
                "title": "Should Fail",
                "body": "This should not be accepted before delivery.",
            },
        )

        self.assertRedirects(response, reverse("orders:order_detail", args=[order.order_number]))
        self.assertFalse(
            Review.objects.filter(customer=self.customer, product=self.product, is_deleted=False).exists()
        )

    def test_duplicate_review_is_blocked(self):
        order, item = self._build_order(status=Order.Status.DELIVERED)
        Review.objects.create(
            customer=self.customer,
            product=self.product,
            order=order,
            rating=4,
            title="Great",
            body="Already reviewed once.",
        )
        self.client.login(email="customer@test.com", password="TestPass123!")

        response = self.client.post(
            reverse("orders:create_review", args=[order.order_number, item.id]),
            {
                "rating": 5,
                "title": "Duplicate",
                "body": "Trying to post a second review.",
            },
        )

        self.assertRedirects(response, reverse("marketplace:product_detail", args=[self.product.id]))
        self.assertEqual(
            Review.objects.filter(customer=self.customer, product=self.product, is_deleted=False).count(),
            1,
        )

    def test_product_detail_shows_review_and_average_rating(self):
        order, _item = self._build_order(status=Order.Status.DELIVERED)
        Review.objects.create(
            customer=self.customer,
            product=self.product,
            order=order,
            rating=5,
            title="Excellent quality and flavour",
            body="These tomatoes were incredibly fresh and flavourful.",
        )

        response = self.client.get(reverse("marketplace:product_detail", args=[self.product.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customer Reviews")
        self.assertContains(response, "Excellent quality and flavour")
        self.assertContains(response, "5.0 / 5")
        self.assertContains(response, "Verified Purchase")

    def test_product_detail_shows_previously_purchased_tag_and_add_review_cta(self):
        order, item = self._build_order(status=Order.Status.DELIVERED)
        self.client.login(email="customer@test.com", password="TestPass123!")

        response = self.client.get(reverse("marketplace:product_detail", args=[self.product.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Previously Purchased")
        self.assertContains(response, "Add Review")
        self.assertContains(response, reverse("orders:create_review", args=[order.order_number, item.id]))

    def test_product_detail_shows_not_delivered_review_block_message(self):
        self._build_order(status=Order.Status.CONFIRMED)
        self.client.login(email="customer@test.com", password="TestPass123!")

        response = self.client.get(reverse("marketplace:product_detail", args=[self.product.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Previously Purchased")
        self.assertContains(response, "Add Review")
        self.assertContains(response, "You can review this product once the order is marked as delivered.")

    def test_customer_can_delete_own_review_from_product_page(self):
        order, _item = self._build_order(status=Order.Status.DELIVERED)
        review = Review.objects.create(
            customer=self.customer,
            product=self.product,
            order=order,
            rating=5,
            title="Delete me",
            body="Customer requested removal.",
        )
        self.client.login(email="customer@test.com", password="TestPass123!")

        response = self.client.post(
            reverse("marketplace:delete_own_review", args=[self.product.id, review.id])
        )

        self.assertRedirects(response, reverse("marketplace:product_detail", args=[self.product.id]))
        deleted_review = Review.all_objects.get(pk=review.id)
        self.assertTrue(deleted_review.is_deleted)

    def test_customer_cannot_delete_other_customers_review(self):
        other_customer = self._create_customer(email="other.customer@test.com")
        review = Review.objects.create(
            customer=other_customer,
            product=self.product,
            rating=4,
            title="Not yours",
            body="Another user review.",
        )
        self.client.login(email="customer@test.com", password="TestPass123!")

        response = self.client.post(
            reverse("marketplace:delete_own_review", args=[self.product.id, review.id])
        )

        self.assertEqual(response.status_code, 404)
        review.refresh_from_db()
        self.assertFalse(review.is_deleted)

    def test_product_owner_sees_review_response_form_on_product_detail(self):
        order, _item = self._build_order(status=Order.Status.DELIVERED)
        review = Review.objects.create(
            customer=self.customer,
            product=self.product,
            order=order,
            rating=5,
            title="Great produce",
            body="Very fresh.",
        )
        self.client.login(email="producer@test.com", password="TestPass123!")

        response = self.client.get(reverse("marketplace:product_detail", args=[self.product.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add Response")
        self.assertContains(response, reverse("producer_review_respond", args=[review.id]))

    def test_producer_can_respond_from_product_detail_and_return_there(self):
        review = Review.objects.create(
            customer=self.customer,
            product=self.product,
            rating=5,
            title="Great produce",
            body="Very fresh.",
        )
        self.client.login(email="producer@test.com", password="TestPass123!")

        product_url = reverse("marketplace:product_detail", args=[self.product.id])
        response = self.client.post(
            reverse("producer_review_respond", args=[review.id]),
            {
                "producer_response": "Thanks for your feedback.",
                "next": product_url,
            },
        )

        self.assertRedirects(response, product_url)
        review.refresh_from_db()
        self.assertEqual(review.producer_response, "Thanks for your feedback.")
        self.assertIsNotNone(review.producer_responded_at)


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

        order = Order.objects.create(
            customer=customer, delivery_address="Test", delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"), subtotal=Decimal("10.00"),
            commission_amount=Decimal("0.50"), total=Decimal("10.00"),
            producer_payment=Decimal("9.50"), status=Order.Status.CONFIRMED
        )
        so = ProducerOrder.objects.create(
            order=order, producer=producer, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("10.00"),
            commission_amount=Decimal("0.50"), producer_payment=Decimal("9.50"),
            status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=order, producer_order=so, product=product,
            product_name=product.name, unit_price=Decimal("10.00"), quantity=1, line_total=Decimal("10.00")
        )

        self.client.login(email="customer@test.com", password="TestPass123!")
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

        order = Order.objects.create(
            customer=customer, delivery_address="Test", delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"), subtotal=Decimal("10.00"),
            commission_amount=Decimal("0.50"), total=Decimal("10.00"),
            producer_payment=Decimal("9.50"), status=Order.Status.CONFIRMED
        )
        so = ProducerOrder.objects.create(
            order=order, producer=producer, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("10.00"),
            commission_amount=Decimal("0.50"), producer_payment=Decimal("9.50"),
            status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=order, producer_order=so, product=product,
            product_name=product.name, unit_price=Decimal("10.00"), quantity=1, line_total=Decimal("10.00")
        )

        self.client.login(email="customer@test.com", password="TestPass123!")
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

        order = Order.objects.create(
            customer=customer, delivery_address="Test", delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"), subtotal=Decimal("100.00"),
            commission_amount=Decimal("5.00"), total=Decimal("100.00"),
            producer_payment=Decimal("95.00"), status=Order.Status.CONFIRMED
        )
        so = ProducerOrder.objects.create(
            order=order, producer=producer, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("100.00"),
            commission_amount=Decimal("5.00"), producer_payment=Decimal("95.00"),
            status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=order, producer_order=so, product=product,
            product_name=product.name, unit_price=Decimal("20.00"), quantity=5, line_total=Decimal("100.00")
        )

        self.client.login(email="producer@test.com", password="TestPass123!")
        response = self.client.get(
            reverse("orders:order_detail", args=[order.order_number])
        )
        self.assertEqual(response.status_code, 200)
        # The producer percentage is now rendered dynamically from the
        # view context rather than being hardcoded in the template.
        self.assertContains(response, "Your Payment (95%)")
        self.assertContains(response, "95.00")


class CustomerOrderHistoryFeatureTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer()
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer, name="Heritage Potatoes", price="4.00", stock=10)

        self.order = Order.objects.create(
            customer=self.customer,
            delivery_address="123 Test Lane",
            delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"),
            subtotal=Decimal("12.00"),
            commission_amount=Decimal("0.60"),
            total=Decimal("12.00"),
            producer_payment=Decimal("11.40"),
            status=Order.Status.DELIVERED,
        )
        self.sub_order = ProducerOrder.objects.create(
            order=self.order,
            producer=self.producer,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
            subtotal=Decimal("12.00"),
            commission_amount=Decimal("0.60"),
            producer_payment=Decimal("11.40"),
            status=ProducerOrder.Status.DELIVERED,
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            producer_order=self.sub_order,
            product=self.product,
            product_name=self.product.name,
            unit_price=Decimal("4.00"),
            quantity=3,
            line_total=Decimal("12.00"),
        )
        self.payment = Payment.objects.create(
            order=self.order,
            amount=Decimal("12.00"),
            status=Payment.Status.SUCCESS,
            transaction_id="pi_1234567890ABCDEF",
            payment_method="stripe_card",
        )

        self.client.login(email="customer@test.com", password="TestPass123!")

    def test_order_history_includes_soft_deleted_order(self):
        self.order.delete()
        response = self.client.get(reverse("orders:order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.order.order_number)

    def test_order_detail_masks_payment_identifier(self):
        response = self.client.get(reverse("orders:order_detail", args=[self.order.order_number]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CDEF")
        self.assertNotContains(response, self.payment.transaction_id)

    def test_customer_can_download_receipt_for_past_order(self):
        response = self.client.get(reverse("orders:download_receipt", args=[self.order.order_number]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(self.order.order_number, response["Content-Disposition"])
        self.assertIn(".pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_reorder_handles_unavailable_products_gracefully(self):
        self.product.is_available = False
        self.product.save()

        response = self.client.post(
            reverse("orders:reorder_order", args=[self.order.order_number]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Some items could not be reordered")
        cart, _ = Cart.objects.get_or_create(user=self.customer, status="active")
        self.assertFalse(cart.items.exists())

    def test_reorder_unavailable_product_suggests_other_producer(self):
        self.product.is_available = False
        self.product.save()

        alt_producer = self._create_producer(
            email="alt-unavailable@test.com",
            business_name="Sunny Acres",
        )
        self._create_product(
            alt_producer,
            name=self.product.name,
            price="4.30",
            stock=8,
        )

        response = self.client.post(
            reverse("orders:reorder_order", args=[self.order.order_number]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Suggested Alternatives")
        self.assertContains(response, "Sunny Acres")

    def test_reorder_out_of_stock_suggests_other_producer(self):
        self.product.stock_quantity = 0
        self.product.save()

        alt_producer = self._create_producer(
            email="alt-reorder@test.com",
            business_name="Green Meadow Farm",
        )
        self._create_product(
            alt_producer,
            name=self.product.name,
            price="4.30",
            stock=8,
        )

        response = self.client.post(
            reverse("orders:reorder_order", args=[self.order.order_number]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Suggested Alternatives")
        self.assertContains(response, "Green Meadow Farm")

    def test_reorder_partially_adds_items_when_stock_reduced(self):
        self.product.stock_quantity = 1
        self.product.save()

        response = self.client.post(
            reverse("orders:reorder_order", args=[self.order.order_number]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "partially added")

        cart = Cart.objects.get(user=self.customer, status="active")
        cart_item = cart.items.get(product=self.product)
        self.assertEqual(cart_item.quantity, 1)

    def test_reorder_notifies_when_price_changed(self):
        self.product.price = Decimal("5.25")
        self.product.save()

        response = self.client.post(
            reverse("orders:reorder_order", args=[self.order.order_number]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Price updates applied during reorder")
        self.assertContains(response, "Heritage Potatoes: was £4.00, now £5.25")


class ProducerOrderStatusLifecycleTests(OrderTestHelperMixin, TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = self._create_producer(email="producer-a@test.com", business_name="Alpha Farm")
        self.other_producer = self._create_producer(email="producer-b@test.com", business_name="Beta Farm")
        self.customer = self._create_customer()
        self.product = self._create_product(self.producer, price="6.00")

        self.order = Order.objects.create(
            customer=self.customer,
            delivery_address="123 Test Lane",
            delivery_postcode="BS1 1AA",
            commission_rate=Decimal("0.05"),
            subtotal=Decimal("12.00"),
            commission_amount=Decimal("0.60"),
            total=Decimal("12.00"),
            producer_payment=Decimal("11.40"),
            status=Order.Status.CONFIRMED,
        )
        self.sub_order = ProducerOrder.objects.create(
            order=self.order,
            producer=self.producer,
            delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"),
            subtotal=Decimal("12.00"),
            commission_amount=Decimal("0.60"),
            producer_payment=Decimal("11.40"),
            status=ProducerOrder.Status.CONFIRMED,
        )
        OrderItem.objects.create(
            order=self.order,
            producer_order=self.sub_order,
            product=self.product,
            product_name=self.product.name,
            unit_price=Decimal("6.00"),
            quantity=2,
            line_total=Decimal("12.00"),
        )

    def test_producer_can_advance_status_through_lifecycle(self):
        self.client.login(email="producer-a@test.com", password="TestPass123!")

        # Confirmed -> Ready
        response = self.client.post(
            reverse("orders:producer_update_sub_order_status", args=[self.sub_order.id]),
            {"target_status": ProducerOrder.Status.DISPATCHED},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.sub_order.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.sub_order.status, ProducerOrder.Status.DISPATCHED)
        self.assertEqual(self.order.status, Order.Status.DISPATCHED)

        # Ready -> Delivered
        response = self.client.post(
            reverse("orders:producer_update_sub_order_status", args=[self.sub_order.id]),
            {"target_status": ProducerOrder.Status.DELIVERED},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.sub_order.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.sub_order.status, ProducerOrder.Status.DELIVERED)
        self.assertEqual(self.order.status, Order.Status.DELIVERED)

    def test_status_cannot_skip_required_stage(self):
        self.client.login(email="producer-a@test.com", password="TestPass123!")
        response = self.client.post(
            reverse("orders:producer_update_sub_order_status", args=[self.sub_order.id]),
            {"target_status": ProducerOrder.Status.DELIVERED},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.sub_order.refresh_from_db()
        self.assertEqual(self.sub_order.status, ProducerOrder.Status.CONFIRMED)
        self.assertContains(response, "Invalid status transition")

    def test_only_relevant_producer_can_update_sub_order(self):
        self.client.login(email="producer-b@test.com", password="TestPass123!")
        response = self.client.post(
            reverse("orders:producer_update_sub_order_status", args=[self.sub_order.id]),
            {"target_status": ProducerOrder.Status.DISPATCHED},
        )
        self.assertEqual(response.status_code, 404)

    def test_customer_gets_notification_on_status_update(self):
        self.client.login(email="producer-a@test.com", password="TestPass123!")
        self.client.post(
            reverse("orders:producer_update_sub_order_status", args=[self.sub_order.id]),
            {"target_status": ProducerOrder.Status.DISPATCHED},
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.customer,
                order=self.order,
                notification_type=Notification.Type.ORDER_STATUS_UPDATE,
            ).exists()
        )

    def test_audit_trail_records_status_changes(self):
        initial_sub_history = self.sub_order.history.count()
        initial_order_history = self.order.history.count()

        self.client.login(email="producer-a@test.com", password="TestPass123!")
        self.client.post(
            reverse("orders:producer_update_sub_order_status", args=[self.sub_order.id]),
            {"target_status": ProducerOrder.Status.DISPATCHED},
        )

        self.sub_order.refresh_from_db()
        self.order.refresh_from_db()
        self.assertGreater(self.sub_order.history.count(), initial_sub_history)
        self.assertGreater(self.order.history.count(), initial_order_history)

    def test_optional_status_note_reaches_notification_and_audit(self):
        self.client.login(email="producer-a@test.com", password="TestPass123!")
        note = "Products will be prepared by delivery date"

        self.client.post(
            reverse("orders:producer_update_sub_order_status", args=[self.sub_order.id]),
            {
                "target_status": ProducerOrder.Status.DISPATCHED,
                "status_note": note,
            },
        )

        notif = Notification.objects.filter(
            recipient=self.customer,
            order=self.order,
            notification_type=Notification.Type.ORDER_STATUS_UPDATE,
        ).latest("created_at")
        self.assertIn(note, notif.message)

        latest_history = self.sub_order.history.latest("history_date")
        self.assertIn("Note:", latest_history.history_change_reason or "")
        self.assertIn(note, latest_history.history_change_reason or "")


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

        self.order = Order.objects.create(
            customer=self.customer, delivery_address="Test", delivery_postcode="BS1",
            commission_rate=Decimal("0.05"), subtotal=Decimal("7.00"), commission_amount=Decimal("0.35"),
            total=Decimal("7.00"), producer_payment=Decimal("6.65"), status=Order.Status.CONFIRMED
        )
        so = ProducerOrder.objects.create(
            order=self.order, producer=self.producer, delivery_date=self._valid_delivery_date(),
            commission_rate=Decimal("0.05"), subtotal=Decimal("7.00"), commission_amount=Decimal("0.35"),
            producer_payment=Decimal("6.65"), status=ProducerOrder.Status.CONFIRMED
        )
        OrderItem.objects.create(
            order=self.order, producer_order=so, product=self.product,
            product_name=self.product.name, unit_price=Decimal("3.50"), quantity=2, line_total=Decimal("7.00")
        )

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

class TC025FinancialReportingViewTests(TestCase):
    """
    Validates Phase 5 of the TC-025 Implementation Plan:
    Admin Commissions Custom Views using Django Test Client.
    """

    def setUp(self):
        self.client = Client()
        
        # Target URLs
        self.list_url = reverse("orders:admin_commissions")
        self.csv_url = reverse("orders:admin_commissions_csv")
        self.accounting_csv_url = reverse("orders:admin_commissions_accounting_csv")
        
        # Test users
        self.admin = User.objects.create_superuser("admin@test.com", "pass")
        self.producer1 = User.objects.create_user("p1@test.com", "pass", role="PRODUCER")
        self.producer2 = User.objects.create_user("p2@test.com", "pass", role="PRODUCER")
        self.customer = User.objects.create_user("c@test.com", "pass", role="CUSTOMER")
        
        d_date = timezone.localdate() + timedelta(days=2)
        
        # Mock Multi-vendor Order (Order A) - £150 total
        self.order_a = Order.objects.create(
            customer=self.customer,
            status=Order.Status.DELIVERED,
            subtotal=Decimal("150.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("7.50"),
            total=Decimal("150.00"),
            producer_payment=Decimal("142.50")
        )
        self.payment_a = Payment.objects.create(
            order=self.order_a,
            status=Payment.Status.SUCCESS,
            transaction_id="TXN-A",
            amount=Decimal("150.00")
        )
        self.sub_a1 = ProducerOrder.objects.create(
            order=self.order_a,
            producer=self.producer1,
            subtotal=Decimal("80.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("4.00"),
            producer_payment=Decimal("76.00"),
            delivery_date=d_date
        )
        self.sub_a2 = ProducerOrder.objects.create(
            order=self.order_a,
            producer=self.producer2,
            subtotal=Decimal("70.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("3.50"),
            producer_payment=Decimal("66.50"),
            delivery_date=d_date
        )

        # Mock Single-vendor Order (Order B) - £100 total
        self.order_b = Order.objects.create(
            customer=self.customer,
            status=Order.Status.DELIVERED,
            subtotal=Decimal("100.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("5.00"),
            total=Decimal("100.00"),
            producer_payment=Decimal("95.00")
        )
        self.payment_b = Payment.objects.create(
            order=self.order_b,
            status=Payment.Status.SUCCESS,
            transaction_id="TXN-B",
            amount=Decimal("100.00")
        )
        self.sub_b1 = ProducerOrder.objects.create(
            order=self.order_b,
            producer=self.producer1,
            subtotal=Decimal("100.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("5.00"),
            producer_payment=Decimal("95.00"),
            delivery_date=d_date
        )

        self.detail_a_url = reverse("orders:admin_commissions_detail", args=[self.order_a.order_number])

    def test_security_access_control(self):
        """Customers and Producers get 403 on all endpoints (Step 268)."""
        endpoints = [self.list_url, self.csv_url, self.accounting_csv_url, self.detail_a_url]
        
        # Test Customer
        self.client.force_login(self.customer)
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)
            
        # Test Producer
        self.client.force_login(self.producer1)
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

        # Test Admin
        self.client.force_login(self.admin)
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"Failed on {url}")

    def test_reporting_value_accuracy_and_display(self):
        """Value accuracy for Step 274 and 275."""
        self.client.force_login(self.admin)
        
        # Test Detail View for Order A (£150 multi-vendor split)
        response = self.client.get(self.detail_a_url)
        content = response.content.decode("utf-8", errors="ignore").replace("Â", "")
        self.assertIn("5% of £150.00 =", content)
        self.assertIn("£7.50", content)
        self.assertIn("95% of £80.00 =", content)
        self.assertIn("£76.00", content)
        self.assertIn("95% of £70.00 =", content)
        self.assertIn("£66.50", content)

        # Test Detail View for Order B (£100 single-vendor split)
        detail_b_url = reverse("orders:admin_commissions_detail", args=[self.order_b.order_number])
        response_b = self.client.get(detail_b_url)
        content_b = response_b.content.decode("utf-8", errors="ignore").replace("Â", "")
        self.assertIn("5% of £100.00 =", content_b)
        self.assertIn("£5.00", content_b)
        self.assertIn("95% of £100.00 =", content_b)
        self.assertIn("£95.00", content_b)

    def test_filter_logic_last_14_days(self):
        """Verify date filtering properly excludes old records (Step 269/270)."""
        self.client.force_login(self.admin)
        
        # Alter order_b to be 20 days old
        old_date = timezone.now() - timedelta(days=20)
        Order.objects.filter(id=self.order_b.id).update(created_at=old_date)
        
        response = self.client.get(self.list_url, {"period": "last_14_days"})
        # order_b should be excluded from page_obj
        orders = response.context["page_obj"].object_list
        self.assertIn(self.order_a, orders)
        self.assertNotIn(self.order_b, orders)
        
        # Overall metrics should only include £150 order
        self.assertEqual(response.context["metrics"]["total_order_value"], Decimal("150.00"))
        
    def test_csv_file_integrity(self):
        """Re-verify CSV filters and mapping exactly (Step 276)."""
        self.client.force_login(self.admin)
        
        # Alter order_b to be old
        old_date = timezone.now() - timedelta(days=20)
        Order.objects.filter(id=self.order_b.id).update(created_at=old_date)
        
        # Test Export with last_14_days filter
        response = self.client.get(self.csv_url, {"period": "last_14_days"})
        self.assertEqual(response.status_code, 200)
        
        # Only order A sub-orders should be present 
        content = response.content.decode("utf-8").strip().splitlines()
        self.assertEqual(content[0], "Network Commission Report")
        self.assertTrue(any("Applied Filters,period=last_14_days" in row for row in content))
        self.assertTrue(any(row.startswith("Order Number,Order Date") for row in content))
        self.assertTrue(any(self.order_a.order_number in row for row in content))
        self.assertFalse(any(self.order_b.order_number in row for row in content))

    def test_producer_filter_applies_to_metrics_and_csv_rows(self):
        """Producer filter scopes metrics and CSV rows to that producer split."""
        self.client.force_login(self.admin)

        response = self.client.get(self.list_url, {"producer_id": self.producer1.id})
        self.assertEqual(response.status_code, 200)
        metrics = response.context["metrics"]
        self.assertEqual(metrics["total_order_value"], Decimal("180.00"))
        self.assertEqual(metrics["total_commission"], Decimal("9.00"))
        self.assertEqual(metrics["total_producer_payout"], Decimal("171.00"))
        self.assertEqual(metrics["order_count"], 2)
        self.assertNotContains(response, "p2@test.com:</span>")

        csv_response = self.client.get(self.csv_url, {"producer_id": self.producer1.id})
        csv_content = csv_response.content.decode("utf-8").splitlines()
        self.assertTrue(any("Applied Filters,producer_id=" in row for row in csv_content))
        self.assertTrue(any(",p1@test.com," in row for row in csv_content if row.startswith("ORD-")))
        self.assertFalse(any(",p2@test.com," in row for row in csv_content if row.startswith("ORD-")))

    def test_accounting_csv_is_header_first_and_paid_only_by_default(self):
        """Accounting CSV is import-friendly and excludes pending payments by default."""
        self.client.force_login(self.admin)

        # Make order_b pending to verify default exclusion behavior.
        self.payment_b.status = Payment.Status.PENDING
        self.payment_b.save(update_fields=["status"])

        response = self.client.get(self.accounting_csv_url)
        self.assertEqual(response.status_code, 200)
        lines = response.content.decode("utf-8").strip().splitlines()

        expected_header = (
            "Order Number,Order Date,Order Status,Payment Status,Transaction ID,"
            "Currency,Producer Order ID,Producer Email,Producer Name,Producer Subtotal,"
            "Producer Commission,Producer Payout"
        )
        self.assertEqual(lines[0], expected_header)
        self.assertFalse(any("Network Commission Report" in row for row in lines))
        self.assertFalse(any("Generated At" in row for row in lines))

        data_rows = [row for row in lines[1:] if row.startswith("ORD-")]
        self.assertTrue(any(self.order_a.order_number in row for row in data_rows))
        self.assertFalse(any(self.order_b.order_number in row for row in data_rows))
        self.assertTrue(all(",GBP," in row for row in data_rows))
        self.assertTrue(all(",TXN-A," in row for row in data_rows))

        response_with_pending = self.client.get(self.accounting_csv_url, {"include_pending": "1"})
        lines_with_pending = response_with_pending.content.decode("utf-8").strip().splitlines()
        data_rows_with_pending = [row for row in lines_with_pending[1:] if row.startswith("ORD-")]
        self.assertTrue(any(self.order_b.order_number in row for row in data_rows_with_pending))

    def test_anonymise_data_toggle(self):
        """Verify that 'anonymise' toggle redacts sensitive data from exports."""
        self.client.force_login(self.admin)

        # Test normal CSV
        csv_response = self.client.get(self.csv_url, {"anonymise": "1"})
        csv_content = csv_response.content.decode("utf-8")
        self.assertIn("REDACTED PRODUCER", csv_content)
        self.assertIn(",REDACTED,", csv_content)
        self.assertNotIn("p1@test.com", csv_content)

        # Test accounting CSV
        acc_response = self.client.get(self.accounting_csv_url, {"anonymise": "1"})
        acc_content = acc_response.content.decode("utf-8")
        self.assertIn("REDACTED PRODUCER", acc_content)
        self.assertIn(",REDACTED,", acc_content)  # transaction id and email
        self.assertNotIn("p1@test.com", acc_content)
        self.assertNotIn("TXN-A", acc_content)


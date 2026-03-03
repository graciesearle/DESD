import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone

from products.models import Product, Farm
from marketplace.models import Category
from cart.models import Cart, CartItem

User = get_user_model()


class CartTestMixin:
    """Shared setUp for all cart test classes."""

    def setUp(self):
        self.client = Client()

        # Customer user
        self.customer = User.objects.create_user(
            email='customer@test.com',
            password='testpass123',
            role='CUSTOMER',
        )

        # Producer user
        self.producer = User.objects.create_user(
            email='producer@test.com',
            password='testpass123',
            role='PRODUCER',
        )

        self.category = Category.objects.create(name='Vegetables', slug='vegetables')

        self.farm = Farm.objects.create(
            producer=self.producer,
            name='Test Farm',
            postcode='BS1 1AA',
        )

        # Standard in-stock, in-season product
        self.product = Product.objects.create(
            producer=self.producer,
            farm=self.farm,
            name='Organic Carrots',
            description='Crunchy carrots',
            price=Decimal('2.99'),
            unit='1kg',
            stock_quantity=10,
            is_available=True,
            category=self.category,
        )

        # Second product from same producer
        self.product2 = Product.objects.create(
            producer=self.producer,
            farm=self.farm,
            name='Free-Range Eggs',
            description='Farm fresh eggs',
            price=Decimal('4.50'),
            unit='dozen',
            stock_quantity=5,
            is_available=True,
            category=self.category,
        )


# ---------------------------------------------------------------------------
# Model Tests
# ---------------------------------------------------------------------------

class CartModelTest(CartTestMixin, TestCase):
    """Tests for Cart and CartItem models."""

    def test_one_active_cart_per_user(self):
        """UniqueConstraint prevents two active carts for the same user."""
        Cart.objects.create(user=self.customer, status='active')
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Cart.objects.create(user=self.customer, status='active')

    def test_item_total_property(self):
        cart = Cart.objects.create(user=self.customer)
        item = CartItem.objects.create(cart=cart, product=self.product, quantity=3)
        self.assertEqual(item.item_total, Decimal('8.97'))

    def test_unique_together_cart_product(self):
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            CartItem.objects.create(cart=cart, product=self.product, quantity=2)


# ---------------------------------------------------------------------------
# API: Add Item
# ---------------------------------------------------------------------------

class AddItemAPITest(CartTestMixin, TestCase):
    """Tests for POST /cart/api/add/"""

    def test_add_item_creates_cart_and_item(self):
        self.client.login(email='customer@test.com', password='testpass123')
        resp = self.client.post(
            '/cart/api/add/',
            json.dumps({'product_id': self.product.id, 'quantity': 2}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['quantity'], 2)

        # Cart and item exist
        cart = Cart.objects.get(user=self.customer, status='active')
        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.first().quantity, 2)

    def test_add_existing_item_increments(self):
        self.client.login(email='customer@test.com', password='testpass123')
        self.client.post(
            '/cart/api/add/',
            json.dumps({'product_id': self.product.id, 'quantity': 2}),
            content_type='application/json',
        )
        resp = self.client.post(
            '/cart/api/add/',
            json.dumps({'product_id': self.product.id, 'quantity': 3}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['quantity'], 5)

        cart = Cart.objects.get(user=self.customer, status='active')
        self.assertEqual(cart.items.first().quantity, 5)

    def test_add_over_stock_rejected(self):
        self.client.login(email='customer@test.com', password='testpass123')
        resp = self.client.post(
            '/cart/api/add/',
            json.dumps({'product_id': self.product.id, 'quantity': 11}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('stock', resp.json()['error'].lower())

    def test_add_unavailable_product_rejected(self):
        self.product.is_available = False
        self.product.save()
        self.client.login(email='customer@test.com', password='testpass123')
        resp = self.client.post(
            '/cart/api/add/',
            json.dumps({'product_id': self.product.id}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('unavailable', resp.json()['error'].lower())

    def test_add_out_of_season_rejected(self):
        self.product.season_end = timezone.now().date() - timedelta(days=1)
        self.product.save()
        self.client.login(email='customer@test.com', password='testpass123')
        resp = self.client.post(
            '/cart/api/add/',
            json.dumps({'product_id': self.product.id}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('season', resp.json()['error'].lower())

    def test_add_deleted_product_rejected(self):
        self.product.delete()  # soft delete
        self.client.login(email='customer@test.com', password='testpass123')
        resp = self.client.post(
            '/cart/api/add/',
            json.dumps({'product_id': self.product.id}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('no longer listed', resp.json()['error'].lower())

    def test_anonymous_user_redirected(self):
        resp = self.client.post(
            '/cart/api/add/',
            json.dumps({'product_id': self.product.id}),
            content_type='application/json',
        )
        # login_required returns 302 redirect
        self.assertEqual(resp.status_code, 302)


# ---------------------------------------------------------------------------
# API: Update Quantity
# ---------------------------------------------------------------------------

class UpdateItemAPITest(CartTestMixin, TestCase):
    """Tests for PATCH /cart/api/update/<item_id>/"""

    def setUp(self):
        super().setUp()
        self.client.login(email='customer@test.com', password='testpass123')
        self.cart = Cart.objects.create(user=self.customer)
        self.item = CartItem.objects.create(
            cart=self.cart, product=self.product, quantity=2,
        )

    def test_update_quantity(self):
        resp = self.client.patch(
            f'/cart/api/update/{self.item.id}/',
            json.dumps({'quantity': 5}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['quantity'], 5)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 5)

    def test_update_quantity_over_stock_rejected(self):
        resp = self.client.patch(
            f'/cart/api/update/{self.item.id}/',
            json.dumps({'quantity': 99}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('stock', resp.json()['error'].lower())

    def test_update_quantity_below_one_rejected(self):
        resp = self.client.patch(
            f'/cart/api/update/{self.item.id}/',
            json.dumps({'quantity': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# API: Remove Item
# ---------------------------------------------------------------------------

class RemoveItemAPITest(CartTestMixin, TestCase):
    """Tests for DELETE /cart/api/remove/<item_id>/"""

    def setUp(self):
        super().setUp()
        self.client.login(email='customer@test.com', password='testpass123')
        self.cart = Cart.objects.create(user=self.customer)
        self.item = CartItem.objects.create(
            cart=self.cart, product=self.product, quantity=2,
        )

    def test_remove_item(self):
        resp = self.client.delete(f'/cart/api/remove/{self.item.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertEqual(CartItem.objects.filter(cart=self.cart).count(), 0)

    def test_remove_last_item_keeps_cart(self):
        self.client.delete(f'/cart/api/remove/{self.item.id}/')
        self.assertTrue(Cart.objects.filter(pk=self.cart.pk).exists())


# ---------------------------------------------------------------------------
# Cart Detail View
# ---------------------------------------------------------------------------

class CartDetailViewTest(CartTestMixin, TestCase):
    """Tests for GET /cart/"""

    def test_cart_detail_shows_items(self):
        self.client.login(email='customer@test.com', password='testpass123')
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        resp = self.client.get('/cart/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Organic Carrots')
        self.assertContains(resp, '5.98')  # 2.99 × 2

    def test_anonymous_user_redirected(self):
        resp = self.client.get('/cart/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_totals_calculated_correctly(self):
        self.client.login(email='customer@test.com', password='testpass123')
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2)   # 5.98
        CartItem.objects.create(cart=cart, product=self.product2, quantity=1)  # 4.50
        resp = self.client.get('/cart/')
        self.assertEqual(resp.status_code, 200)
        # Subtotal: 10.48, Commission (5%): 0.52, Grand total: 11.00
        self.assertContains(resp, '10.48')
        self.assertContains(resp, '0.52')
        self.assertContains(resp, '11.00')


# ---------------------------------------------------------------------------
# Lazy Validation (Stale Items)
# ---------------------------------------------------------------------------

class LazyValidationTest(CartTestMixin, TestCase):
    """Tests that stale/invalid items are cleaned on cart page load."""

    def setUp(self):
        super().setUp()
        self.client.login(email='customer@test.com', password='testpass123')
        self.cart = Cart.objects.create(user=self.customer)

    def test_stale_item_removed_with_message(self):
        """Out-of-season product is removed on cart load with a warning."""
        self.product.season_end = timezone.now().date() - timedelta(days=1)
        self.product.save()
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)

        resp = self.client.get('/cart/')
        self.assertEqual(resp.status_code, 200)
        # Item should have been removed
        self.assertEqual(self.cart.items.count(), 0)
        # Warning message should appear
        self.assertContains(resp, 'no longer in season')

    def test_unavailable_item_removed_with_message(self):
        self.product.is_available = False
        self.product.save()
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)

        resp = self.client.get('/cart/')
        self.assertEqual(self.cart.items.count(), 0)
        self.assertContains(resp, 'unavailable')

    def test_qty_reduced_to_stock_with_message(self):
        """When stock drops below cart quantity, qty is auto-reduced."""
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=8)
        self.product.stock_quantity = 3
        self.product.save()

        resp = self.client.get('/cart/')
        item = self.cart.items.first()
        self.assertEqual(item.quantity, 3)
        self.assertContains(resp, 'reduced from 8 to 3')

    def test_out_of_stock_item_removed(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        self.product.stock_quantity = 0
        self.product.save()

        resp = self.client.get('/cart/')
        self.assertEqual(self.cart.items.count(), 0)
        self.assertContains(resp, 'out of stock')


# ---------------------------------------------------------------------------
# Context Processor
# ---------------------------------------------------------------------------

class ContextProcessorTest(CartTestMixin, TestCase):
    """Tests that cart_item_count is correctly injected."""

    def test_context_processor_count(self):
        self.client.login(email='customer@test.com', password='testpass123')
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=3)
        CartItem.objects.create(cart=cart, product=self.product2, quantity=2)

        resp = self.client.get('/cart/')
        # Total items = 3 + 2 = 5
        self.assertEqual(resp.context['cart_item_count'], 5)

    def test_context_processor_anonymous(self):
        resp = self.client.get('/marketplace/')
        self.assertEqual(resp.context.get('cart_item_count', 0), 0)

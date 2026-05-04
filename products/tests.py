from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from .models import Product, Farm, SurplusDeal
from marketplace.models import Category
from orders.models import Notification, OrderItem
from accounts.models import ProducerProfile, CustomerProfile
from cart.models import Cart, CartItem
from decimal import Decimal
from datetime import timedelta

import datetime 
from io import StringIO
from unittest.mock import patch

User = get_user_model()


class ProductAPITest(TestCase):
    """Tests that producers can CRUD products."""

    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name='Vegetables', slug='vegetables')
        self.user = User.objects.create_user(
            email='producer@test.com',
            password='testpass123',
            role='PRODUCER',
        )
        self.farm = Farm.objects.create(
            producer = self.user,
            name="Test Farm",
            postcode="BS1 1AA"
        )
        self.client.force_authenticate(user=self.user)
        self.product_data = {
            'farm': self.farm.id,
            'name': 'Test Carrots',
            'description': 'Crunchy carrots',
            'price': '2.99',
            'unit': '500g',
            'stock_quantity': 10,
            'is_available': True,
            'category': self.category.id,
        }

    def test_create_product(self):
        response = self.client.post('/api/products/', self.product_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Product.objects.first().producer, self.user)

    def test_list_products(self):
        Product.objects.create(producer=self.user, farm=self.farm, name='Test Carrots', description='Crunchy carrots', price='2.99', unit='500g', stock_quantity=10, is_available=True, category=self.category)
        response = self.client.get('/api/products/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_update_product(self):
        product = Product.objects.create(producer=self.user, farm=self.farm, name='Test Carrots', description='Crunchy carrots', price='2.99', unit='500g', stock_quantity=10, is_available=True, category=self.category)
        response = self.client.patch(f'/api/products/{product.id}/', {'price': '3.99'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        product.refresh_from_db()
        self.assertEqual(str(product.price), '3.99')

    def test_delete_product(self):
        product = Product.objects.create(producer=self.user, farm=self.farm, name='Test Carrots', description='Crunchy carrots', price='2.99', unit='500g', stock_quantity=10, is_available=True, category=self.category)
        response = self.client.delete(f'/api/products/{product.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Product.objects.count(), 0)

    def test_unauthenticated_access(self):
        """Unauthenticated users cannot access the API."""
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/products/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CustomerCannotCRUDTest(TestCase):
    """Tests that customers are blocked from CRUD operations."""

    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name='Vegetables', slug='vegetables')
        self.customer = User.objects.create_user(
            email='customer@test.com',
            password='testpass123',
            role='CUSTOMER',
        )
        self.producer = User.objects.create_user(
            email='producer@test.com',
            password='testpass123',
            role='PRODUCER',
        )
        self.farm = Farm.objects.create(producer=self.producer, name="Test Farm", postcode="BS1 1AB")

        self.product_data = {
            'farm': self.farm.id,
            'name': 'Test Carrots',
            'description': 'Crunchy carrots',
            'price': '2.99',
            'unit': '500g',
            'stock_quantity': 10,
            'is_available': True,
            'category': self.category.id,
        }

    def test_customer_cannot_create(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/products/', self.product_data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_cannot_list(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.get('/api/products/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_cannot_update(self):
        product = Product.objects.create(producer=self.producer, farm=self.farm, name='Test Carrots', description='Crunchy carrots', price='2.99', unit='500g', stock_quantity=10, is_available=True, category=self.category)
        self.client.force_authenticate(user=self.customer)
        response = self.client.patch(f'/api/products/{product.id}/', {'price': '3.99'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_cannot_delete(self):
        product = Product.objects.create(producer=self.producer, farm=self.farm, name='Test Carrots', description='Crunchy carrots', price='2.99', unit='500g', stock_quantity=10, is_available=True, category=self.category)
        self.client.force_authenticate(user=self.customer)
        response = self.client.delete(f'/api/products/{product.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ProducerOwnershipTest(TestCase):
    """Tests that a producer cannot edit/delete another producer's products."""

    def setUp(self):
        self.client = APIClient()
        self.category = Category.objects.create(name='Vegetables', slug='vegetables')
        self.producer_a = User.objects.create_user(
            email='producerA@test.com',
            password='testpass123',
            role='PRODUCER',
        )
        self.producer_b = User.objects.create_user(
            email='producerB@test.com',
            password='testpass123',
            role='PRODUCER',
        )
        self.farm_a = Farm.objects.create(producer=self.producer_a, name="Farm A", postcode="BS1 1AC")

        self.product_data = {
            'farm': self.farm_a.id,
            'name': 'Test Carrots',
            'description': 'Crunchy carrots',
            'price': '2.99',
            'unit': '500g',
            'stock_quantity': 10,
            'is_available': True,
            'category': self.category.id,
        }

    def test_producer_cannot_update_others_product(self):
        product = Product.objects.create(producer=self.producer_a, farm=self.farm_a, name='Test Carrots', description='Crunchy carrots', price='2.99', unit='500g', stock_quantity=10, is_available=True, category=self.category)
        self.client.force_authenticate(user=self.producer_b)
        response = self.client.patch(f'/api/products/{product.id}/', {'price': '3.99'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_producer_cannot_delete_others_product(self):
        product = Product.objects.create(producer=self.producer_a, farm=self.farm_a, name='Test Carrots', description='Crunchy carrots', price='2.99', unit='500g', stock_quantity=10, is_available=True, category=self.category)
        self.client.force_authenticate(user=self.producer_b)
        response = self.client.delete(f'/api/products/{product.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProductManagerTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Veg', slug='veg')
        self.producer = User.objects.create_user(email='season_test@test.com', password='pw', role='PRODUCER')
        ProducerProfile.objects.create(user=self.producer, business_name="Season Test Farm", address="123 Test Lane", postcode="BS1", vacation_mode=False)
        self.farm = Farm.objects.create(producer=self.producer, name='Farm')
        
    def test_active_and_in_season_standard(self):
        """Current date inside standard April to Sept season."""
        mock_date = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        with patch('django.utils.timezone.now', return_value=mock_date):
            p_in = Product.objects.create(producer=self.producer, farm=self.farm, category=self.category, name='In', price=1, season_start='04-01', season_end='09-30', is_available=True)
            p_out = Product.objects.create(producer=self.producer, farm=self.farm, category=self.category, name='Out', price=1, season_start='07-01', season_end='09-30', is_available=True)
            p_year = Product.objects.create(producer=self.producer, farm=self.farm, category=self.category, name='Year', price=1, is_year_round=True, is_available=True)
            
            active = list(Product.objects.active_and_in_season())
            self.assertIn(p_in, active)
            self.assertNotIn(p_out, active)
            self.assertIn(p_year, active)
            
    def test_active_and_in_season_cross_year(self):
        """Cross year e.g. Nov to Jan (next year)."""
        mock_date = datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc)
        with patch('django.utils.timezone.now', return_value=mock_date):
            p_in = Product.objects.create(producer=self.producer, farm=self.farm, category=self.category, name='In', price=1, season_start='11-01', season_end='01-31', is_available=True)
            p_out = Product.objects.create(producer=self.producer, farm=self.farm, category=self.category, name='Out', price=1, season_start='03-01', season_end='05-31', is_available=True)
            
            active = list(Product.objects.active_and_in_season())
            self.assertIn(p_in, active)
            self.assertNotIn(p_out, active)

    def test_active_and_in_season_cross_year_before_jan(self):
        """Cross year e.g. Nov to Feb, when current date is December."""
        mock_date = datetime.datetime(2026, 12, 15, tzinfo=datetime.timezone.utc)
        with patch('django.utils.timezone.now', return_value=mock_date):
            p_in = Product.objects.create(producer=self.producer, farm=self.farm, category=self.category, name='In', price=1, season_start='11-01', season_end='02-28', is_available=True)
            active = list(Product.objects.active_and_in_season())
            self.assertIn(p_in, active)

    def test_active_and_in_season_respects_vacation_mode(self):
        """If a producer is on vacation, their products should not appear."""
        mock_date = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
        with patch('django.utils.timezone.now', return_value=mock_date):
            # Initially, producer is NOT on vacation
            p_visible = Product.objects.create(
                producer=self.producer, farm=self.farm, category=self.category, 
                name='Visible Item', price=1, is_year_round=True, is_available=True
            )
            self.assertIn(p_visible, Product.objects.active_and_in_season())

            # Turn ON vacation mode
            profile = self.producer.producer_profile
            profile.vacation_mode = True
            profile.save()

            # Product should now be hidden
            self.assertNotIn(p_visible, Product.objects.active_and_in_season())


class SeasonalCheckCommandTests(TestCase):
    """Tests the automated background worker for seasonal planning."""

    def setUp(self):
        self.category = Category.objects.create(name='Veg', slug='veg-plan')
        self.producer = User.objects.create_user(email='farmer_plan@test.com', password='pw', role='PRODUCER')
        self.farm = Farm.objects.create(name="Planning Farm", producer=self.producer, postcode="BS1 1AA")

        # Calculate "Next Month's 1st" target date
        self.today = timezone.localdate()
        if self.today.month == 12:
            self.next_month_1st = self.today.replace(year=self.today.year + 1, month=1, day=1)
        else:
            self.next_month_1st = self.today.replace(month=self.today.month + 1, day=1)
            
        self.target_md = self.next_month_1st.strftime('%m-%d')

    def test_seasonal_check_command_triggers_notification(self):
        # Create a product starting next month
        Product.objects.create(
            name="Upcoming Apples",
            producer=self.producer,
            farm=self.farm,
            category=self.category,
            price='3.00',
            unit="kg",
            is_year_round=False,
            season_start=self.target_md,
            is_available=False
        )

        # Mock today to be the 24th of the current month so the command runs
        mock_today = datetime.date(self.today.year, self.today.month, 24)

        # Temporarily override timezone.localdate inside this block
        with patch('django.utils.timezone.localdate', return_value=mock_today):
            out = StringIO()
            # Run the management command and capture its terminal output
            call_command('seasonal_check', stdout=out)
            
            # 1. Check the terminal output
            self.assertIn("Digest sent", out.getvalue())
            
            # 2. Verify the Notification was actually saved to the database
            notification = Notification.objects.filter(
                recipient=self.producer, 
                notification_type="SEASONAL_DIGEST"
            ).first()
            
            self.assertIsNotNone(notification)
            self.assertIn("Upcoming Apples", notification.message)


class SurplusDealModelTest(TestCase):
    """Tests for the SurplusDeal model — discount validation, price calculation, and expiry."""

    def setUp(self):
        self.category = Category.objects.create(name='Veg', slug='surplus-veg')
        self.producer = User.objects.create_user(
            email='surplus_producer@test.com', password='pw', role='PRODUCER'
        )
        ProducerProfile.objects.create(
            user=self.producer, business_name="Surplus Farm",
            address="1 Test Lane", postcode="BS1", vacation_mode=False
        )
        self.farm = Farm.objects.create(
            producer=self.producer, name='Surplus Farm', postcode='BS1 1AA'
        )
        self.product = Product.objects.create(
            producer=self.producer, farm=self.farm, category=self.category,
            name='Lettuce', description='Fresh lettuce', price=Decimal('2.00'),
            unit='head', stock_quantity=50, is_available=True, is_year_round=True
        )

    def test_surplus_deal_price_calculation(self):
        """Discounted price is correctly calculated and saved."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=30,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=48)
        )
        self.assertEqual(deal.original_price, Decimal('2.00'))
        self.assertEqual(deal.discounted_price, Decimal('1.40'))

    def test_surplus_deal_50_percent(self):
        """Maximum 50% discount is calculated correctly."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=50,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=24)
        )
        self.assertEqual(deal.discounted_price, Decimal('1.00'))

    def test_surplus_deal_10_percent(self):
        """Minimum 10% discount is calculated correctly."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=10,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=24)
        )
        self.assertEqual(deal.discounted_price, Decimal('1.80'))

    def test_effective_price_with_active_deal(self):
        """Product.effective_price returns discounted price when deal is active."""
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=25,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=48)
        )
        self.assertEqual(self.product.effective_price, Decimal('1.50'))

    def test_effective_price_without_deal(self):
        """Product.effective_price returns normal price when no deal exists."""
        self.assertEqual(self.product.effective_price, Decimal('2.00'))

    def test_effective_price_with_expired_deal(self):
        """Product.effective_price returns normal price when deal is expired."""
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=30,
            expires_at=timezone.now() - timedelta(hours=1)  # Already expired
        )
        self.assertEqual(self.product.effective_price, Decimal('2.00'))

    def test_is_expired_property(self):
        """SurplusDeal.is_expired returns True when expires_at is in the past."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=30,
            expires_at=timezone.now() - timedelta(hours=1)
        )
        self.assertTrue(deal.is_expired)

    def test_is_not_expired_property(self):
        """SurplusDeal.is_expired returns False when expires_at is in the future."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=30,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=48)
        )
        self.assertFalse(deal.is_expired)

    def test_has_active_surplus_deal(self):
        """has_active_surplus_deal returns True for active, non-expired deals."""
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=20,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=24)
        )
        self.assertTrue(self.product.has_active_surplus_deal)

    def test_has_active_surplus_deal_false_when_none(self):
        """has_active_surplus_deal returns False when no deal exists."""
        self.assertFalse(self.product.has_active_surplus_deal)

    def test_time_remaining_shows_hours_and_minutes(self):
        """time_remaining returns a human readable string."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=30,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=5, minutes=30)
        )
        self.assertIn('h', deal.time_remaining)
        self.assertIn('remaining', deal.time_remaining)

    def test_time_remaining_expired(self):
        """time_remaining returns 'Expired' for past deals."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=30,
            expires_at=timezone.now() - timedelta(hours=1)
        )
        self.assertEqual(deal.time_remaining, 'Expired')

    def test_one_deal_per_product_constraint(self):
        """OneToOneField prevents multiple deals on the same product."""
        from django.db import IntegrityError
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=20,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=24)
        )
        with self.assertRaises(IntegrityError):
            SurplusDeal.objects.create(
                product=self.product,
                discount_percentage=30,
                surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=48)
            )


class SurplusDealViewTest(TestCase):
    """Tests for surplus deal creation, removal, and the customer deals view."""

    def setUp(self):
        self.category = Category.objects.create(name='Veg', slug='surplus-veg-view')
        self.producer = User.objects.create_user(
            email='surplus_view_producer@test.com', password='pw', role='PRODUCER'
        )
        ProducerProfile.objects.create(
            user=self.producer, business_name="View Surplus Farm",
            address="1 Test Lane", postcode="BS1", vacation_mode=False
        )
        self.farm = Farm.objects.create(
            producer=self.producer, name='View Surplus Farm', postcode='BS1 1AA'
        )
        self.product = Product.objects.create(
            producer=self.producer, farm=self.farm, category=self.category,
            name='Tomatoes', description='Fresh tomatoes', price=Decimal('3.00'),
            unit='kg', stock_quantity=30, is_available=True, is_year_round=True
        )
        self.customer = User.objects.create_user(
            email='surplus_customer@test.com', password='pw', role='CUSTOMER'
        )

    def test_producer_can_create_surplus_deal(self):
        """Producer can POST to mark_as_surplus and create a deal."""
        self.client.login(email='surplus_view_producer@test.com', password='pw')
        response = self.client.post(
            f'/marketplace/product/{self.product.pk}/mark-surplus/',
            {'discount_percentage': 30, 'expiry_hours': 48, 'surplus_quantity': 5, 'note': 'Must sell'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SurplusDeal.objects.filter(product=self.product).exists())
        deal = self.product.surplus_deal
        self.assertEqual(deal.discount_percentage, 30)
        self.assertEqual(deal.discounted_price, Decimal('2.10'))

    def test_producer_can_remove_surplus_deal(self):
        """Producer can POST to remove_surplus and delete a deal."""
        self.client.login(email='surplus_view_producer@test.com', password='pw')
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=20,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=24)
        )
        response = self.client.post(
            f'/marketplace/product/{self.product.pk}/remove-surplus/'
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SurplusDeal.objects.filter(product=self.product).exists())

    def test_customer_cannot_create_surplus_deal(self):
        """Customers are blocked from creating surplus deals."""
        self.client.login(email='surplus_customer@test.com', password='pw')
        response = self.client.post(
            f'/marketplace/product/{self.product.pk}/mark-surplus/',
            {'discount_percentage': 30, 'expiry_hours': 48, 'surplus_quantity': 5}
        )
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(SurplusDeal.objects.filter(product=self.product).exists())

    def test_marketplace_surplus_filter_shows_active_deals(self):
        """The marketplace surplus filter lists active, non-expired deals."""
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=25,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=24)
        )
        response = self.client.get('/marketplace/?surplus=true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tomatoes')
        self.assertContains(response, '25% OFF')

    def test_marketplace_surplus_filter_hides_expired_deals(self):
        """Expired deals don't appear when filtering by surplus."""
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=25,
            expires_at=timezone.now() - timedelta(hours=1)
        )
        response = self.client.get('/marketplace/?surplus=true')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Tomatoes')

    def test_discount_percentage_validation_rejects_out_of_range(self):
        """The SurplusDealForm rejects discount values outside 10-50%."""
        from products.forms import SurplusDealForm
        form = SurplusDealForm(data={
            'discount_percentage': 5,
            'expiry_hours': 24,
        })
        self.assertFalse(form.is_valid())


class SurplusDealCartTest(TestCase):
    """Tests that surplus deal discounts flow through the cart correctly."""

    def setUp(self):
        self.category = Category.objects.create(name='Veg', slug='surplus-cart-veg')
        self.producer = User.objects.create_user(
            email='surplus_cart_producer@test.com', password='pw', role='PRODUCER'
        )
        ProducerProfile.objects.create(
            user=self.producer, business_name="Cart Surplus Farm",
            address="1 Test Lane", postcode="BS1", vacation_mode=False
        )
        self.farm = Farm.objects.create(
            producer=self.producer, name='Cart Surplus Farm', postcode='BS1 1AA'
        )
        self.product = Product.objects.create(
            producer=self.producer, farm=self.farm, category=self.category,
            name='Carrots', description='Crunchy carrots', price=Decimal('4.00'),
            unit='kg', stock_quantity=20, is_available=True, is_year_round=True
        )
        self.customer = User.objects.create_user(
            email='surplus_cart_customer@test.com', password='pw', role='CUSTOMER'
        )
        CustomerProfile.objects.create(
            user=self.customer, full_name='Test Customer',
            delivery_address='1 Test St', postcode='BS1 1AA'
        )

    def test_cart_item_total_uses_effective_price(self):
        """CartItem.item_total uses the surplus discounted price."""
        SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=25,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=24)
        )
        cart = Cart.objects.create(user=self.customer)
        item = CartItem.objects.create(cart=cart, product=self.product, quantity=3)
        # 4.00 * 0.75 = 3.00 per unit, 3.00 * 3 = 9.00
        self.assertEqual(item.item_total, Decimal('9.00'))

    def test_cart_item_total_normal_price_without_deal(self):
        """CartItem.item_total uses normal price when no deal exists."""
        cart = Cart.objects.create(user=self.customer)
        item = CartItem.objects.create(cart=cart, product=self.product, quantity=3)
        # 4.00 * 3 = 12.00
        self.assertEqual(item.item_total, Decimal('12.00'))


class ExpireSurplusDealsCommandTest(TestCase):
    """Tests the expire_surplus_deals management command."""

    def setUp(self):
        self.category = Category.objects.create(name='Veg', slug='expire-veg')
        self.producer = User.objects.create_user(
            email='expire_producer@test.com', password='pw', role='PRODUCER'
        )
        self.farm = Farm.objects.create(
            producer=self.producer, name='Expire Farm', postcode='BS1 1AA'
        )
        self.product = Product.objects.create(
            producer=self.producer, farm=self.farm, category=self.category,
            name='Spinach', price=Decimal('2.50'), unit='bag',
            stock_quantity=10, is_available=True, is_year_round=True
        )

    def test_expired_deals_are_deactivated(self):
        """The command deactivates deals past their expiry."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=20,
            expires_at=timezone.now() - timedelta(hours=1),
            is_active=True
        )
        out = StringIO()
        call_command('expire_surplus_deals', stdout=out)
        deal.refresh_from_db()
        self.assertFalse(deal.is_active)
        self.assertIn('Deactivated 1', out.getvalue())

    def test_active_deals_not_deactivated(self):
        """The command does not deactivate still-active deals."""
        deal = SurplusDeal.objects.create(
            product=self.product,
            discount_percentage=20,
            surplus_quantity=10, expires_at=timezone.now() + timedelta(hours=24),
            is_active=True
        )
        out = StringIO()
        call_command('expire_surplus_deals', stdout=out)
        deal.refresh_from_db()
        self.assertTrue(deal.is_active)
        self.assertIn('No expired', out.getvalue())
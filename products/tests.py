from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from .models import Product, Farm
from marketplace.models import Category
from orders.models import Notification

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
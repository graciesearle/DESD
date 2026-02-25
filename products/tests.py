from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status
from .models import Product

User = get_user_model()


class ProductAPITest(TestCase):
    """Tests that producers can CRUD products."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='producer@test.com',
            password='testpass123',
            role='PRODUCER',
        )
        self.client.force_authenticate(user=self.user)
        self.product_data = {
            'name': 'Test Carrots',
            'description': 'Crunchy carrots',
            'price': '2.99',
            'unit': '500g',
            'stock_quantity': 10,
            'is_available': True,
        }

    def test_create_product(self):
        response = self.client.post('/api/products/', self.product_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Product.objects.first().producer, self.user)

    def test_list_products(self):
        Product.objects.create(producer=self.user, **self.product_data)
        response = self.client.get('/api/products/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_update_product(self):
        product = Product.objects.create(producer=self.user, **self.product_data)
        response = self.client.patch(f'/api/products/{product.id}/', {'price': '3.99'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        product.refresh_from_db()
        self.assertEqual(str(product.price), '3.99')

    def test_delete_product(self):
        product = Product.objects.create(producer=self.user, **self.product_data)
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
        self.product_data = {
            'name': 'Test Carrots',
            'description': 'Crunchy carrots',
            'price': '2.99',
            'unit': '500g',
            'stock_quantity': 10,
            'is_available': True,
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
        product = Product.objects.create(producer=self.producer, **self.product_data)
        self.client.force_authenticate(user=self.customer)
        response = self.client.patch(f'/api/products/{product.id}/', {'price': '3.99'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_customer_cannot_delete(self):
        product = Product.objects.create(producer=self.producer, **self.product_data)
        self.client.force_authenticate(user=self.customer)
        response = self.client.delete(f'/api/products/{product.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ProducerOwnershipTest(TestCase):
    """Tests that a producer cannot edit/delete another producer's products."""

    def setUp(self):
        self.client = APIClient()
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
        self.product_data = {
            'name': 'Test Carrots',
            'description': 'Crunchy carrots',
            'price': '2.99',
            'unit': '500g',
            'stock_quantity': 10,
            'is_available': True,
        }

    def test_producer_cannot_update_others_product(self):
        product = Product.objects.create(producer=self.producer_a, **self.product_data)
        self.client.force_authenticate(user=self.producer_b)
        response = self.client.patch(f'/api/products/{product.id}/', {'price': '3.99'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_producer_cannot_delete_others_product(self):
        product = Product.objects.create(producer=self.producer_a, **self.product_data)
        self.client.force_authenticate(user=self.producer_b)
        response = self.client.delete(f'/api/products/{product.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
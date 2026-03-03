from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model 
from products.models import Product, Farm
from .models import Category
from django.utils import timezone
import datetime

# Get active user model
User = get_user_model()

# Create your tests here.
class MarketplaceTests(TestCase):
    def setUp(self):
        """Set up data for testing."""
        self.client = Client()

        # Create a user
        self.user = User.objects.create_user(email='test@example.com', password='password123')

        # Create a category
        self.category = Category.objects.create(name="Vegetables", slug="vegetables")

        # Create a Farm
        self.farm = Farm.objects.create(
            producer=self.user,
            name="Test Farm",
            postcode="BS1 1AB"
        )

        # Create an active product
        self.active_product = Product.objects.create(
            producer=self.user,
            farm=self.farm,
            name="Organic Carrots",
            price=2.50,
            unit="kg",
            stock_quantity=50,
            category=self.category,
            is_available=True
        )

        # Create an out-of-season product
        self.expired_product = Product.objects.create(
            producer=self.user,
            farm=self.farm,
            name="Cold Cucumber",
            price=3.00,
            unit="each",
            stock_quantity=5,
            category=self.category,
            is_available=True,
            season_end=timezone.now().date() - datetime.timedelta(days=1) # Yesterday
        )
    
    def test_category_slug_auto_generation(self):
        """Test that the slug is automatically generated from the name. (should lower case everything, join space with '-')"""
        new_cat = Category.objects.create(name="Dairy Products")
        self.assertEqual(new_cat.slug, "dairy-products")

    def test_active_and_in_season_manager(self):
        """
        Tests that the custom ProductManager in models.py is working as intended:
        Only carrots should show not the cucumber.
        """
        active_products = Product.objects.active_and_in_season()
        self.assertIn(self.active_product, active_products)
        self.assertNotIn(self.expired_product, active_products)

    def test_product_list_view_status_code(self):
        """Test that the marketplace page loads successfully."""
        response = self.client.get(reverse('marketplace:product_list'))
        self.assertEqual(response.status_code, 200) # Success
        self.assertTemplateUsed(response, 'marketplace/product_list.html')
    
    def test_api_endpoint_returns_json(self):
        """Test that the DRF API returns the correct data structure."""
        response = self.client.get(reverse('marketplace:api_get_products'))
        self.assertEqual(response.status_code, 200)
        # Check if json contains active product
        self.assertContains(response, "Organic Carrots")
        # Ensure expired product is not in JSON
        self.assertNotContains(response, "Cold Cucumber")

    def test_category_filter_logic(self):
        """Test that filtering by category in the URL works."""
        fruit_cat = Category.objects.create(name="Fruit", slug="fruit")
        # Filter by vegetables
        response = self.client.get(reverse('marketplace:product_list') + '?category=vegetables')
        self.assertContains(response, "Organic Carrots")

        # Filter by Fruit (should by empty)
        response = self.client.get(reverse('marketplace:product_list') + '?category=fruit')
        self.assertNotContains(response, "Organic Carrots")

    def test_uncategorised_fallback(self):
        """Products are correctly categorised (even if the category is deleted), by making them uncategorised."""
        product = Product.objects.create(producer=self.user, farm=self.farm, name="Tomato", price=1.00, unit="kg", category=self.category)
        self.category.delete()
        product.refresh_from_db()
        self.assertEqual(product.category.name, "Uncategorised")

    def test_api_category_filter(self):
        """Category filtering works accurately (API side)"""
        response = self.client.get(reverse('marketplace:api_get_products') + '?category=vegetables')
        self.assertContains(response, "Organic Carrots")
    
    def test_api_data_completeness(self):
        """TC-004 Browse & Categories criteria: Product information is complete and readable"""
        response = self.client.get(reverse('marketplace:api_get_products'))
        data = response.json()[0]
        # Check that readable info is in json
        keys = ['name', 'price', 'unit', 'producer', 'category_name', 'season_end', 'farm_name', 'farm_postcode']
        for key in keys:
            self.assertIn(key, data)

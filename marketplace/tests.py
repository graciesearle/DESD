from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model 
from products.models import Product, Farm, Allergen
from accounts.models import ProducerProfile, CustomerProfile
from orders.models import Notification
from .models import Category, EducationalPost
from .forms import ProductAddForm
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

        # Allergen fixtures for safety-display acceptance checks
        self.milk = Allergen.objects.create(name="Milk")
        self.wheat = Allergen.objects.create(name="Wheat (Gluten)")
        self.walnuts = Allergen.objects.create(name="Nuts (Walnuts)")

        self.cheddar = Product.objects.create(
            producer=self.user,
            farm=self.farm,
            name="Cheddar Cheese",
            description="Mature farmhouse cheddar",
            price=4.50,
            unit="each",
            stock_quantity=10,
            category=self.category,
            is_available=True,
        )
        self.cheddar.allergens.add(self.milk)

        self.walnut_bread = Product.objects.create(
            producer=self.user,
            farm=self.farm,
            name="Walnut Bread",
            description="Freshly baked loaf with walnuts",
            price=3.20,
            unit="each",
            stock_quantity=8,
            category=self.category,
            is_available=True,
        )
        self.walnut_bread.allergens.add(self.wheat, self.walnuts)

        self.fresh_apples = Product.objects.create(
            producer=self.user,
            farm=self.farm,
            name="Fresh Apples",
            description="Seasonal hand-picked apples",
            price=2.10,
            unit="kg",
            stock_quantity=25,
            category=self.category,
            is_available=True,
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
            season_start=(timezone.now().date() - datetime.timedelta(days=30)).strftime('%m-%d'),
            season_end=(timezone.now().date() - datetime.timedelta(days=1)).strftime('%m-%d') # Yesterday
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

    def test_product_detail_shows_single_allergen_contains_label(self):
        response = self.client.get(reverse('marketplace:product_detail', args=[self.cheddar.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span class="allergen-tag-detail">Milk</span>')

    def test_product_detail_shows_multiple_allergens(self):
        response = self.client.get(reverse('marketplace:product_detail', args=[self.walnut_bread.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span class="allergen-tag-detail">Wheat (Gluten)</span>')
        self.assertContains(response, '<span class="allergen-tag-detail">Nuts (Walnuts)</span>')

    def test_product_detail_shows_no_common_allergens(self):
        response = self.client.get(reverse('marketplace:product_detail', args=[self.fresh_apples.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No common allergens")

    def test_allergen_dropdown_filter_for_nuts(self):
        response = self.client.get(
            reverse('marketplace:product_list'),
            {'allergen_mode': 'contains', 'allergen': 'Nuts'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Walnut Bread")

    def test_filter_products_without_allergens(self):
        response = self.client.get(reverse('marketplace:product_list'), {'has_allergens': 'no'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fresh Apples")
        self.assertNotContains(response, "Walnut Bread")


class ProductAllergenDisclosureFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='producer@example.com', password='password123', role='PRODUCER')
        self.category = Category.objects.create(name="Bakery", slug="bakery")
        self.farm = Farm.objects.create(producer=self.user, name="Orchard Farm", postcode="BS1 1AB")

    def _base_data(self):
        return {
            'name': 'Rustic Loaf',
            'description': 'Handmade bread',
            'price': '3.50',
            'unit': 'each',
            'stock_quantity': 12,
            'low_stock_threshold': 3,
            'category': self.category.id,
            'farm': self.farm.id,
            'is_available': 'True',
            'is_year_round': 'True',
        }

    def test_listing_requires_explicit_allergen_confirmation(self):
        form = ProductAddForm(data=self._base_data(), user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('allergen_info_confirmed', form.errors)

    def test_listing_allows_no_allergens_when_confirmed(self):
        data = self._base_data()
        data['allergen_info_confirmed'] = 'on'
        form = ProductAddForm(data=data, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_listing_rejects_explicit_unconfirmed_allergen_declaration(self):
        data = self._base_data()
        data['allergen_info_confirmed'] = ''
        form = ProductAddForm(data=data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('allergen_info_confirmed', form.errors)

class EducationalPostTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create a Producer
        self.producer_user = User.objects.create_user(
            email='farm@test.com', password='Password123!', role='PRODUCER'
        )
        self.producer_profile = ProducerProfile.objects.create(
            user=self.producer_user, business_name="Test Farm"
        )
        
        # 2. Create a Customer and Subscribe them to the Producer
        self.customer_user = User.objects.create_user(
            email='customer@test.com', password='Password123!', role='CUSTOMER'
        )
        self.customer_profile = CustomerProfile.objects.create(
            user=self.customer_user, receive_educational_emails=True
        )
        self.customer_profile.subscribed_producers.add(self.producer_profile)

    def test_post_creation_and_notification(self):
        """Test that creating a post via the view generates a notification for subscribers."""
        self.client.login(email='farm@test.com', password='Password123!')
        
        # Submit the create post form
        response = self.client.post(reverse('marketplace:create_educational_post'), {
            'title': 'Spring Harvest',
            'content': 'Carrots are ready!',
            'post_type': 'SEASONAL_UPDATE',
            'send_email_alert': 'on'
        })
        
        # Check it redirected successfully
        self.assertEqual(response.status_code, 302)
        
        # Check the post was created in DB
        post = EducationalPost.objects.first()
        self.assertIsNotNone(post)
        self.assertEqual(post.title, 'Spring Harvest')
        
        # Check that a notification was generated for the subscribed customer
        notification = Notification.objects.filter(recipient=self.customer_user).first()
        self.assertIsNotNone(notification)
        self.assertEqual(notification.notification_type, 'NEW_POST')
        self.assertEqual(notification.educational_post, post)

    def test_educational_post_manager_soft_delete(self):
        """Test that soft-deleted posts do not appear in active_posts()"""
        post = EducationalPost.objects.create(
            producer=self.producer_user, title="Test Post", content="Hello"
        )
        
        # Should be active initially
        self.assertEqual(EducationalPost.objects.active_posts().count(), 1)
        
        # Soft delete the post
        post.delete() 
        
        # Should no longer be in active_posts
        self.assertEqual(EducationalPost.objects.active_posts().count(), 0)
        # But should still exist in the database entirely (audit trail)
        self.assertEqual(EducationalPost.all_objects.count(), 1)

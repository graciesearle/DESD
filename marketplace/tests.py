from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model 
from products.models import Product, Farm, Allergen, ProductBatch
from accounts.models import ProducerProfile, CustomerProfile
from orders.models import Notification
from ai_engineering.models import BatchGradeChangeEvent
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


class ProductAddBatchScanFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.producer = User.objects.create_user(
            email='scan-flow-producer@test.com',
            password='Password123!',
            role='PRODUCER',
        )
        self.category = Category.objects.create(name='Leafy Greens', slug='leafy-greens')
        self.farm = Farm.objects.create(
            producer=self.producer,
            name='Scan Flow Farm',
            postcode='BS1 4AA',
        )
        self.client.login(email='scan-flow-producer@test.com', password='Password123!')

    def test_product_add_redirects_to_edit_with_auto_scan_flag(self):
        response = self.client.post(
            reverse('marketplace:product_add'),
            {
                'name': 'Flow Test Kale',
                'description': 'Batch scan continuation test product',
                'price': '3.25',
                'unit': 'kg',
                'stock_quantity': 12,
                'low_stock_threshold': 3,
                'category': self.category.id,
                'farm': self.farm.id,
                'is_available': 'True',
                'is_year_round': 'True',
                'allergen_info_confirmed': 'on',
                'start_batch_scan': '1',
            },
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name='Flow Test Kale', producer=self.producer)
        expected_url = f"{reverse('marketplace:product_edit', args=[product.pk])}?auto_ai_scan=1"
        self.assertEqual(response.url, expected_url)

    def test_auto_scan_edit_page_prefills_lot_quantity_from_unbatched_stock(self):
        product = Product.objects.create(
            producer=self.producer,
            farm=self.farm,
            name='Flow Prefill Apples',
            description='Prefill lot quantity check',
            price=4.10,
            unit='kg',
            stock_quantity=12,
            category=self.category,
            is_available=True,
        )

        response = self.client.get(
            f"{reverse('marketplace:product_edit', args=[product.pk])}?auto_ai_scan=1"
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertRegex(html, r'id="batch-intake-quantity"[^>]*value="12"')
        self.assertRegex(html, r'id="batch-use-existing-stock"[^>]*checked')
        self.assertIn('Use existing ungraded stock first (12 available).', html)

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


class ProductBatchManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.producer = User.objects.create_user(
            email='batch-producer@test.com',
            password='Password123!',
            role='PRODUCER',
        )
        self.category = Category.objects.create(name='Roots', slug='roots')
        self.farm = Farm.objects.create(
            producer=self.producer,
            name='Batch Farm',
            postcode='BS1 2AA',
        )
        self.product = Product.objects.create(
            producer=self.producer,
            farm=self.farm,
            name='Batch Carrots',
            description='Batch test product',
            price=2.50,
            unit='kg',
            stock_quantity=10,
            category=self.category,
            is_available=True,
        )
        self.batch = ProductBatch.objects.create(
            product=self.product,
            grade='B',
            stock_quantity=6,
            base_price=self.product.price,
            discount_percent=10,
            is_active=True,
        )
        self.client.login(email='batch-producer@test.com', password='Password123!')

    def test_producer_can_retire_batch(self):
        resp = self.client.post(reverse('marketplace:product_batch_toggle', args=[self.batch.id]))
        self.assertEqual(resp.status_code, 302)
        self.batch.refresh_from_db()
        self.assertFalse(self.batch.is_active)

    def test_zero_stock_batch_cannot_be_reactivated(self):
        self.batch.stock_quantity = 0
        self.batch.is_active = False
        self.batch.save()

        resp = self.client.post(reverse('marketplace:product_batch_toggle', args=[self.batch.id]))
        self.assertEqual(resp.status_code, 302)
        self.batch.refresh_from_db()
        self.assertFalse(self.batch.is_active)

    def test_producer_can_edit_batch_grade_with_reason(self):
        resp = self.client.post(
            reverse('marketplace:product_batch_grade_edit', args=[self.batch.id]),
            {'new_grade': 'A', 'reason': 'Lot quality upgraded after sorting'},
        )
        self.assertEqual(resp.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.grade, 'A')
        self.assertEqual(BatchGradeChangeEvent.objects.filter(batch=self.batch).count(), 1)

    def test_batch_grade_edit_requires_reason(self):
        resp = self.client.post(
            reverse('marketplace:product_batch_grade_edit', args=[self.batch.id]),
            {'new_grade': 'C', 'reason': ''},
        )
        self.assertEqual(resp.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.grade, 'B')

    def test_batch_grade_edit_merges_into_existing_grade_bucket(self):
        target = ProductBatch.objects.create(
            product=self.product,
            grade='A',
            stock_quantity=2,
            base_price=self.product.price,
            discount_percent=0,
            is_active=True,
        )

        resp = self.client.post(
            reverse('marketplace:product_batch_grade_edit', args=[self.batch.id]),
            {'new_grade': 'A', 'reason': 'Sorted and regraded to premium'},
        )

        self.assertEqual(resp.status_code, 302)
        self.batch.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(self.batch.grade, 'B')
        self.assertEqual(self.batch.stock_quantity, 0)
        self.assertFalse(self.batch.is_active)
        self.assertEqual(target.stock_quantity, 8)
        self.assertEqual(
            ProductBatch.objects.filter(product=self.product, grade='A', is_active=True).count(),
            1,
        )

    def test_batch_stock_subtract_action_reduces_grade_quantity(self):
        resp = self.client.post(
            reverse('marketplace:product_batch_stock_adjust', args=[self.batch.id]),
            {
                'action': 'subtract',
                'quantity': 2,
                'reason': 'Damaged produce removed',
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.batch.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.batch.stock_quantity, 4)
        self.assertEqual(self.product.stock_quantity, 14)

    def test_batch_stock_move_action_transfers_between_grades(self):
        target = ProductBatch.objects.create(
            product=self.product,
            grade='A',
            stock_quantity=1,
            base_price=self.product.price,
            discount_percent=0,
            is_active=True,
        )

        resp = self.client.post(
            reverse('marketplace:product_batch_stock_adjust', args=[self.batch.id]),
            {
                'action': 'move',
                'quantity': 3,
                'target_grade': 'A',
                'reason': 'Quality improved after sorting',
            },
        )

        self.assertEqual(resp.status_code, 302)
        self.batch.refresh_from_db()
        target.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(self.batch.stock_quantity, 3)
        self.assertEqual(target.stock_quantity, 4)
        self.assertEqual(self.product.stock_quantity, 17)
        self.assertTrue(
            BatchGradeChangeEvent.objects.filter(
                batch=target,
                old_grade='B',
                new_grade='A',
            ).exists()
        )

    def test_product_edit_redirects_back_to_edit_page(self):
        resp = self.client.post(
            reverse('marketplace:product_edit', args=[self.product.id]),
            {
                'name': self.product.name,
                'description': self.product.description,
                'price': str(self.product.price),
                'unit': self.product.unit,
                'stock_quantity': 999,
                'low_stock_threshold': 2,
                'category': self.category.id,
                'farm': self.farm.id,
                'is_available': 'True',
                'is_year_round': 'True',
                'allergen_info_confirmed': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('marketplace:product_edit', args=[self.product.id]))

    def test_product_edit_with_batches_syncs_stock_to_batch_total(self):
        resp = self.client.post(
            reverse('marketplace:product_edit', args=[self.product.id]),
            {
                'name': self.product.name,
                'description': self.product.description,
                'price': str(self.product.price),
                'unit': self.product.unit,
                'stock_quantity': 1234,
                'low_stock_threshold': 2,
                'category': self.category.id,
                'farm': self.farm.id,
                'is_available': 'True',
                'is_year_round': 'True',
                'allergen_info_confirmed': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 16)

    def test_product_edit_disables_stock_field_when_batches_exist(self):
        resp = self.client.get(reverse('marketplace:product_edit', args=[self.product.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertRegex(html, r'name="stock_quantity"[^>]*disabled')
        self.assertIn(
            "Adjust stock through Batch Intake and Manage Grade Stock actions below.",
            html,
        )

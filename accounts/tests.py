from django.test import TestCase, RequestFactory, Client
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import HttpResponse
from django.urls import reverse

from decimal import Decimal

from accounts.models import ProducerProfile, CustomerProfile
from marketplace.models import Category
from products.models import Farm, Product, Review
from accounts.validators import (
    MinimumLengthValidator,
    UppercaseValidator,
    LowercaseValidator,
    NumberValidator,
    SpecialCharacterValidator,
    CommonPasswordValidator,
)
from accounts.decorators import (
    producer_required,
    customer_required,
    admin_required,
)
from accounts.forms import validate_phone_number

from accounts.forms import CustomerRegistrationForm

User = get_user_model()

# For decorator tests

@producer_required
def producer_only_view(request):
    return HttpResponse("ok", status=200)

@customer_required
def customer_only_view(request):
    return HttpResponse("ok", status=200)

@admin_required
def admin_only_view(request):
    return HttpResponse("ok", status=200)


# CustomUser model tests

class CustomUserModelTests(TestCase):

    def test_create_producer_user(self):
        user = User.objects.create_user(
            email="jane@bristolvalleyfarm.com",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
            phone="01179 123456",
        )
        self.assertEqual(user.email, "jane@bristolvalleyfarm.com")
        self.assertEqual(user.role, User.Role.PRODUCER)
        self.assertTrue(user.is_producer)
        self.assertFalse(user.is_customer)

    def test_create_customer_user(self):
        user = User.objects.create_user(
            email="robert@email.com",
            password="Secure#Pass1",
            role=User.Role.CUSTOMER,
        )
        self.assertTrue(user.is_customer)
        self.assertFalse(user.is_producer)

    def test_password_is_hashed(self):
        user = User.objects.create_user(
            email="test@example.com",
            password="Secure#Pass1",
        )
        self.assertNotEqual(user.password, "Secure#Pass1")
        self.assertTrue(user.password.startswith(("pbkdf2_", "argon2")))

    def test_email_is_unique(self):
        User.objects.create_user(email="dup@example.com", password="Secure#Pass1")
        with self.assertRaises(IntegrityError):
            User.objects.create_user(email="dup@example.com", password="Secure#Pass1")

    def test_community_group_is_customer(self):
        user = User.objects.create_user(
            email="school@example.com",
            password="Secure#Pass1",
            role=User.Role.COMMUNITY_GROUP,
        )
        self.assertTrue(user.is_customer)
        self.assertTrue(user.is_community_group)

    def test_restaurant_is_customer(self):
        user = User.objects.create_user(
            email="chef@example.com",
            password="Secure#Pass1",
            role=User.Role.RESTAURANT,
        )
        self.assertTrue(user.is_customer)
        self.assertTrue(user.is_restaurant)

# Profile model tests

class ProducerProfileTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="producer@farm.com",
            password="Secure#Pass1",
            role=User.Role.PRODUCER,
        )

    def test_producer_profile_creation(self):
        profile = ProducerProfile.objects.create(
            user=self.user,
            business_name="Bristol Valley Farm",
            contact_name="Jane Smith",
            address="1 Farm Lane, Bristol",
            postcode="BS1 4DJ",
        )
        self.assertEqual(profile.business_name, "Bristol Valley Farm")
        self.assertEqual(profile.postcode, "BS1 4DJ")
        self.assertEqual(profile.lead_time_hours, 48)   # default
        self.assertFalse(profile.organic_certified)

    def test_full_address_property(self):
        profile = ProducerProfile.objects.create(
            user=self.user,
            business_name="Test Farm",
            contact_name="Farmer Joe",
            address="10 Country Road",
            postcode="BS2 0AB",
        )
        self.assertEqual(profile.full_address, "10 Country Road, BS2 0AB")


class CustomerProfileTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="customer@email.com",
            password="Secure#Pass1",
            role=User.Role.CUSTOMER,
        )

    def test_customer_profile_creation(self):
        profile = CustomerProfile.objects.create(
            user=self.user,
            full_name="Robert Johnson",
            delivery_address="45 Park Street, Bristol",
            postcode="BS1 5JG",
        )
        self.assertEqual(profile.full_name, "Robert Johnson")
        self.assertEqual(profile.postcode, "BS1 5JG")
        self.assertEqual(profile.customer_type, CustomerProfile.CustomerType.INDIVIDUAL)

    def test_display_name_uses_organisation(self):
        profile = CustomerProfile.objects.create(
            user=self.user,
            full_name="John Doe",
            organisation_name="St Mary's School",
            delivery_address="1 School Lane",
            postcode="BS3 1AA",
        )
        self.assertEqual(profile.display_name, "St Mary's School")

# Password validator tests

class PasswordValidatorTests(TestCase):

    def test_short_password_rejected(self):
        v = MinimumLengthValidator(min_length=8)
        with self.assertRaises(ValidationError) as ctx:
            v.validate("abc")
        self.assertEqual(ctx.exception.code, "password_too_short")

    def test_long_enough_password_accepted(self):
        v = MinimumLengthValidator(min_length=8)
        v.validate("abcdefgh") 

    def test_no_uppercase_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            UppercaseValidator().validate("alllower1!")
        self.assertEqual(ctx.exception.code, "password_no_upper")

    def test_uppercase_present_accepted(self):
        UppercaseValidator().validate("HasUpper1!")

    def test_no_lowercase_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            LowercaseValidator().validate("ALLUPPER1!")
        self.assertEqual(ctx.exception.code, "password_no_lower")

    def test_no_digit_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            NumberValidator().validate("NoDigits!")
        self.assertEqual(ctx.exception.code, "password_no_number")

    def test_no_special_char_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            SpecialCharacterValidator().validate("NoSpecial1")
        self.assertEqual(ctx.exception.code, "password_no_special")

    def test_common_password_rejected(self):
        with self.assertRaises(ValidationError):
            CommonPasswordValidator().validate("password123")

    def test_strong_password_passes_all(self):
        strong = "Bristol#Food2024"
        for validator in [
            MinimumLengthValidator(),
            UppercaseValidator(),
            LowercaseValidator(),
            NumberValidator(),
            SpecialCharacterValidator(),
            CommonPasswordValidator(),
        ]:
            validator.validate(strong)

# Decorator tests

class DecoratorTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.producer = User.objects.create_user(
            email="prod@farm.com", password="Secure#Pass1", role=User.Role.PRODUCER
        )
        self.customer = User.objects.create_user(
            email="cust@email.com", password="Secure#Pass1", role=User.Role.CUSTOMER
        )
        self.admin = User.objects.create_user(
            email="admin@brfn.com", password="Secure#Pass1", role=User.Role.ADMIN
        )

    def _get(self, view, user):
        request = self.factory.get("/fake/")
        request.user = user
        return view(request)

    def test_producer_decorator_allows_producer(self):
        response = self._get(producer_only_view, self.producer)
        self.assertEqual(response.status_code, 200)

    def test_producer_decorator_blocks_customer(self):
        with self.assertRaises(PermissionDenied):
            self._get(producer_only_view, self.customer)

    def test_customer_decorator_allows_customer(self):
        response = self._get(customer_only_view, self.customer)
        self.assertEqual(response.status_code, 200)

    def test_customer_decorator_blocks_producer(self):
        with self.assertRaises(PermissionDenied):
            self._get(customer_only_view, self.producer)
        
    def test_admin_decorator_allows_admin(self):
        response = self._get(admin_only_view, self.admin)
        self.assertEqual(response.status_code, 200)

    def test_admin_decorator_blocks_producer(self):
        with self.assertRaises(PermissionDenied):
            self._get(admin_only_view, self.producer)


<<<<<<< HEAD
class InstitutionalValidationTests(TestCase):

    def test_community_group_requires_organisation_name(self):
        form_data = {
            "email": "catering@stmarys-school.org.uk",
            "phone": "07700900123",
            "full_name": "Mary Taylor",
            "customer_type": "COMMUNITY_GROUP",
            "organisation_name": "",  # Missing!
            "delivery_address": "123 School Lane",
            "postcode": "BS9 4LR",
            "receive_surplus_alerts": True,
            "receive_educational_emails": True,
            "password": "SecurePassword1!",
            "confirm_password": "SecurePassword1!"
        }
        form = CustomerRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("organisation_name", form.errors)

    def test_institutional_account_blocks_free_email(self):
        form_data = {
            "email": "my.school@gmail.com",  # Blocked domain!
            "phone": "07700900123",
            "full_name": "Mary Taylor",
            "customer_type": "COMMUNITY_GROUP",
            "organisation_name": "St Marys School",
            "delivery_address": "123 School Lane",
            "postcode": "BS9 4LR",
            "receive_surplus_alerts": True,
            "receive_educational_emails": True,
            "password": "SecurePassword1!",
            "confirm_password": "SecurePassword1!"
        }
        form = CustomerRegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
=======
class ProducerReviewResponseTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.producer = User.objects.create_user(
            email="owner@farm.com", password="Secure#Pass1", role=User.Role.PRODUCER
        )
        ProducerProfile.objects.create(
            user=self.producer,
            business_name="Owner Farm",
            contact_name="Owner",
            address="1 Road",
            postcode="BS1 1AA",
        )
        self.other_producer = User.objects.create_user(
            email="other@farm.com", password="Secure#Pass1", role=User.Role.PRODUCER
        )
        ProducerProfile.objects.create(
            user=self.other_producer,
            business_name="Other Farm",
            contact_name="Other",
            address="2 Road",
            postcode="BS1 2AA",
        )
        self.customer = User.objects.create_user(
            email="reviewer@email.com", password="Secure#Pass1", role=User.Role.CUSTOMER
        )
        CustomerProfile.objects.create(
            user=self.customer,
            full_name="Review User",
            delivery_address="3 Road",
            postcode="BS1 3AA",
        )

        category = Category.objects.create(name="Veg", slug="veg-test")
        farm = Farm.objects.create(producer=self.producer, name="Owner Farm", postcode="BS1 1AA")
        self.product = Product.objects.create(
            producer=self.producer,
            farm=farm,
            category=category,
            name="Organic Tomatoes",
            description="Fresh tomatoes",
            price=Decimal("3.50"),
            unit="kg",
            stock_quantity=10,
            is_available=True,
        )
        self.review = Review.objects.create(
            customer=self.customer,
            product=self.product,
            rating=5,
            title="Excellent quality and flavour",
            body="Great produce",
        )

    def test_producer_reviews_page_lists_reviews(self):
        self.client.login(email="owner@farm.com", password="Secure#Pass1")
        response = self.client.get(reverse("producer_reviews"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Organic Tomatoes")
        self.assertContains(response, "Excellent quality and flavour")

    def test_producer_can_respond_to_review(self):
        self.client.login(email="owner@farm.com", password="Secure#Pass1")
        response = self.client.post(
            reverse("producer_review_respond", args=[self.review.id]),
            {"producer_response": "Thanks for your support."},
        )
        self.assertRedirects(response, reverse("producer_reviews"))
        self.review.refresh_from_db()
        self.assertEqual(self.review.producer_response, "Thanks for your support.")
        self.assertIsNotNone(self.review.producer_responded_at)

    def test_other_producer_cannot_respond_to_review(self):
        self.client.login(email="other@farm.com", password="Secure#Pass1")
        response = self.client.post(
            reverse("producer_review_respond", args=[self.review.id]),
            {"producer_response": "Should not be allowed."},
        )
        self.assertEqual(response.status_code, 404)


class SettingsFeatureTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create a Producer
        self.producer_user = User.objects.create_user(
            email="farmer@test.com", password="Secure#Pass1", role=User.Role.PRODUCER, phone="+447911111111"
        )
        self.producer_profile = ProducerProfile.objects.create(
            user=self.producer_user, business_name="Farmer Joe", address="1 Farm Lane", postcode="BS1"
        )
        
        # Create a Customer
        self.customer_user = User.objects.create_user(
            email="buyer@test.com", password="Secure#Pass1", role=User.Role.CUSTOMER, phone="+447922222222"
        )
        self.customer_profile = CustomerProfile.objects.create(
            user=self.customer_user, full_name="Buyer Bob", delivery_address="2 Street", postcode="BS2"
        )

    def test_phone_validation_logic(self):
        """Test the shared validate_phone_number helper."""
        # Valid UK
        self.assertEqual(validate_phone_number("+447912345678"), "+447912345678")
        
        # Invalid Format (letters)
        with self.assertRaises(ValidationError):
            validate_phone_number("07912-HELLO")
            
        # Too Short
        with self.assertRaises(ValidationError):
            validate_phone_number("+441")

        # Too Long
        with self.assertRaises(ValidationError):
            validate_phone_number("+442193129391391939193291391")
            
        # Duplicate check (the customer's number already exists)
        with self.assertRaises(ValidationError):
            validate_phone_number("+447922222222")

    def test_settings_view_access(self):
        """Ensure only logged-in users can see settings."""
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 302)

        self.client.login(email="farmer@test.com", password="Secure#Pass1")
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)

    def test_settings_tab_visibility(self):
        """Verify producers see business info, but customers don't."""
        # Test Producer
        self.client.login(email="farmer@test.com", password="Secure#Pass1")
        response = self.client.get(reverse('settings'))
        self.assertContains(response, "Business Info")
        self.assertNotContains(response, "Profile & Delivery")

        # Test Customer
        self.client.login(email="buyer@test.com", password="Secure#Pass1")
        response = self.client.get(reverse('settings'))
        self.assertNotContains(response, "Business Info")
        self.assertContains(response, "Profile & Delivery")

    def test_download_my_data_json(self):
        """Verify the JSON export returns valid data."""
        self.client.login(email="farmer@test.com", password="Secure#Pass1")
        response = self.client.get(reverse('export_data'))
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertEqual(data['account']['email'], "farmer@test.com")
        self.assertEqual(data['profile']['business_name'], "Farmer Joe")

    def test_deactivate_account_logic(self):
        """Verify account deactivation sets is_active to False."""
        self.client.login(email="buyer@test.com", password="Secure#Pass1")
        response = self.client.post(reverse('deactivate_account'))
        
        self.customer_user.refresh_from_db()
        self.assertFalse(self.customer_user.is_active)
        self.assertRedirects(response, reverse('login'))

    def test_producer_can_update_profile_data(self):
        """Test that submitting the producer_profile form actually updates the database."""
        self.client.login(email="farmer@test.com", password="Secure#Pass1")
        
        payload = {
            'form_type': 'producer_profile',
            'business_name': 'New Farm Name',
            'contact_name': 'Farmer Joe',
            'bio': 'We grow the best organic kale in Bristol.',
            'address': '1 Farm Lane',
            'postcode': 'BS1 1AA',
            'lead_time_hours': 72,
            'tax_reference': 'TAX12345',
            'vacation_mode': True
        }
        
        response = self.client.post(reverse('settings'), payload)
        
        # Check for redirect back to settings tab
        self.assertEqual(response.status_code, 302)
        self.assertIn('tab=producer_profile', response.url)
        
        # Verify the database updated
        self.producer_profile.refresh_from_db()
        self.assertEqual(self.producer_profile.business_name, "New Farm Name")
        self.assertEqual(self.producer_profile.bio, "We grow the best organic kale in Bristol.")
        self.assertTrue(self.producer_profile.vacation_mode)

    def test_customer_can_unsubscribe_via_settings(self):
        """Test that the remove_subscription view works correctly."""
        # Subscribe the customer to the producer first
        self.customer_profile.subscribed_producers.add(self.producer_profile)
        self.assertTrue(self.customer_profile.subscribed_producers.filter(id=self.producer_profile.id).exists())

        # Call the unsubscribe view
        self.client.login(email="buyer@test.com", password="Secure#Pass1")
        response = self.client.post(reverse('remove_subscription', args=[self.producer_profile.id]))
        
        # Verify they are unsubscribed
        self.assertFalse(self.customer_profile.subscribed_producers.filter(id=self.producer_profile.id).exists())
        self.assertRedirects(response, f"{reverse('settings')}?tab=customer_pref")

    def test_admin_settings_view_restriction(self):
        """Verify that an Admin only sees the Account, Security, and Privacy tabs."""
        admin_user = User.objects.create_superuser(email="admin@test.com", password="Secure#Pass1")
        self.assertEqual(admin_user.role, User.Role.ADMIN)
        self.client.login(email="admin@test.com", password="Secure#Pass1")
        
        response = self.client.get(reverse('settings'))
        
        # Should see basic tabs
        self.assertContains(response, "Account Info")
        self.assertContains(response, "Security")
        
        # Should NOT see profile-specific tabs (because Admins have no profiles)
        self.assertNotContains(response, "Business Info")
        self.assertNotContains(response, "Profile & Delivery")

    def test_invalid_form_submission_returns_errors(self):
        """Test that sending bad data (like an invalid email) doesn't save and shows errors."""
        self.client.login(email="buyer@test.com", password="Secure#Pass1")
        
        payload = {
            'form_type': 'account',
            'email': 'not-an-email', # Invalid email
            'phone': '+447911'       # Too short
        }
        
        response = self.client.post(reverse('settings'), payload)
        
        # Should stay on page (200) instead of redirecting (302) because of errors
        self.assertEqual(response.status_code, 200)
        
        # Database should not have changed
        self.customer_user.refresh_from_db()
        self.assertEqual(self.customer_user.email, "buyer@test.com")
>>>>>>> dd1ffe6be391d78d9e450c86a9b58297a8e8951a

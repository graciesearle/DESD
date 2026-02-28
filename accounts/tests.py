from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import HttpResponse

from accounts.models import ProducerProfile, CustomerProfile
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
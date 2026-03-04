from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.core.validators import MinValueValidator


# Custom User Manager

class CustomUserManager(BaseUserManager):
    
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password) 
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", CustomUser.Role.ADMIN)
        if not extra_fields.get("is_staff"):
            raise ValueError("Superuser must have is_staff=True.")
        if not extra_fields.get("is_superuser"):
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


# CustomUser Model

class CustomUser(AbstractBaseUser, PermissionsMixin):

    class Role(models.TextChoices):
        CUSTOMER          = "CUSTOMER",          "Customer"
        PRODUCER          = "PRODUCER",          "Producer"
        COMMUNITY_GROUP   = "COMMUNITY_GROUP",   "Community Group"
        RESTAURANT        = "RESTAURANT",        "Restaurant"
        ADMIN             = "ADMIN",             "Administrator"

    email       = models.EmailField(unique=True, verbose_name="Email address")
    role        = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    phone       = models.CharField(max_length=20, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)

    is_active   = models.BooleanField(default=True)
    is_staff    = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = [] 

    class Meta:
        verbose_name        = "User"
        verbose_name_plural = "Users"
        ordering            = ["-date_joined"]

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    # Role properties 
    @property
    def is_producer(self):
        return self.role == self.Role.PRODUCER

    @property
    def is_customer(self):
        return self.role in (
            self.Role.CUSTOMER,
            self.Role.COMMUNITY_GROUP,
            self.Role.RESTAURANT,
        )

    @property
    def is_community_group(self):
        return self.role == self.Role.COMMUNITY_GROUP

    @property
    def is_restaurant(self):
        return self.role == self.Role.RESTAURANT

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN


# ProducerProfile Model

class ProducerProfile(models.Model):

    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="producer_profile",
        limit_choices_to={"role": CustomUser.Role.PRODUCER},
    )

    business_name   = models.CharField(max_length=200)
    contact_name    = models.CharField(max_length=100)
    address         = models.TextField()
    postcode        = models.CharField(max_length=10)


    lead_time_hours = models.PositiveIntegerField(
        default=48,
        validators=[MinValueValidator(48)],
        help_text="Minimum hours notice required before a delivery.",
    )

    organic_certified = models.BooleanField(default=False)
    certification_body = models.CharField(
        max_length=100,
        blank=True,
        help_text="E.g. Soil Association certificate reference.",
    )

    bank_sort_code      = models.CharField(max_length=8,  blank=True)
    bank_account_number = models.CharField(max_length=20, blank=True)
    tax_reference       = models.CharField(max_length=50, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Producer Profile"
        verbose_name_plural = "Producer Profiles"

    def __str__(self):
        return f"{self.business_name} ({self.user.email})"

    @property
    def full_address(self):
        return f"{self.address}, {self.postcode}"


# CustomerProfile Model 

class CustomerProfile(models.Model):

    class CustomerType(models.TextChoices):
        INDIVIDUAL      = "INDIVIDUAL",      "Individual"
        COMMUNITY_GROUP = "COMMUNITY_GROUP", "Community Group"
        RESTAURANT      = "RESTAURANT",      "Restaurant / Café"

    user            = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="customer_profile",
    )

    full_name       = models.CharField(max_length=200)
    customer_type   = models.CharField(
        max_length=20,
        choices=CustomerType.choices,
        default=CustomerType.INDIVIDUAL,
    )
    organisation_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Required for community groups and restaurants.",
    )

    delivery_address = models.TextField()
    postcode         = models.CharField(
        max_length=10,
        help_text="Used for food-miles calculation.",
    )

    receive_surplus_alerts = models.BooleanField(
        default=True,
        help_text="Opt-in for last-minute surplus deal notifications.",
    )

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Customer Profile"
        verbose_name_plural = "Customer Profiles"

    def __str__(self):
        return f"{self.full_name} ({self.user.email})"

    @property
    def display_name(self):
        if self.organisation_name:
            return self.organisation_name
        return self.full_name

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import AuthenticationForm

from .models import ProducerProfile, CustomerProfile

User = get_user_model()

# Producer registration form
class ProducerRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput,
        help_text="Your password must meet security requirements."
    )

    class Meta:
        model = ProducerProfile
        fields = [
            "business_name",
            "contact_name",
            "address",
            "postcode",
            "lead_time_hours",
            "organic_certified",
            "certification_body",
            "bank_sort_code",
            "bank_account_number",
            "tax_reference",
        ]

    email = forms.EmailField()
    phone = forms.CharField(max_length=20)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Browser side validation for minimum lead time
        self.fields["lead_time_hours"].widget.attrs["min"] = 48
     
    def clean_lead_time_hours(self):
        lead_time = self.cleaned_data.get("lead_time_hours")

        if lead_time < 48:
            raise forms.ValidationError(
                "Lead time must be at least 48 hours."
            )

        return lead_time

    def clean_password(self):
        password = self.cleaned_data.get("password")
        validate_password(password)
        return password

    def save(self, commit=True):
        # Create the user first
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password"],
            role=User.Role.PRODUCER,
            phone=self.cleaned_data["phone"],
        )

        # Create the producer profile
        profile = super().save(commit=False)
        profile.user = user

        if commit:
            profile.save()

        return user

# Customer registration forms
class CustomerRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput,
        help_text="Your password must meet security requirements."
    )

    class Meta:
        model = CustomerProfile
        fields = [
            "full_name",
            "customer_type",
            "organisation_name",
            "delivery_address",
            "postcode",
            "receive_surplus_alerts",
        ]

    email = forms.EmailField()
    phone = forms.CharField(max_length=20)

    def clean_password(self):
        password = self.cleaned_data.get("password")
        validate_password(password)
        return password

    def save(self, commit=True):
        # Determine role based on customer_type
        customer_type = self.cleaned_data["customer_type"]

        role_map = {
            "INDIVIDUAL": User.Role.CUSTOMER,
            "COMMUNITY_GROUP": User.Role.COMMUNITY_GROUP,
            "RESTAURANT": User.Role.RESTAURANT,
        }

        role = role_map.get(customer_type, User.Role.CUSTOMER)

        # Create the user
        user = User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password"],
            role=role,
            phone=self.cleaned_data["phone"],
        )

        # Create the customer profile
        profile = super().save(commit=False)
        profile.user = user

        if commit:
            profile.save()

        return user

class CustomAuthenticationForm(AuthenticationForm):
    remember_me = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-green-600 border-gray-300 rounded'})
    )
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.forms import AuthenticationForm

from .models import ProducerProfile, CustomerProfile, CustomUser

import phonenumbers

User = get_user_model()


def validate_phone_number(phone, instance=None):
    """
    Shared utility to validate international phone format and uniqueness. Used by registration and settings forms.
    """
    if not phone:
        return phone

    try:
        parsed_number = phonenumbers.parse(phone, None)
    except phonenumbers.NumberParseException as e:
        if e.error_type == phonenumbers.NumberParseException.INVALID_COUNTRY_CODE:
            raise forms.ValidationError("Missing or invalid country code.")
        elif e.error_type == phonenumbers.NumberParseException.NOT_A_NUMBER:
            raise forms.ValidationError("The phone number contains invalid characters. Please use digits only.")
        else:
            raise forms.ValidationError("The phone format is invalid. Please use the international format (e.g., +44 7912 345678).")

    # Check if the number length is possible for that country
    if not phonenumbers.is_possible_number(parsed_number):
        reason = phonenumbers.is_possible_number_with_reason(parsed_number)
        
        if reason == phonenumbers.ValidationResult.TOO_SHORT:
            raise forms.ValidationError("This phone number is too short for the selected country.")
        elif reason == phonenumbers.ValidationResult.TOO_LONG:
            raise forms.ValidationError("This phone number is too long for the selected country.")
        else:
            raise forms.ValidationError("This phone number's length is invalid for the selected country.")

    # Check if it's a valid working number (checks prefixes/patterns)
    if not phonenumbers.is_valid_number(parsed_number):
        raise forms.ValidationError("This number is not a valid working phone number for the selected country.")

    # 4. Standardize the format to E.164 before check and save
    formatted_phone = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)

    # Check Uniqueness
    queryset = User.objects.filter(phone=formatted_phone)
    if instance and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    
    if queryset.exists():
        raise forms.ValidationError("An account with this phone number already exists.")
        
    return formatted_phone

# Producer registration form
class ProducerRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput,
        help_text="Your password must meet security requirements."
    )

    confirm_password = forms.CharField(
        widget=forms.PasswordInput,
        label="Confirm Password"
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

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean_phone(self):
        return validate_phone_number(self.cleaned_data.get('phone'))
    
    def clean_password(self):
        password = self.cleaned_data.get("password")
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match.")

        return cleaned_data

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

    confirm_password = forms.CharField(
        widget=forms.PasswordInput,
        label="Confirm Password"
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
            "receive_educational_emails",
        ]

    email = forms.EmailField()
    phone = forms.CharField(max_length=20)


    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean_phone(self):
        return validate_phone_number(self.cleaned_data.get('phone'))

    def clean_password(self):
        password = self.cleaned_data.get("password")
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', "Passwords do not match.")

        return cleaned_data

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
    username = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(attrs={'placeholder': 'you@example.com'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Password'})
    )

    remember_me = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-green-600 border-gray-300 rounded'})
    )



# ---- Settings Start: All the forms below will be for different setting tabs. ----

class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'phone']

    def clean_phone(self):
        return validate_phone_number(self.cleaned_data.get('phone'), instance=self.instance)

class ProducerProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = ProducerProfile
        fields = [
            'business_name', 'contact_name', 'bio', 
            'address', 'postcode', 'lead_time_hours', 
            'organic_certified', 'certification_body', 
            'tax_reference', 'vacation_mode'
        ]

class ProducerNotificationForm(forms.ModelForm):
    class Meta:
        model = ProducerProfile
        fields = ['notify_general']

class CustomerProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ['full_name', 'organisation_name', 'delivery_address', 'postcode']

    def __init__(self, *args, **kwargs):
        user_role = kwargs.pop('user_role', None)
        super().__init__(*args, **kwargs)
        # Only require organisation_name for certain roles
        if user_role in [User.Role.COMMUNITY_GROUP, User.Role.RESTAURANT]:
            self.fields['organisation_name'].required = True

class CustomerPreferencesForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ['receive_surplus_alerts', 'receive_educational_emails']


# ---- Settings End: All the forms above will be for different setting tabs. ----
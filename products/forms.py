import datetime

from django import forms
from django.utils import timezone

from .models import Review


_INPUT_CSS = (
    "w-full border border-gray-300 rounded-lg px-4 py-2 "
    "focus:ring-2 focus:ring-green-500 focus:border-green-500"
)


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        choices=[(5, '5'), (4, '4'), (3, '3'), (2, '2'), (1, '1')],
        coerce=int,
        widget=forms.RadioSelect(attrs={'class': 'star-rating-input'}),
        label="Rating"
    )

    class Meta:
        model = Review
        fields = ["rating", "title", "body", "is_anonymous"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "maxlength": 120,
                    "class": _INPUT_CSS,
                    "placeholder": "Summarise your experience",
                }
            ),
            "body": forms.Textarea(
                attrs={
                    "rows": 5,
                    "maxlength": 2000,
                    "class": _INPUT_CSS,
                    "placeholder": "Share quality, freshness, taste, and delivery experience.",
                }
            ),
            "is_anonymous": forms.CheckboxInput(attrs={"class": "rounded border-gray-300"}),
        }

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("Please add a short review title.")
        return title

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if len(body) < 10:
            raise forms.ValidationError("Please provide a little more detail in your review.")
        return body


class ProducerResponseForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["producer_response"]
        widgets = {
            "producer_response": forms.Textarea(
                attrs={
                    "rows": 3,
                    "maxlength": 1500,
                    "class": _INPUT_CSS,
                    "placeholder": "Reply to this customer review",
                }
            )
        }

    def clean_producer_response(self):
        response = (self.cleaned_data.get("producer_response") or "").strip()
        if not response:
            raise forms.ValidationError("Producer response cannot be empty.")
        return response


DISCOUNT_CHOICES = [
    (10, '10% off'),
    (15, '15% off'),
    (20, '20% off'),
    (25, '25% off'),
    (30, '30% off'),
    (35, '35% off'),
    (40, '40% off'),
    (45, '45% off'),
    (50, '50% off'),
]

EXPIRY_CHOICES = [
    (12, '12 hours'),
    (24, '24 hours'),
    (48, '48 hours'),
    (72, '72 hours'),
]


class SurplusDealForm(forms.Form):
    """Form for producers to create a surplus / last-minute deal on a product."""

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product


    discount_percentage = forms.TypedChoiceField(
        choices=DISCOUNT_CHOICES,
        coerce=int,
        label="Discount Percentage",
        widget=forms.Select(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-green-500 focus:border-green-500',
            'id': 'id_discount_percentage',
        }),
    )

    expiry_hours = forms.TypedChoiceField(
        choices=EXPIRY_CHOICES,
        coerce=int,
        label="Deal Duration",
        widget=forms.Select(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-green-500 focus:border-green-500',
        }),
    )

    best_before_date = forms.DateField(
        label="Best Before Date",
        help_text="Must be at least 24 hours after the deal expiry time.",
        widget=forms.DateInput(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-green-500 focus:border-green-500',
            'type': 'date',
        }),
    )

    surplus_quantity = forms.IntegerField(
        min_value=1,
        label="Surplus Quantity",
        help_text="How many items are available at this discount?",
        widget=forms.NumberInput(attrs={
            'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-green-500 focus:border-green-500',
            'min': '1',
        }),
    )

    note = forms.CharField(
        required=False,
        max_length=500,
        label="Note for Customers",
        widget=forms.Textarea(attrs={
            'rows': 3,
            'maxlength': 500,
            'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-green-500 focus:border-green-500',
            'placeholder': 'e.g. Perfect condition, must sell quickly to avoid waste',
        }),
    )

    def clean_discount_percentage(self):
        value = self.cleaned_data['discount_percentage']
        if value < 10 or value > 50:
            raise forms.ValidationError("Discount must be between 10% and 50%.")
        return value

    def clean_expiry_hours(self):
        value = self.cleaned_data['expiry_hours']
        if value not in [12, 24, 48, 72]:
            raise forms.ValidationError("Please select a valid deal duration.")
        return value

    def clean_surplus_quantity(self):
        value = self.cleaned_data['surplus_quantity']
        if self.product and value > self.product.stock_quantity:
            raise forms.ValidationError(f"Cannot exceed available stock ({self.product.stock_quantity}).")
        return value

    def clean(self):
        cleaned_data = super().clean()
        expiry_hours = cleaned_data.get('expiry_hours')
        best_before_date = cleaned_data.get('best_before_date')

        if expiry_hours and best_before_date:
            expires_at = timezone.now() + datetime.timedelta(hours=expiry_hours)
            best_before_end = datetime.datetime.combine(best_before_date, datetime.time.max)
            if timezone.is_naive(best_before_end):
                best_before_end = timezone.make_aware(best_before_end, timezone.get_current_timezone())

            if best_before_end < expires_at + datetime.timedelta(hours=24):
                self.add_error(
                    'best_before_date',
                    "Best before date must be at least 24 hours after the deal expiry time."
                )

        return cleaned_data

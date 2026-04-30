from datetime import timedelta
from django import forms
from django.utils import timezone
from orders.models import RecurringOrderTemplate


# Shared Tailwind CSS class string for form widgets
_INPUT_CSS = (
    "w-full border border-gray-300 rounded-lg px-4 py-2 "
    "focus:ring-2 focus:ring-green-500 focus:border-green-500"
)


class CheckoutForm(forms.Form):
    """
    Collects / confirms the shared delivery address and postcode.
    Per-producer delivery dates are handled by ``ProducerDeliveryForm``.
    """

    delivery_address = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": _INPUT_CSS,
            "placeholder": "Enter your delivery address",
        }),
        label="Delivery Address",
    )

    delivery_postcode = forms.CharField(
        max_length=10,
        widget=forms.TextInput(attrs={
            "class": _INPUT_CSS,
            "placeholder": "e.g. BS1 5TR",
        }),
        label="Delivery Postcode",
    )

    is_recurring = forms.BooleanField(
        required=False, 
        label="Make this a recurring order template",
        widget=forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-green-600 rounded border-gray-300'})
    )
    frequency = forms.ChoiceField(
        choices=RecurringOrderTemplate.Frequency.choices,
        required=False,
        widget=forms.Select(attrs={"class": _INPUT_CSS})
    )
    order_day = forms.TypedChoiceField(
        choices=RecurringOrderTemplate.DayOfWeek.choices,
        coerce=int, # coerce makes the selected string into an int
        required=False,
        widget=forms.Select(attrs={"class": _INPUT_CSS})
    )
    delivery_day = forms.TypedChoiceField(
        choices=RecurringOrderTemplate.DayOfWeek.choices,
        coerce=int,
        required=False,
        widget=forms.Select(attrs={"class": _INPUT_CSS})
    )

    def __init__(self, *args, max_lead_time_hours=48, **kwargs):
        # Accept dynamic max_lead_time_hours from the cart
        self.max_lead_time_hours = max_lead_time_hours
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        is_recurring = cleaned_data.get('is_recurring')
        
        if is_recurring:
            frequency = cleaned_data.get('frequency')
            order_day = cleaned_data.get('order_day')
            delivery_day = cleaned_data.get('delivery_day')

            if frequency is None or order_day is None or delivery_day is None:
                raise forms.ValidationError("Frequency, Order Day, and Delivery Day are required for recurring orders.")

            # Enforce Lead Time 
            days_diff = (delivery_day - order_day) % 7
            if days_diff == 0:
                days_diff = 7 # If same day, assume delivery is next week
            
            hours_diff = days_diff * 24
            if hours_diff < self.max_lead_time_hours:
                raise forms.ValidationError(f"Delivery day must be at least {self.max_lead_time_hours} hours after the order day due to your selected producers' requirements. You selected {hours_diff} hours.")

        return cleaned_data


class ProducerDeliveryForm(forms.Form):
    """
    Per-producer delivery date picker.

    Each producer section at checkout gets its own instance, configured
    with that producer's ``lead_time_hours`` and labelled with their
    business name.
    """

    delivery_date = forms.DateField(
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": _INPUT_CSS,
        }),
        label="Delivery Date",
    )

    special_instructions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 2,
            "class": _INPUT_CSS,
            "placeholder": "e.g. Please leave in the porch..."
        }),
        label="Special Instructions (Optional)"
    )

    def __init__(self, *args, lead_time_hours=48, producer_id=None,
                 producer_name="", **kwargs):
        # Use a per-producer prefix so multiple forms don't clash.
        if producer_id is not None:
            kwargs.setdefault("prefix", f"producer_{producer_id}")
        super().__init__(*args, **kwargs)

        self.lead_time_hours = lead_time_hours
        self.producer_id = producer_id
        self.producer_name = producer_name

        # Compute the earliest allowed date
        self.min_delivery_date = (
            timezone.now() + timedelta(hours=self.lead_time_hours)
        ).date()

        # Set the HTML min attribute so the browser enforces it too
        self.fields["delivery_date"].widget.attrs["min"] = (
            self.min_delivery_date.isoformat()
        )

    def clean_delivery_date(self):
        date = self.cleaned_data["delivery_date"]
        if date < self.min_delivery_date:
            raise forms.ValidationError(
                f"Delivery date must be at least {self.lead_time_hours} hours "
                f"from now. The earliest available date is "
                f"{self.min_delivery_date.strftime('%d %b %Y')}."
            )
        return date

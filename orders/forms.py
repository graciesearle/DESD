from datetime import timedelta

from django import forms
from django.utils import timezone


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

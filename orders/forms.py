from datetime import timedelta

from django import forms
from django.utils import timezone


class CheckoutForm(forms.Form):
    """
    Collects / confirms delivery details and a delivery date that
    respects the producer's minimum lead-time.
    """

    delivery_address = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": (
                "w-full border border-gray-300 rounded-lg px-4 py-2 "
                "focus:ring-2 focus:ring-green-500 focus:border-green-500"
            ),
            "placeholder": "Enter your delivery address",
        }),
        label="Delivery Address",
    )

    delivery_postcode = forms.CharField(
        max_length=10,
        widget=forms.TextInput(attrs={
            "class": (
                "w-full border border-gray-300 rounded-lg px-4 py-2 "
                "focus:ring-2 focus:ring-green-500 focus:border-green-500"
            ),
            "placeholder": "e.g. BS1 5TR",
        }),
        label="Delivery Postcode",
    )

    delivery_date = forms.DateField(
        widget=forms.DateInput(attrs={
            "type": "date",
            "class": (
                "w-full border border-gray-300 rounded-lg px-4 py-2 "
                "focus:ring-2 focus:ring-green-500 focus:border-green-500"
            ),
        }),
        label="Delivery Date",
    )

    def __init__(self, *args, lead_time_hours=48, **kwargs):
        super().__init__(*args, **kwargs)
        self.lead_time_hours = lead_time_hours

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

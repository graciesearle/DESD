from django import forms

from .models import Review


_INPUT_CSS = (
    "w-full border border-gray-300 rounded-lg px-4 py-2 "
    "focus:ring-2 focus:ring-green-500 focus:border-green-500"
)


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "title", "body", "is_anonymous"]
        widgets = {
            "rating": forms.NumberInput(
                attrs={
                    "min": 1,
                    "max": 5,
                    "step": 1,
                    "class": _INPUT_CSS,
                }
            ),
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

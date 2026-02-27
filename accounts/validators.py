import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

class MinimumLengthValidator:

    def __init__(self, min_length=8):
        self.min_length = min_length

    def validate(self, password, user=None):
        if len(password) < self.min_length:
            raise ValidationError(
                _(
                    "Your password must contain at least %(min_length)d characters."
                ),
                code="password_too_short",
                params={"min_length": self.min_length},
            )

    def get_help_text(self):
        return _(
            f"Your password must contain at least {self.min_length} characters."
        )


class UppercaseValidator:
    
    def validate(self, password, user=None):
        if not re.search(r"[A-Z]", password):
            raise ValidationError(
                _("Your password must contain at least one uppercase letter (A–Z)."),
                code="password_no_upper",
            )

    def get_help_text(self):
        return _("Your password must contain at least one uppercase letter.")

class LowercaseValidator:

    def validate(self, password, user=None):
        if not re.search(r"[a-z]", password):
            raise ValidationError(
                _("Your password must contain at least one lowercase letter (a–z)."),
                code="password_no_lower",
            )

    def get_help_text(self):
        return _("Your password must contain at least one lowercase letter.")

class NumberValidator:

    def validate(self, password, user=None):
        if not re.search(r"\d", password):
            raise ValidationError(
                _("Your password must contain at least one number (0–9)."),
                code="password_no_number",
            )

    def get_help_text(self):
        return _("Your password must contain at least one number.")


class SpecialCharacterValidator:

    SPECIAL_CHARS = r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]"

    def validate(self, password, user=None):
        if not re.search(self.SPECIAL_CHARS, password):
            raise ValidationError(
                _(
                    "Your password must contain at least one special character "
                    "(e.g. ! @ # $ % ^ & *)."
                ),
                code="password_no_special",
            )

    def get_help_text(self):
        return _(
            "Your password must contain at least one special character (e.g. ! @ # $ % ^ & *)."
        )


# Common-password block

COMMON_PASSWORDS = {
    "password", "password1", "password123", "PASSWORD123",
    "123456", "12345678", "qwerty", "zxcvbnm", "abc123",
    "letmein", "welcome", "2026", "dragon",
    "master", "sunshine", "princess", "admin",
    "bristol", "foodnetwork",
}

class CommonPasswordValidator:

    def validate(self, password, user=None):
        if password.lower() in COMMON_PASSWORDS:
            raise ValidationError(
                _("This password is common. Please choose a different password."),
                code="password_too_common",
            )

    def get_help_text(self):
        return _("Your password cannot be used.")

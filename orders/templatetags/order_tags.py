"""
Custom template tags for the orders app.
Centralises the status → colour mapping so it is defined once (DRY).
"""
from django import template

register = template.Library()

# Maps Order.Status values to Tailwind CSS colour classes.
STATUS_COLOURS = {
    "PENDING":    "bg-yellow-100 text-yellow-800",
    "CONFIRMED":  "bg-blue-100 text-blue-800",
    "DISPATCHED": "bg-purple-100 text-purple-800",
    "DELIVERED":  "bg-green-100 text-green-800",
    "CANCELLED":  "bg-red-100 text-red-800",
}


@register.filter
def status_colour(status):
    """Return the Tailwind badge classes for a given order status string."""
    return STATUS_COLOURS.get(status, "bg-gray-100 text-gray-800")

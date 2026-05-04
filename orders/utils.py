import stripe
from django.conf import settings
from django.urls import reverse

def generate_stripe_checkout_session(request, order):
    """Shared helper to generate a Stripe session for any given Order."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    checkout_session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'gbp',
                'product_data': {'name': f"Order {order.order_number}"},
                'unit_amount': int(order.total * 100), #Stripe uses pence
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url=request.build_absolute_uri(
            reverse('orders:payment_success')
        ) + f"?session_id={{CHECKOUT_SESSION_ID}}&order_number={order.order_number}",
        cancel_url=request.build_absolute_uri(
            reverse('orders:payment_cancel')
        ) + f"?order_number={order.order_number}",
    )
    return checkout_session.url
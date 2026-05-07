import os
import django
import json

import sys
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth import get_user_model
from products.models import Product
from ai_engineering.services.inference_client import InferenceClient

User = get_user_model()
# Assuming the user is tom@hillsidedairy.co.uk based on previous logs
user = User.objects.filter(email='tom@hillsidedairy.co.uk').first()

if not user:
    print("User not found.")
else:
    print(f"Checking for user: {user.email}")
    recent_order_items = (
        Product.objects.filter(order_items__order__customer=user)
        .values_list('name', flat=True)
        .distinct()[:5]
    )
    print(f"Recent order items found: {list(recent_order_items)}")

    if recent_order_items:
        try:
            client = InferenceClient()
            rec_result = client.recommend(recent_items=list(recent_order_items), top_n=4)
            print(f"AI Recommendation Result: {json.dumps(rec_result, indent=2)}")
        except Exception as e:
            print(f"AI Error: {e}")
    else:
        print("No recent order items found for this user.")

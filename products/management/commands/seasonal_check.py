"""
Designed to execute its logic every 24th of each month. Run by Docker Scheduler. 
It sends reminder notifications/emails to producers with a group of products set to be in season the upcoming month
"""

from collections import defaultdict
from django.core.management.base import BaseCommand
from django.utils import timezone
from products.models import Product
from orders.models import Notification

class Command(BaseCommand):
    help = "Sends a monthly planning digest 7 days before the new month starts."

    def handle(self, *args, **options):
        today = timezone.localdate()
        
        if today.day != 24:
            self.stdout.write("Not the 24th. Skipping digest.")
            return

        # Calculate the 1st of next month 
        if today.month == 12:
            next_month_date = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month_date = today.replace(month=today.month + 1, day=1)

        target_md = next_month_date.strftime('%m-%d')

        upcoming = Product.objects.filter(
            is_year_round=False,
            is_deleted=False,
            season_start=target_md,
            producer__is_active=True,
            farm__is_deleted=False
        ).select_related('producer', 'producer__producer_profile')

        if not upcoming.exists():
            self.stdout.write(f"No products starting on {target_md}")
            return

        # Group by Producer
        to_notify = defaultdict(list)
        for p in upcoming:
            to_notify[p.producer].append(p)

        # Create Notifications (Dispatching emails automatically)
        for user, products in to_notify.items():
            names = ", ".join([prod.name for prod in products])
            Notification.objects.create(
                recipient=user,
                notification_type=Notification.Type.SEASONAL_DIGEST,
                message=f"Planning Alert: Your products ({names}) are starting their season on {next_month_date.strftime('%d %B')}. Please update your stock levels!"
            )
        
        self.stdout.write(f"Digest sent to {len(to_notify)} producers.")
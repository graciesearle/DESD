from django.core.management.base import BaseCommand
from django.utils import timezone
from products.models import SurplusDeal


class Command(BaseCommand):
    help = "Deactivate expired surplus deals. Run periodically via cron or task scheduler."

    def handle(self, *args, **options):
        now = timezone.now()
        expired_deals = SurplusDeal.objects.filter(
            is_active=True,
            expires_at__lte=now,
        )
        count = expired_deals.count()

        if count == 0:
            self.stdout.write("No expired surplus deals to clean up.")
            return

        expired_deals.update(is_active=False)
        self.stdout.write(self.style.SUCCESS(
            f"Deactivated {count} expired surplus deal(s)."
        ))

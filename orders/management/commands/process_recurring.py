"""Temporary solution via schedular until camunda is integrated"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from orders.models import RecurringOrderTemplate
from orders.services.recurring_orders import generate_draft_from_template

class Command(BaseCommand):
    help = 'Generates draft orders for active recurring templates due today.'

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        
        # Find templates that are active and due today (or past due if missed)
        due_templates = RecurringOrderTemplate.objects.filter(
            is_active=True,
            next_order_date__lte=today
        )
        
        count = 0
        for template in due_templates:
            try:
                order = generate_draft_from_template(template)
                if order:
                    count += 1
                    self.stdout.write(self.style.SUCCESS(f"Generated Draft {order.order_number} for Template {template.id}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed Template {template.id}: {str(e)}"))

        self.stdout.write(self.style.SUCCESS(f"Processed {count} recurring orders."))
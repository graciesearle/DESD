from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.db import transaction

from orders.models import Order, ProducerOrder, OrderItem, Notification, RecurringOrderTemplate
from products.models import Product

def generate_draft_from_template(template_instance):
    """
    Whoever is integrating camunda into the workflow, you can call this function from a camunda worker 
    when it reaches the 'Generate Order' timer event.
    Generates a draft order instance from a template, respecting lead times, stock levels, and producer statuses.
    """
    today = timezone.localdate()

    with transaction.atomic():
        # 1. lock template first to prevent duplicate execution if two workers trigger simultaneously.
        try:
            template = RecurringOrderTemplate.objects.select_for_update().get(id=template_instance.id)
        except RecurringOrderTemplate.DoesNotExist:
            return None # Template was deleted right before execution

        # 2. Verify state after locking
        # If another worker already processed it, the date will be in the future.
        # If the user paused it, is_active will be False.
        if not template.is_active or template.next_order_date > today:
            return None 
        
        # 3. Date normalisation: if date in DB is out-of-sync, adjust it back to the correct weekday.
        days_to_align = (template.order_day - template.next_order_date.weekday()) % 7
        if days_to_align !=0:
            template.next_order_date += timedelta(days=days_to_align)

        # 4. Handle Weekly vs Fortnightly
        interval_days = 7 if template.frequency == 'WEEKLY' else 14
        
        while template.next_order_date < today: # In scenarious that the cron job or camandu has been offline for a while.
            template.next_order_date += timedelta(days=interval_days)
        
        # Calculate delivery date for this specific draft
        days_until_delivery = (template.delivery_day - template.order_day) % 7
        if days_until_delivery == 0:
            days_until_delivery = 7

        max_lead_hours = 48
        for item in template.items.all():
            try:
                lt = item.product.producer.producer_profile.lead_time_hours
                if lt > max_lead_hours:
                    max_lead_hours = lt

            except AttributeError:
                pass

        min_days_required = (max_lead_hours // 24) + (1 if max_lead_hours % 24 > 0 else 0)

        if days_until_delivery < min_days_required:
            days_until_delivery += 7

        upcoming_delivery_date = template.next_order_date + timedelta(days=days_until_delivery)

        # 5. Lock products
        product_ids = sorted(list(template.items.values_list('product_id', flat=True)))
        
        locked_products = {
            p.id: p for p in Product.objects.select_for_update().filter(id__in=product_ids)
        }

        # 6. Create the Draft Parent Order
        draft_order = Order.objects.create(
            customer=template.customer,
            status=Order.Status.DRAFT,
            delivery_address=template.delivery_address,
            delivery_postcode=template.delivery_postcode,
            commission_rate=getattr(settings, "COMMISSION_RATE", Decimal("0.05")),
            recurring_template=template
        )

        issues = []
        added_items_count = 0
        producer_orders = {} # Cache ProducerOrder instances

        # 7. Process items and validate stock using the locked rows
        for template_item in template.items.select_related('product__producer', 'product__farm'):
            product = locked_products.get(template_item.product_id)
            
            if not product:
                continue # Product hard deleted

            # Validation Checks
            if product.is_deleted or product.farm.is_deleted or not product.producer.is_active:
                issues.append(f"Removed: {product.name} (Producer/Farm no longer available).")
                continue
            if not product.is_available:
                issues.append(f"Removed: {product.name} (Currently out of season/unavailable).")
                continue
            if product.stock_quantity < template_item.quantity:
                issues.append(f"Stock Alert: {product.name} only has {product.stock_quantity} remaining (You requested {template_item.quantity}). Please adjust your draft before paying.")
            
            producer = product.producer

            # create draft sub-order for this producer
            if producer.id not in producer_orders:
                po = ProducerOrder.objects.create(
                    order=draft_order,
                    producer=producer,
                    status=ProducerOrder.Status.DRAFT,
                    delivery_date=upcoming_delivery_date,
                    commission_rate=draft_order.commission_rate
                )
                producer_orders[producer.id] = po
            
            if template_item.unit_price_at_setup and product.price != template_item.unit_price_at_setup:
                diff = product.price - template_item.unit_price_at_setup
                direction = "increased" if diff > 0 else "decreased"
                issues.append(
                    f"Price Change: {product.name} has {direction} "
                    f"from &#163;{template_item.unit_price_at_setup} to &#163;{product.price}."
                )

            # Add item snapshot
            OrderItem.objects.create(
                order=draft_order,
                producer_order=producer_orders[producer.id],
                product=product,
                product_name=product.name,
                unit_price=product.price,
                quantity=template_item.quantity,
                line_total=product.price * template_item.quantity
            )
            added_items_count += 1

        # 8. Clean up if nothing was available
        if added_items_count == 0:
            draft_order.delete()
            template.is_active = False
            template.save()
            Notification.objects.create(
                recipient=template.customer,
                notification_type=Notification.Type.RECURRING_ISSUE,
                message="Recurring Order Paused: None of your saved items are currently available."
            )
            return None

        # Calculate totals
        for po in producer_orders.values():
            po.calculate_financials()
            po.save()
            
        draft_order.calculate_financials()
        draft_order.save()

        # 9. Advance the locked template's next run date
        template.next_order_date += timedelta(days=interval_days)
        template.save()

        # 10. Dispatch Notifications
        if issues:
            msg = f"Action Required: Your draft order {draft_order.order_number} is ready to review, but needs attention:<br><br> • " + "<br> • ".join(issues)
            Notification.objects.create(
                recipient=template.customer,
                order=draft_order,
                notification_type=Notification.Type.RECURRING_ISSUE,
                message=msg
            )
        else:
            Notification.objects.create(
                recipient=template.customer,
                order=draft_order,
                notification_type=Notification.Type.RECURRING_DRAFT,
                message=f"Your upcoming recurring order {draft_order.order_number} is ready. Please review and pay by {template.get_order_day_display()}."
            )

        return draft_order
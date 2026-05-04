from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from orders.models import Order, ProducerOrder, Settlement, SettlementLine
from orders.services.settlement import resolve_settlement_window, run_weekly_settlement

User = get_user_model()


class WeeklySettlementTests(TestCase):
    def setUp(self):
        self.producer = User.objects.create(email="producer@example.com", role=User.Role.PRODUCER)
        self.customer = User.objects.create(email="customer@example.com", role=User.Role.CUSTOMER)
        self.order = Order.objects.create(
            customer=self.customer,
            order_number="ORD-123",
            subtotal=Decimal("100.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("5.00"),
            producer_payment=Decimal("95.00"),
            status=Order.Status.DELIVERED,
        )

    def test_resolve_settlement_window(self):
        # 2026-05-04 is a Monday
        as_of = date(2026, 5, 4)
        week_start, week_end = resolve_settlement_window(as_of)
        self.assertEqual(week_start, date(2026, 4, 27))
        self.assertEqual(week_end, date(2026, 5, 3))

        # 2026-05-03 is a Sunday
        as_of = date(2026, 5, 3)
        week_start, week_end = resolve_settlement_window(as_of)
        self.assertEqual(week_start, date(2026, 4, 27))
        self.assertEqual(week_end, date(2026, 5, 3))

    def test_run_weekly_settlement(self):
        # Create a delivered producer order in the target window
        # Window: 2026-04-27 (Mon) -> 2026-05-03 (Sun)
        po = ProducerOrder.objects.create(
            order=self.order,
            producer=self.producer,
            delivery_date=date(2026, 5, 1),
            subtotal=Decimal("100.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("5.00"),
            producer_payment=Decimal("95.00"),
            status=ProducerOrder.Status.DELIVERED,
        )
        # Override created_at to fit the window (timezone aware)
        po.created_at = timezone.make_aware(timezone.datetime(2026, 5, 1, 12, 0))
        po.save()

        as_of = date(2026, 5, 4)
        result = run_weekly_settlement(as_of)

        self.assertEqual(result["settlements_created"], 1)
        self.assertEqual(result["week_start"], date(2026, 4, 27))
        self.assertEqual(result["week_end"], date(2026, 5, 3))

        settlement = Settlement.objects.first()
        self.assertIsNotNone(settlement)
        self.assertEqual(settlement.net_payout, Decimal("95.00"))
        
        line = SettlementLine.objects.first()
        self.assertIsNotNone(line)
        self.assertEqual(line.producer_order, po)
        self.assertTrue(line.transfer_ref.startswith("MOCK-"))

        # Test Idempotency
        # Create a new unsettled order in the same window
        po2 = ProducerOrder.objects.create(
            order=self.order,
            producer=self.producer,
            delivery_date=date(2026, 5, 2),
            subtotal=Decimal("50.00"),
            commission_rate=Decimal("0.05"),
            commission_amount=Decimal("2.50"),
            producer_payment=Decimal("47.50"),
            status=ProducerOrder.Status.DELIVERED,
        )
        po2.created_at = timezone.make_aware(timezone.datetime(2026, 5, 2, 12, 0))
        po2.save()

        result2 = run_weekly_settlement(as_of)
        self.assertEqual(result2["settlements_created"], 0)
        self.assertEqual(len(result2["skipped_producers"]), 1)
        
        # Test Force
        result3 = run_weekly_settlement(as_of, force=True)
        self.assertEqual(result3["settlements_created"], 1)
        self.assertEqual(Settlement.objects.count(), 1)  # the previous one was deleted

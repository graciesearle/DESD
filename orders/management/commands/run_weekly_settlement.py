"""Management command to trigger a weekly settlement run.

Usage:
    python manage.py run_weekly_settlement --as-of 2026-05-04
    python manage.py run_weekly_settlement --as-of 2026-05-04 --force

The ``--as-of`` argument determines which Mon–Sun window to settle.
If omitted, defaults to today's date.

Idempotency:
    Before executing, the command checks for existing Settlement records
    matching the resolved window.  If found, it exits with a warning and
    a non-zero exit code.  Use ``--force`` to override (e.g. after
    correcting a failed run).
"""

import sys
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from orders.services.settlement import run_weekly_settlement, resolve_settlement_window


class Command(BaseCommand):
    help = (
        "Run the weekly payout settlement for the most recently completed "
        "Mon–Sun window relative to the given --as-of date."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-of",
            type=str,
            default=None,
            help="Reference date in YYYY-MM-DD format (default: today).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Override the idempotency guard and re-run settlement for producers "
                 "that already have a record in the resolved window.",
        )
        parser.add_argument(
            "--no-catch-up",
            action="store_false",
            dest="catch_up",
            default=True,
            help="Disable the 'Backlog Catch-up' mechanism. If set, only orders "
                 "created within the strict Monday-Sunday window will be settled.",
        )

    def handle(self, *args, **options):
        # Parse --as-of
        as_of_str = options["as_of"]
        if as_of_str:
            try:
                as_of_date = date.fromisoformat(as_of_str)
            except ValueError:
                raise CommandError(
                    f"Invalid date format: '{as_of_str}'. Use YYYY-MM-DD."
                )
        else:
            as_of_date = date.today()

        force = options["force"]

        # Preview
        week_start, week_end = resolve_settlement_window(as_of_date)
        self.stdout.write(
            f"Resolving settlement window: {week_start} – {week_end} "
            f"(as-of: {as_of_date}, force: {force})"
        )

        # Run
        result = run_weekly_settlement(as_of_date, force=force, catch_up=options["catch_up"])

        # Report
        created = result["settlements_created"]
        skipped = result["skipped_producers"]

        if created:
            self.stdout.write(self.style.SUCCESS(
                f"✓ {created} settlement(s) created for window "
                f"{result['week_start']} – {result['week_end']}."
            ))
            for s in result["summaries"]:
                self.stdout.write(
                    f"  Producer: {s['producer_email']} | "
                    f"Orders: {s['order_count']} | "
                    f"Payout: £{s['net_payout']}"
                )

        if skipped:
            for sk in skipped:
                self.stderr.write(self.style.WARNING(
                    f"⚠ Skipped producer {sk['producer_email']}: "
                    f"{sk.get('reason', 'settlement already exists')} "
                    f"(id={sk.get('existing_settlement_id', 'N/A')})"
                ))

        if not created and not skipped:
            self.stdout.write(self.style.NOTICE(
                "No eligible delivered orders found in the settlement window."
            ))

        # Exit non-zero if we skipped any producers (idempotency warning)
        if skipped and not force:
            self.stderr.write(self.style.WARNING(
                "Exiting with non-zero code due to skipped producers. "
                "Use --force to override."
            ))
            sys.exit(1)

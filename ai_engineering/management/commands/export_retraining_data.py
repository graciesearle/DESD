from django.core.management.base import BaseCommand
from django.utils import timezone

from ai_engineering.models import ExportJob
from ai_engineering.services.export import create_retraining_export


class Command(BaseCommand):
    help = "Export retraining data from ai_engineering inference logs."

    def add_arguments(self, parser):
        parser.add_argument("--anonymise", action="store_true", help="Anonymise producer identifiers.")

    def handle(self, *args, **options):
        anonymise = options["anonymise"]
        job = ExportJob.objects.create(
            requested_by=None,
            status=ExportJob.Status.RUNNING,
            anonymised=anonymise,
            filter_json={},
        )

        try:
            create_retraining_export(job)
        except Exception as exc:  # pragma: no cover
            job.status = ExportJob.Status.FAILED
            job.completed_at = timezone.now()
            job.error_message = str(exc)
            job.save(update_fields=["status", "completed_at", "error_message"])
            raise

        self.stdout.write(self.style.SUCCESS(f"Export complete: {job.output_path} ({job.row_count} rows)"))

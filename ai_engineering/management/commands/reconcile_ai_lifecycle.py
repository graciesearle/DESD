from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ai_engineering.models import AIModelVersion, ActiveModel
from ai_engineering.services.lifecycle_client import LifecycleClient, LifecycleClientError


class Command(BaseCommand):
    help = "Detect and optionally reconcile lifecycle drift between AAI (canonical) and DESD (mirror)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--task-profile",
            dest="task_profile",
            help="Optional task_profile filter sent to AAI model list API.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply reconciliation updates to local DESD mirror state.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with error when drift is detected.",
        )

    def handle(self, *args, **options):
        task_profile = options.get("task_profile")
        apply_changes = options.get("apply", False)
        strict = options.get("strict", False)

        client = LifecycleClient()
        try:
            payload = client.list_models(task_profile=task_profile)
        except LifecycleClientError as exc:
            raise CommandError(f"Unable to fetch canonical lifecycle state from AAI: {exc}") from exc

        remote_results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(remote_results, list):
            raise CommandError("Invalid AAI lifecycle payload: 'results' must be a list")

        remote_map = {}
        remote_active_by_model = {}
        for item in remote_results:
            if not isinstance(item, dict):
                continue
            model_name = item.get("model_name")
            model_version = item.get("model_version")
            if not model_name or not model_version:
                continue

            key = (str(model_name), str(model_version))
            remote_map[key] = item

            if bool(item.get("is_active")):
                remote_active_by_model[str(model_name)] = str(model_version)

        local_qs = AIModelVersion.objects.all()
        if task_profile:
            local_qs = local_qs.filter(manifest_json__task_profile=task_profile)
        local_models = list(local_qs)

        local_map = {(item.model_name, item.model_version): item for item in local_models}

        remote_keys = set(remote_map.keys())
        local_keys = set(local_map.keys())

        missing_local = sorted(remote_keys - local_keys)
        stale_local = sorted(local_keys - remote_keys)

        metadata_mismatch = []
        for key in sorted(remote_keys & local_keys):
            remote_item = remote_map[key]
            local_item = local_map[key]

            differences = []
            if local_item.framework != (remote_item.get("framework") or ""):
                differences.append("framework")
            if local_item.checksum != (remote_item.get("checksum") or ""):
                differences.append("checksum")
            if local_item.artifact_path != (remote_item.get("artifact_path") or ""):
                differences.append("artifact_path")

            local_task_profile = (local_item.manifest_json or {}).get("task_profile", "")
            remote_task_profile = remote_item.get("task_profile", "")
            if local_task_profile != remote_task_profile:
                differences.append("task_profile")

            if differences:
                metadata_mismatch.append((key, differences))

        model_names = {name for (name, _) in remote_keys} | {name for (name, _) in local_keys}
        active_mismatch = []
        for model_name in sorted(model_names):
            remote_active = remote_active_by_model.get(model_name)
            local_active_obj = (
                ActiveModel.objects.filter(is_active=True, model_version__model_name=model_name)
                .select_related("model_version")
                .order_by("-activated_at")
                .first()
            )
            local_active = local_active_obj.model_version.model_version if local_active_obj else None

            if remote_active != local_active:
                active_mismatch.append((model_name, local_active, remote_active))

        drift_count = len(missing_local) + len(stale_local) + len(metadata_mismatch) + len(active_mismatch)

        self.stdout.write(f"Remote models: {len(remote_keys)}")
        self.stdout.write(f"Local models: {len(local_keys)}")
        self.stdout.write(f"Missing local versions: {len(missing_local)}")
        self.stdout.write(f"Stale local versions: {len(stale_local)}")
        self.stdout.write(f"Metadata mismatches: {len(metadata_mismatch)}")
        self.stdout.write(f"Active mismatches: {len(active_mismatch)}")

        if missing_local:
            self.stdout.write("Missing local entries:")
            for model_name, model_version in missing_local:
                self.stdout.write(f"  - {model_name}:{model_version}")

        if metadata_mismatch:
            self.stdout.write("Metadata mismatch entries:")
            for (model_name, model_version), fields in metadata_mismatch:
                self.stdout.write(f"  - {model_name}:{model_version} -> {', '.join(fields)}")

        if active_mismatch:
            self.stdout.write("Active version mismatches:")
            for model_name, local_active, remote_active in active_mismatch:
                self.stdout.write(
                    f"  - {model_name}: local={local_active or 'None'} remote={remote_active or 'None'}"
                )

        if apply_changes:
            self._apply_reconciliation(remote_map, remote_active_by_model)
            self.stdout.write(self.style.SUCCESS("Applied lifecycle reconciliation updates."))

        if drift_count == 0:
            self.stdout.write(self.style.SUCCESS("No lifecycle drift detected."))
        else:
            self.stdout.write(self.style.WARNING(f"Lifecycle drift detected ({drift_count} issue(s))."))

        if strict and drift_count > 0:
            raise CommandError("Lifecycle drift detected.")

    def _apply_reconciliation(self, remote_map, remote_active_by_model):
        with transaction.atomic():
            for (model_name, model_version), item in remote_map.items():
                AIModelVersion.objects.update_or_create(
                    model_name=model_name,
                    model_version=model_version,
                    defaults={
                        "framework": item.get("framework", ""),
                        "manifest_json": item,
                        "checksum": item.get("checksum", ""),
                        "artifact_path": item.get("artifact_path", ""),
                    },
                )

            all_model_names = {
                name for (name, _) in AIModelVersion.objects.values_list("model_name", "model_version")
            }

            for model_name in all_model_names:
                remote_active_version = remote_active_by_model.get(model_name)

                if not remote_active_version:
                    ActiveModel.objects.filter(
                        is_active=True,
                        model_version__model_name=model_name,
                    ).update(is_active=False)
                    continue

                target_model = AIModelVersion.objects.filter(
                    model_name=model_name,
                    model_version=remote_active_version,
                ).first()
                if not target_model:
                    continue

                ActiveModel.objects.filter(
                    is_active=True,
                    model_version__model_name=model_name,
                ).exclude(model_version=target_model).update(is_active=False)

                already_active = ActiveModel.objects.filter(
                    is_active=True,
                    model_version=target_model,
                ).exists()
                if not already_active:
                    ActiveModel.objects.create(
                        model_version=target_model,
                        activated_by=None,
                        is_active=True,
                    )

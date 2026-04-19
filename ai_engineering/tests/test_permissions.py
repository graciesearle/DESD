from types import SimpleNamespace

from django.test import SimpleTestCase

from ai_engineering.permissions import IsAIEngineerOrAdmin, IsExportOwnerOrAdmin


class PermissionTests(SimpleTestCase):
    def _request(self, role, authenticated=True, user_id=1):
        user = SimpleNamespace(is_authenticated=authenticated, role=role, id=user_id)
        return SimpleNamespace(user=user)

    def test_ai_engineer_or_admin_permission(self):
        permission = IsAIEngineerOrAdmin()

        self.assertTrue(permission.has_permission(self._request("AI_ENGINEER"), None))
        self.assertTrue(permission.has_permission(self._request("ADMIN"), None))
        self.assertFalse(permission.has_permission(self._request("PRODUCER"), None))

    def test_export_owner_or_admin_permission(self):
        permission = IsExportOwnerOrAdmin()
        export_job = SimpleNamespace(requested_by_id=5)

        self.assertTrue(permission.has_object_permission(self._request("ADMIN", user_id=1), None, export_job))
        self.assertTrue(permission.has_object_permission(self._request("AI_ENGINEER", user_id=5), None, export_job))
        self.assertFalse(permission.has_object_permission(self._request("AI_ENGINEER", user_id=4), None, export_job))

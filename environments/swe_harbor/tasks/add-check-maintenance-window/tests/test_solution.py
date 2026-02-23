"""Tests for the Check Maintenance Windows feature."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta as td
from datetime import timezone

from django.test import TestCase
from django.utils.timezone import now

import os
import sys
sys.path.insert(0, "/app")
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()

from hc.api.models import Check
from hc.test import BaseTestCase


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class MaintenanceWindowModelTestCase(BaseTestCase):
    """Tests for the MaintenanceWindow model itself."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_model_exists(self):
        """MaintenanceWindow should be importable from hc.api.models."""
        from hc.api.models import MaintenanceWindow
        self.assertTrue(hasattr(MaintenanceWindow, "objects"))

    def test_create_window(self):
        """Can create a maintenance window linked to a check."""
        from hc.api.models import MaintenanceWindow
        start = now()
        end = now() + td(hours=2)
        w = MaintenanceWindow.objects.create(
            owner=self.check, start_at=start, end_at=end, reason="Planned outage"
        )
        self.assertIsNotNone(w.code)
        self.assertEqual(w.reason, "Planned outage")

    def test_window_has_unique_uuid(self):
        """Each window should receive a distinct UUID code."""
        from hc.api.models import MaintenanceWindow
        w1 = MaintenanceWindow.objects.create(
            owner=self.check, start_at=now(), end_at=now() + td(hours=1)
        )
        w2 = MaintenanceWindow.objects.create(
            owner=self.check, start_at=now(), end_at=now() + td(hours=2)
        )
        self.assertNotEqual(w1.code, w2.code)

    def test_default_reason_is_empty(self):
        """reason should default to an empty string."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            owner=self.check, start_at=now(), end_at=now() + td(hours=1)
        )
        self.assertEqual(w.reason, "")

    def test_to_dict_keys(self):
        """to_dict() should return all required keys."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() - td(minutes=30),
            end_at=now() + td(hours=1),
            reason="Deploy",
        )
        d = w.to_dict()
        for key in ("uuid", "start_at", "end_at", "reason", "created", "active"):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_active_true_during_window(self):
        """active should be True when now() is within start_at/end_at."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() - td(minutes=10),
            end_at=now() + td(hours=1),
        )
        self.assertTrue(w.to_dict()["active"])

    def test_to_dict_active_false_before_window(self):
        """active should be False when now() is before start_at."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() + td(hours=1),
            end_at=now() + td(hours=2),
        )
        self.assertFalse(w.to_dict()["active"])

    def test_to_dict_active_false_after_window(self):
        """active should be False when now() is past end_at."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() - td(hours=2),
            end_at=now() - td(hours=1),
        )
        self.assertFalse(w.to_dict()["active"])

    def test_to_dict_no_microseconds(self):
        """Datetime strings in to_dict() should have no microseconds."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now(),
            end_at=now() + td(hours=1),
        )
        d = w.to_dict()
        self.assertNotIn(".", d["start_at"])
        self.assertNotIn(".", d["end_at"])
        self.assertNotIn(".", d["created"])

    def test_cascade_delete(self):
        """Deleting a check should cascade to its maintenance windows."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            owner=self.check, start_at=now(), end_at=now() + td(hours=1)
        )
        self.assertEqual(MaintenanceWindow.objects.count(), 1)
        self.check.delete()
        self.assertEqual(MaintenanceWindow.objects.count(), 0)

    def test_related_name(self):
        """check.maintenance_windows should work as a reverse relation."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            owner=self.check, start_at=now(), end_at=now() + td(hours=1)
        )
        self.assertEqual(self.check.maintenance_windows.count(), 1)

    def test_ordering_newest_start_first(self):
        """MaintenanceWindows should be ordered by -start_at."""
        from hc.api.models import MaintenanceWindow
        base = now()
        MaintenanceWindow.objects.create(
            owner=self.check, start_at=base, end_at=base + td(hours=1)
        )
        later = base + td(hours=3)
        MaintenanceWindow.objects.create(
            owner=self.check, start_at=later, end_at=later + td(hours=1)
        )
        windows = list(MaintenanceWindow.objects.filter(owner=self.check))
        self.assertGreater(windows[0].start_at, windows[1].start_at)


# ---------------------------------------------------------------------------
# Check.to_dict() in_maintenance field
# ---------------------------------------------------------------------------

class CheckToDictMaintenanceTestCase(BaseTestCase):
    """Tests for the in_maintenance field in Check.to_dict()."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_in_maintenance_false_no_windows(self):
        """in_maintenance should be False when there are no windows."""
        d = self.check.to_dict()
        self.assertIn("in_maintenance", d)
        self.assertFalse(d["in_maintenance"])

    def test_in_maintenance_false_past_window(self):
        """in_maintenance should be False when all windows are in the past."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() - td(hours=3),
            end_at=now() - td(hours=1),
        )
        self.assertFalse(self.check.to_dict()["in_maintenance"])

    def test_in_maintenance_false_future_window(self):
        """in_maintenance should be False when all windows are in the future."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() + td(hours=1),
            end_at=now() + td(hours=2),
        )
        self.assertFalse(self.check.to_dict()["in_maintenance"])

    def test_in_maintenance_true_active_window(self):
        """in_maintenance should be True when an active window covers now()."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() - td(minutes=30),
            end_at=now() + td(hours=1),
        )
        self.assertTrue(self.check.to_dict()["in_maintenance"])


# ---------------------------------------------------------------------------
# POST /api/v3/checks/<uuid>/maintenance/
# ---------------------------------------------------------------------------

class CreateMaintenanceWindowApiTestCase(BaseTestCase):
    """Tests for POST /api/v3/checks/<uuid>/maintenance/"""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")
        self.url = f"/api/v3/checks/{self.check.code}/maintenance/"

    def post(self, data, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        payload = {**data, "api_key": api_key}
        return self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
        )

    def valid_payload(self, **overrides):
        base = {
            "start_at": (now() + td(hours=1)).isoformat(),
            "end_at": (now() + td(hours=3)).isoformat(),
        }
        base.update(overrides)
        return base

    def test_create_window(self):
        """POST should create a window and return 201."""
        r = self.post(self.valid_payload(reason="Upgrade"))
        self.assertEqual(r.status_code, 201)
        doc = r.json()
        self.assertEqual(doc["reason"], "Upgrade")
        self.assertIn("uuid", doc)
        self.assertIn("start_at", doc)
        self.assertIn("end_at", doc)
        self.assertIn("active", doc)
        self.assertIn("created", doc)

    def test_create_window_no_reason(self):
        """POST without reason should default reason to empty string."""
        r = self.post(self.valid_payload())
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["reason"], "")

    def test_missing_start_at(self):
        """POST without start_at should return 400."""
        r = self.post({"end_at": (now() + td(hours=2)).isoformat()})
        self.assertEqual(r.status_code, 400)
        self.assertIn("start_at", r.json()["error"].lower())

    def test_missing_end_at(self):
        """POST without end_at should return 400."""
        r = self.post({"start_at": now().isoformat()})
        self.assertEqual(r.status_code, 400)
        self.assertIn("end_at", r.json()["error"].lower())

    def test_invalid_start_at(self):
        """POST with unparseable start_at should return 400."""
        r = self.post({"start_at": "not-a-date", "end_at": now().isoformat()})
        self.assertEqual(r.status_code, 400)
        self.assertIn("start_at", r.json()["error"].lower())

    def test_invalid_end_at(self):
        """POST with unparseable end_at should return 400."""
        r = self.post({"start_at": now().isoformat(), "end_at": "not-a-date"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("end_at", r.json()["error"].lower())

    def test_end_before_start(self):
        """POST with end_at <= start_at should return 400."""
        start = now() + td(hours=2)
        end = now() + td(hours=1)
        r = self.post({"start_at": start.isoformat(), "end_at": end.isoformat()})
        self.assertEqual(r.status_code, 400)
        self.assertIn("end_at must be after start_at", r.json()["error"])

    def test_equal_start_end(self):
        """POST with end_at == start_at should return 400."""
        t = now() + td(hours=1)
        r = self.post({"start_at": t.isoformat(), "end_at": t.isoformat()})
        self.assertEqual(r.status_code, 400)

    def test_reason_too_long(self):
        """POST with reason > 200 chars should return 400."""
        r = self.post(self.valid_payload(reason="x" * 201))
        self.assertEqual(r.status_code, 400)
        self.assertIn("too long", r.json()["error"].lower())

    def test_reason_not_string(self):
        """POST with non-string reason should return 400."""
        r = self.post(self.valid_payload(reason=42))
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a string", r.json()["error"].lower())

    def test_wrong_api_key(self):
        """POST with wrong API key should return 401."""
        r = self.post(self.valid_payload(), api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_wrong_project(self):
        """POST for a check in a different project should return 403."""
        other = Check.objects.create(project=self.bobs_project, name="Bob's")
        url = f"/api/v3/checks/{other.code}/maintenance/"
        r = self.client.post(
            url,
            json.dumps({**self.valid_payload(), "api_key": "X" * 32}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_nonexistent_check(self):
        """POST for a nonexistent check UUID should return 404."""
        url = f"/api/v3/checks/{uuid.uuid4()}/maintenance/"
        r = self.client.post(
            url,
            json.dumps({**self.valid_payload(), "api_key": "X" * 32}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 404)

    def test_window_limit(self):
        """POST should return 403 when check already has 20 windows."""
        from hc.api.models import MaintenanceWindow
        base = now() + td(days=1)
        for i in range(20):
            MaintenanceWindow.objects.create(
                owner=self.check,
                start_at=base + td(hours=i),
                end_at=base + td(hours=i + 1),
            )
        r = self.post(self.valid_payload())
        self.assertEqual(r.status_code, 403)
        self.assertIn("too many", r.json()["error"].lower())


# ---------------------------------------------------------------------------
# GET /api/v3/checks/<uuid>/maintenance/
# ---------------------------------------------------------------------------

class ListMaintenanceWindowsApiTestCase(BaseTestCase):
    """Tests for GET /api/v3/checks/<uuid>/maintenance/"""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")
        self.url = f"/api/v3/checks/{self.check.code}/maintenance/"

    def get(self, params="", api_key=None):
        if api_key is None:
            api_key = "X" * 32
        url = self.url + ("?" + params if params else "")
        return self.client.get(url, HTTP_X_API_KEY=api_key)

    def test_list_empty(self):
        """GET with no windows should return an empty list."""
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["maintenance_windows"], [])

    def test_list_windows(self):
        """GET should return all windows for the check."""
        from hc.api.models import MaintenanceWindow
        base = now() + td(hours=1)
        MaintenanceWindow.objects.create(
            owner=self.check, start_at=base, end_at=base + td(hours=1)
        )
        MaintenanceWindow.objects.create(
            owner=self.check, start_at=base + td(days=1), end_at=base + td(days=1, hours=1)
        )
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["maintenance_windows"]), 2)

    def test_list_ordered_newest_start_first(self):
        """GET should return windows ordered by -start_at."""
        from hc.api.models import MaintenanceWindow
        early = now() + td(hours=1)
        late = now() + td(hours=5)
        MaintenanceWindow.objects.create(
            owner=self.check, start_at=early, end_at=early + td(hours=1)
        )
        MaintenanceWindow.objects.create(
            owner=self.check, start_at=late, end_at=late + td(hours=1)
        )
        windows = self.get().json()["maintenance_windows"]
        self.assertGreater(windows[0]["start_at"], windows[1]["start_at"])

    def test_filter_active_only(self):
        """GET with ?active=1 should return only currently-active windows."""
        from hc.api.models import MaintenanceWindow
        # Active window: now() is between start_at and end_at
        active = MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() - td(minutes=30),
            end_at=now() + td(hours=1),
        )
        # Past window
        MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() - td(hours=2),
            end_at=now() - td(hours=1),
        )
        # Future window
        MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() + td(hours=2),
            end_at=now() + td(hours=3),
        )
        r = self.get("active=1")
        windows = r.json()["maintenance_windows"]
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["uuid"], str(active.code))

    def test_wrong_api_key_returns_401(self):
        """GET with wrong API key should return 401."""
        r = self.get(api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_wrong_project_returns_403(self):
        """GET for a check in a different project should return 403."""
        other = Check.objects.create(project=self.bobs_project, name="Bob's")
        url = f"/api/v3/checks/{other.code}/maintenance/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 403)

    def test_nonexistent_check_returns_404(self):
        """GET for a nonexistent check UUID should return 404."""
        url = f"/api/v3/checks/{uuid.uuid4()}/maintenance/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 404)

    def test_cors_headers(self):
        """Response should include Access-Control-Allow-Origin: *."""
        r = self.get()
        self.assertEqual(r.get("Access-Control-Allow-Origin"), "*")

    def test_read_only_key_can_list(self):
        """A read-only API key should be able to list windows."""
        self.project.api_key_readonly = "R" * 32
        self.project.save()
        r = self.get(api_key="R" * 32)
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# DELETE /api/v3/checks/<uuid>/maintenance/<window_uuid>/
# ---------------------------------------------------------------------------

class DeleteMaintenanceWindowApiTestCase(BaseTestCase):
    """Tests for DELETE /api/v3/checks/<uuid>/maintenance/<window_code>/"""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def delete_window(self, check_code, window_code, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        url = f"/api/v3/checks/{check_code}/maintenance/{window_code}/"
        return self.client.delete(url, HTTP_X_API_KEY=api_key)

    def test_delete_window(self):
        """DELETE should remove the window and return 204."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() + td(hours=1),
            end_at=now() + td(hours=2),
        )
        r = self.delete_window(self.check.code, w.code)
        self.assertEqual(r.status_code, 204)
        self.assertFalse(MaintenanceWindow.objects.filter(pk=w.pk).exists())

    def test_delete_nonexistent_window_returns_404(self):
        """DELETE for a UUID that doesn't exist should return 404."""
        r = self.delete_window(self.check.code, uuid.uuid4())
        self.assertEqual(r.status_code, 404)

    def test_delete_wrong_check_returns_404(self):
        """DELETE for a window belonging to a different check should return 404."""
        from hc.api.models import MaintenanceWindow
        other_check = Check.objects.create(project=self.project, name="Other Check")
        w = MaintenanceWindow.objects.create(
            owner=other_check,
            start_at=now() + td(hours=1),
            end_at=now() + td(hours=2),
        )
        # Try to delete other_check's window via self.check URL
        r = self.delete_window(self.check.code, w.code)
        self.assertEqual(r.status_code, 404)

    def test_delete_wrong_api_key_returns_401(self):
        """DELETE with wrong API key should return 401."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            owner=self.check,
            start_at=now() + td(hours=1),
            end_at=now() + td(hours=2),
        )
        r = self.delete_window(self.check.code, w.code, api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_delete_wrong_project_returns_403(self):
        """DELETE for a check in a different project should return 403."""
        from hc.api.models import MaintenanceWindow
        other_check = Check.objects.create(project=self.bobs_project, name="Bob's")
        w = MaintenanceWindow.objects.create(
            owner=other_check,
            start_at=now() + td(hours=1),
            end_at=now() + td(hours=2),
        )
        r = self.delete_window(other_check.code, w.code)
        self.assertEqual(r.status_code, 403)

    def test_delete_nonexistent_check_returns_404(self):
        """DELETE against a nonexistent check UUID should return 404."""
        r = self.delete_window(uuid.uuid4(), uuid.uuid4())
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# URL routing tests
# ---------------------------------------------------------------------------

class MaintenanceWindowUrlRoutingTestCase(BaseTestCase):
    """Tests that URL routing works for all API versions."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_v1_endpoint(self):
        """The maintenance endpoint should work under /api/v1/."""
        url = f"/api/v1/checks/{self.check.code}/maintenance/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v2_endpoint(self):
        """The maintenance endpoint should work under /api/v2/."""
        url = f"/api/v2/checks/{self.check.code}/maintenance/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v3_endpoint(self):
        """The maintenance endpoint should work under /api/v3/."""
        url = f"/api/v3/checks/{self.check.code}/maintenance/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_options_returns_204_with_cors(self):
        """OPTIONS should return 204 with CORS headers."""
        url = f"/api/v3/checks/{self.check.code}/maintenance/"
        r = self.client.options(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.get("Access-Control-Allow-Origin"), "*")

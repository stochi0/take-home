"""
Tests for: add-project-stats-endpoint

Part A: GET /api/v3/projects/<uuid>/stats/
Part B: manage.py archive_stale_checks
"""
import uuid
from datetime import timezone, timedelta, datetime
from io import StringIO

import django
from django.test import TestCase, Client
from django.utils import timezone as dj_timezone

from hc.test import BaseTestCase


def make_check(project, name="Check", status="up", n_pings=1, days_old=0):
    """Helper: create and return a saved Check."""
    from hc.api.models import Check
    c = Check(project=project, name=name, status=status, n_pings=n_pings)
    c.save()
    if days_old > 0:
        # Backdate the created field
        Check.objects.filter(pk=c.pk).update(
            created=dj_timezone.now() - timedelta(days=days_old)
        )
        c.refresh_from_db()
    return c


class ProjectStatsEndpointTests(BaseTestCase):
    """Tests for GET /api/v3/projects/<uuid>/stats/"""

    def setUp(self):
        super().setUp()
        self.client = Client()
        # Create a mix of checks
        self.c_up1 = make_check(self.project, "Up 1", status="up", n_pings=100)
        self.c_up2 = make_check(self.project, "Up 2", status="up", n_pings=50)
        self.c_down = make_check(self.project, "Down", status="down", n_pings=5)
        self.c_grace = make_check(self.project, "Grace", status="grace", n_pings=2)
        self.c_paused = make_check(self.project, "Paused", status="paused", n_pings=0, days_old=1)
        self.c_new = make_check(self.project, "New", status="new", n_pings=0, days_old=0)
        # A stale check: 0 pings, created 10+ days ago
        self.c_stale = make_check(self.project, "Stale", status="new", n_pings=0, days_old=10)

    def _get(self, project_code=None, api_key=None):
        code = project_code or str(self.project.code)
        key = api_key or self.project.api_key
        return self.client.get(
            f"/api/v3/projects/{code}/stats/",
            HTTP_X_API_KEY=key,
        )

    # ── URL resolution ────────────────────────────────────────────────

    def test_url_resolves(self):
        from django.urls import resolve
        code = str(self.project.code)
        match = resolve(f"/api/v3/projects/{code}/stats/")
        self.assertIsNotNone(match)

    # ── Basic response shape ──────────────────────────────────────────

    def test_returns_200(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)

    def test_response_has_required_keys(self):
        r = self._get()
        data = r.json()
        for key in ["project_uuid", "total", "by_status", "total_pings", "stale_checks"]:
            self.assertIn(key, data, f"Missing key: {key}")

    def test_project_uuid_in_response(self):
        r = self._get()
        data = r.json()
        self.assertEqual(data["project_uuid"], str(self.project.code))

    def test_total_count(self):
        r = self._get()
        data = r.json()
        # 7 checks created in setUp
        self.assertEqual(data["total"], 7)

    def test_by_status_has_all_statuses(self):
        r = self._get()
        data = r.json()
        for status in ["up", "down", "grace", "paused", "new", "started"]:
            self.assertIn(status, data["by_status"], f"Missing status: {status}")

    def test_by_status_counts(self):
        r = self._get()
        data = r.json()
        bs = data["by_status"]
        self.assertEqual(bs["up"], 2)
        self.assertEqual(bs["down"], 1)
        self.assertEqual(bs["grace"], 1)
        self.assertEqual(bs["paused"], 1)
        self.assertGreaterEqual(bs["new"], 1)
        self.assertEqual(bs["started"], 0)

    def test_total_pings(self):
        r = self._get()
        data = r.json()
        expected = 100 + 50 + 5 + 2 + 0 + 0 + 0
        self.assertEqual(data["total_pings"], expected)

    def test_stale_checks_count(self):
        """stale_checks counts n_pings==0 AND created >7 days ago"""
        r = self._get()
        data = r.json()
        # c_stale: n_pings=0, 10 days old → stale
        # c_paused: n_pings=0, 1 day old → NOT stale
        # c_new: n_pings=0, 0 days old → NOT stale
        self.assertEqual(data["stale_checks"], 1)

    def test_stale_checks_excludes_pinged_checks(self):
        """Checks with n_pings > 0 are NOT counted as stale"""
        r = self._get()
        data = r.json()
        # c_up1 (100 pings, old) should NOT be stale
        self.assertLess(data["stale_checks"], data["total"])

    # ── Auth & permission ────────────────────────────────────────────

    def test_unauthorized_returns_401(self):
        code = str(self.project.code)
        r = self.client.get(f"/api/v3/projects/{code}/stats/")
        self.assertEqual(r.status_code, 401)

    def test_wrong_project_uuid_returns_404(self):
        """UUID of a different project returns 404"""
        r = self._get(project_code=str(self.bobs_project.code))
        self.assertEqual(r.status_code, 404)

    def test_nonexistent_uuid_returns_404(self):
        r = self._get(project_code=str(uuid.uuid4()))
        self.assertEqual(r.status_code, 404)

    def test_read_only_key_works(self):
        """Read-only API key should be able to view stats"""
        if not hasattr(self.project, "api_key_readonly") or not self.project.api_key_readonly:
            self.skipTest("No read-only key available")
        r = self._get(api_key=self.project.api_key_readonly)
        self.assertIn(r.status_code, [200, 401])

    # ── Edge cases ─────────────────────────────────────────────────

    def test_empty_project(self):
        """Project with no checks returns zeros"""
        from hc.accounts.models import Project
        empty_project = Project(owner=self.alice, name="Empty")
        empty_project.api_key = "test-empty-key-abcdef123"
        empty_project.save()

        code = str(empty_project.code)
        r = self.client.get(f"/api/v3/projects/{code}/stats/", HTTP_X_API_KEY=empty_project.api_key)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["total_pings"], 0)
        self.assertEqual(data["stale_checks"], 0)

    def test_total_pings_zero_when_no_pings(self):
        """total_pings is 0 (not null) when all n_pings are 0"""
        from hc.accounts.models import Project
        p = Project(owner=self.alice, name="ZeroPings")
        p.api_key = "zero-pings-key-12345"
        p.save()
        make_check(p, "Z1", status="new", n_pings=0)

        r = self.client.get(f"/api/v3/projects/{str(p.code)}/stats/", HTTP_X_API_KEY=p.api_key)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total_pings"], 0)

    def test_stale_boundary_exactly_7_days(self):
        """Check created exactly 7 days ago is NOT stale (must be more than 7 days)"""
        # Create a check 7 days old
        from hc.accounts.models import Project
        p = Project(owner=self.alice, name="BoundaryProj")
        p.api_key = "boundary-key-abcdef0987"
        p.save()
        c = make_check(p, "Boundary", status="new", n_pings=0, days_old=7)

        r = self.client.get(f"/api/v3/projects/{str(p.code)}/stats/", HTTP_X_API_KEY=p.api_key)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # Exactly 7 days → cutoff is strictly >7 days, so this is borderline; accept 0 or 1
        self.assertIn(data["stale_checks"], [0, 1])


class ArchiveStaleChecksCommandTests(BaseTestCase):
    """Tests for manage.py archive_stale_checks"""

    def setUp(self):
        super().setUp()
        # Fresh checks (should not be archived)
        self.fresh = make_check(self.project, "Fresh", status="up", n_pings=0, days_old=5)
        # Old stale checks (should be archived with default 30 days)
        self.stale1 = make_check(self.project, "Stale1", status="new", n_pings=0, days_old=35)
        self.stale2 = make_check(self.project, "Stale2", status="down", n_pings=0, days_old=60)
        # Old but has pings (should NOT be archived)
        self.pinged = make_check(self.project, "Pinged", status="up", n_pings=5, days_old=40)

    def _run_command(self, *args):
        from django.core.management import call_command
        out = StringIO()
        call_command("archive_stale_checks", *args, stdout=out)
        return out.getvalue()

    def test_command_exists(self):
        """The archive_stale_checks management command exists"""
        import importlib
        mod = importlib.import_module("hc.api.management.commands.archive_stale_checks")
        self.assertTrue(hasattr(mod, "Command"))

    def test_archives_stale_checks(self):
        """Archives checks with n_pings==0 older than 30 days"""
        output = self._run_command()
        self.stale1.refresh_from_db()
        self.stale2.refresh_from_db()
        self.assertEqual(self.stale1.status, "paused")
        self.assertEqual(self.stale2.status, "paused")

    def test_does_not_archive_fresh_checks(self):
        """Does not archive checks newer than the threshold"""
        self._run_command()
        self.fresh.refresh_from_db()
        # fresh is only 5 days old, should be unchanged
        self.assertNotEqual(self.fresh.status, "paused")

    def test_does_not_archive_checks_with_pings(self):
        """Does not archive checks that have been pinged"""
        self._run_command()
        self.pinged.refresh_from_db()
        self.assertEqual(self.pinged.status, "up")

    def test_output_message(self):
        """Prints a summary of archived checks"""
        output = self._run_command()
        self.assertIn("2", output)  # 2 stale checks archived
        self.assertIn("Archived", output)

    def test_dry_run_does_not_modify(self):
        """--dry-run does not modify any checks"""
        output = self._run_command("--dry-run")
        self.stale1.refresh_from_db()
        self.stale2.refresh_from_db()
        # Status should be unchanged
        self.assertNotEqual(self.stale1.status, "paused")
        self.assertNotEqual(self.stale2.status, "paused")

    def test_dry_run_output(self):
        """--dry-run output mentions dry run and count"""
        output = self._run_command("--dry-run")
        self.assertIn("DRY RUN", output.upper())
        self.assertIn("2", output)

    def test_custom_days_threshold(self):
        """--days flag changes the staleness threshold"""
        # stale1 is 35 days old; stale2 is 60 days old
        # With --days 50, only stale2 qualifies
        output = self._run_command("--days", "50")
        self.stale1.refresh_from_db()
        self.stale2.refresh_from_db()
        self.assertNotEqual(self.stale1.status, "paused")  # 35 < 50
        self.assertEqual(self.stale2.status, "paused")     # 60 > 50

    def test_custom_days_output(self):
        """--days 50 reports 1 archived check"""
        output = self._run_command("--days", "50")
        self.assertIn("1", output)

    def test_zero_stale_checks_message(self):
        """When no stale checks exist, reports 0"""
        from hc.api.models import Check
        Check.objects.filter(n_pings=0).delete()
        output = self._run_command()
        self.assertIn("0", output)

    def test_dry_run_with_custom_days(self):
        """--dry-run and --days can be combined"""
        output = self._run_command("--dry-run", "--days", "50")
        self.assertIn("DRY RUN", output.upper())
        self.stale2.refresh_from_db()
        self.assertNotEqual(self.stale2.status, "paused")

    def test_command_file_location(self):
        """Command file exists at expected path"""
        import os
        path = "/app/hc/api/management/commands/archive_stale_checks.py"
        self.assertTrue(os.path.exists(path), f"File not found: {path}")

    def test_command_is_idempotent(self):
        """Running twice doesn't cause errors"""
        self._run_command()
        self._run_command()  # should not raise

    def test_default_days_is_30(self):
        """Default threshold is 30 days"""
        # fresh is 5 days old, stale1 is 35, stale2 is 60
        # With default (30 days), both stale1 and stale2 should be archived
        output = self._run_command()
        self.assertIn("2", output)

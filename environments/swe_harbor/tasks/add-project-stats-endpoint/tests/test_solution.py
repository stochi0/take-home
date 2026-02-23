"""Tests for project stats endpoint and archive_stale_checks command."""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from pathlib import Path
import os
import sys
import uuid

sys.path.insert(0, "/app")
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client
from django.utils.timezone import now

from hc.api.models import Check
from hc.accounts.models import Project
from hc.test import BaseTestCase


def make_check(project, *, status="up", n_pings=0, days_old=0, name="Check"):
    c = Check.objects.create(project=project, name=name, status=status, n_pings=n_pings)
    if days_old:
        Check.objects.filter(pk=c.pk).update(created=now() - timedelta(days=days_old))
        c.refresh_from_db()
    return c


class ProjectStatsEndpointTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

        self.up1 = make_check(self.project, status="up", n_pings=100, name="up1")
        self.up2 = make_check(self.project, status="up", n_pings=50, name="up2")
        self.down = make_check(self.project, status="down", n_pings=5, name="down")
        self.grace = make_check(self.project, status="grace", n_pings=2, name="grace")
        self.paused = make_check(self.project, status="paused", n_pings=0, days_old=1, name="paused")
        self.new_recent = make_check(self.project, status="new", n_pings=0, name="new_recent")
        self.started = make_check(self.project, status="started", n_pings=1, name="started")
        self.stale_new = make_check(self.project, status="new", n_pings=0, days_old=10, name="stale")

    def _get(self, *, project_code=None, api_key=None):
        code = project_code or str(self.project.code)
        key = api_key if api_key is not None else self.project.api_key
        return self.client.get(f"/api/v3/projects/{code}/stats/", HTTP_X_API_KEY=key)

    def test_url_resolves(self):
        from django.urls import resolve

        match = resolve(f"/api/v3/projects/{self.project.code}/stats/")
        self.assertIsNotNone(match)

    def test_returns_200(self):
        self.assertEqual(self._get().status_code, 200)

    def test_required_keys(self):
        doc = self._get().json()
        for k in ["project_uuid", "total", "by_status", "total_pings", "stale_checks"]:
            self.assertIn(k, doc)

    def test_project_uuid(self):
        self.assertEqual(self._get().json()["project_uuid"], str(self.project.code))

    def test_total(self):
        self.assertEqual(self._get().json()["total"], 8)

    def test_by_status_has_all_keys(self):
        by_status = self._get().json()["by_status"]
        for k in ["up", "down", "grace", "paused", "new", "started"]:
            self.assertIn(k, by_status)

    def test_by_status_values(self):
        by_status = self._get().json()["by_status"]
        self.assertEqual(by_status["up"], 2)
        self.assertEqual(by_status["down"], 1)
        self.assertEqual(by_status["grace"], 1)
        self.assertEqual(by_status["paused"], 1)
        self.assertEqual(by_status["new"], 2)
        self.assertEqual(by_status["started"], 1)

    def test_total_pings(self):
        self.assertEqual(self._get().json()["total_pings"], 158)

    def test_stale_checks(self):
        self.assertEqual(self._get().json()["stale_checks"], 1)

    def test_missing_key_401(self):
        r = self.client.get(f"/api/v3/projects/{self.project.code}/stats/")
        self.assertEqual(r.status_code, 401)

    def test_wrong_key_401(self):
        r = self._get(api_key="Z" * 32)
        self.assertEqual(r.status_code, 401)

    def test_readonly_key_works(self):
        self.project.api_key_readonly = "R" * 32
        self.project.save()
        r = self._get(api_key=self.project.api_key_readonly)
        self.assertEqual(r.status_code, 200)

    def test_nonexistent_project_uuid_404(self):
        r = self._get(project_code=str(uuid.uuid4()))
        self.assertEqual(r.status_code, 404)

    def test_different_project_uuid_404(self):
        r = self._get(project_code=str(self.bobs_project.code))
        self.assertEqual(r.status_code, 404)

    def test_empty_project(self):
        empty = Project(owner=self.alice, name="Empty")
        empty.api_key = "E" * 32
        empty.save()
        r = self.client.get(f"/api/v3/projects/{empty.code}/stats/", HTTP_X_API_KEY=empty.api_key)
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["total"], 0)
        self.assertEqual(doc["total_pings"], 0)
        self.assertEqual(doc["stale_checks"], 0)

    def test_stale_boundary_under_7_days_not_stale(self):
        p = Project(owner=self.alice, name="Boundary")
        p.api_key = "B" * 32
        p.save()
        make_check(p, status="new", n_pings=0, days_old=6, name="almost-7")
        r = self.client.get(f"/api/v3/projects/{p.code}/stats/", HTTP_X_API_KEY=p.api_key)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["stale_checks"], 0)


class ArchiveStaleChecksCommandTests(BaseTestCase):
    def setUp(self):
        super().setUp()

        self.fresh_zero = make_check(self.project, status="new", n_pings=0, days_old=5, name="fresh")
        self.stale1 = make_check(self.project, status="new", n_pings=0, days_old=35, name="stale1")
        self.stale2 = make_check(self.project, status="down", n_pings=0, days_old=60, name="stale2")
        self.already_paused = make_check(
            self.project, status="paused", n_pings=0, days_old=90, name="already-paused"
        )
        self.pinged_old = make_check(self.project, status="up", n_pings=3, days_old=90, name="pinged")

    def _run(self, *args):
        out = StringIO()
        call_command("archive_stale_checks", *args, stdout=out)
        return out.getvalue()

    def test_command_file_created(self):
        p = Path("/app/hc/api/management/commands/archive_stale_checks.py")
        self.assertTrue(p.exists())

    def test_command_exists(self):
        import importlib

        mod = importlib.import_module("hc.api.management.commands.archive_stale_checks")
        self.assertTrue(hasattr(mod, "Command"))

    def test_default_days_archives_expected(self):
        out = self._run()
        self.stale1.refresh_from_db()
        self.stale2.refresh_from_db()
        self.fresh_zero.refresh_from_db()
        self.pinged_old.refresh_from_db()
        self.already_paused.refresh_from_db()

        self.assertEqual(self.stale1.status, "paused")
        self.assertEqual(self.stale2.status, "paused")
        self.assertEqual(self.fresh_zero.status, "new")
        self.assertEqual(self.pinged_old.status, "up")
        self.assertEqual(self.already_paused.status, "paused")
        self.assertIn("Archived 2 stale checks.", out)

    def test_dry_run_does_not_modify(self):
        out = self._run("--dry-run")
        self.stale1.refresh_from_db()
        self.stale2.refresh_from_db()
        self.assertEqual(self.stale1.status, "new")
        self.assertEqual(self.stale2.status, "down")
        self.assertIn("[DRY RUN] Would archive 2 stale checks.", out)

    def test_custom_days(self):
        out = self._run("--days", "50")
        self.stale1.refresh_from_db()
        self.stale2.refresh_from_db()
        self.assertEqual(self.stale1.status, "new")
        self.assertEqual(self.stale2.status, "paused")
        self.assertIn("Archived 1 stale checks.", out)

    def test_dry_run_with_custom_days(self):
        out = self._run("--dry-run", "--days", "50")
        self.stale2.refresh_from_db()
        self.assertEqual(self.stale2.status, "down")
        self.assertIn("[DRY RUN] Would archive 1 stale checks.", out)

    def test_invalid_days(self):
        with self.assertRaises(CommandError):
            self._run("--days", "0")

    def test_idempotent(self):
        first = self._run()
        second = self._run()
        self.assertIn("Archived 2 stale checks.", first)
        self.assertIn("Archived 0 stale checks.", second)

    def test_zero_stale_checks_message(self):
        Check.objects.filter(n_pings=0, status__in=["new", "down"]).update(created=now())
        out = self._run()
        self.assertIn("Archived 0 stale checks.", out)

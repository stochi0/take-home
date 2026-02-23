"""Tests for the Channel–Checks Assignment API."""
from __future__ import annotations

import json
import uuid

from django.test import TestCase

import os
import sys
sys.path.insert(0, "/app")
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()

from hc.api.models import Channel, Check
from hc.test import BaseTestCase


def make_channel(project, kind="email"):
    """Create a minimal channel for the given project."""
    return Channel.objects.create(
        project=project,
        kind=kind,
        value='{"value": "test@example.com", "up": true, "down": true}',
    )


# ---------------------------------------------------------------------------
# Channel.to_dict() — checks_count field
# ---------------------------------------------------------------------------

class ChannelToDictTestCase(BaseTestCase):
    """Tests for the checks_count field added to Channel.to_dict()."""

    def setUp(self):
        super().setUp()
        self.channel = make_channel(self.project)

    def test_to_dict_has_checks_count(self):
        """Channel.to_dict() must include 'checks_count'."""
        d = self.channel.to_dict()
        self.assertIn("checks_count", d)

    def test_checks_count_zero_when_empty(self):
        """checks_count should be 0 when no checks are assigned."""
        self.assertEqual(self.channel.to_dict()["checks_count"], 0)

    def test_checks_count_reflects_assignments(self):
        """checks_count should equal the number of assigned checks."""
        c1 = Check.objects.create(project=self.project)
        c2 = Check.objects.create(project=self.project)
        self.channel.checks.add(c1, c2)
        self.assertEqual(self.channel.to_dict()["checks_count"], 2)

    def test_to_dict_still_has_id_name_kind(self):
        """Existing fields must still be present after the change."""
        d = self.channel.to_dict()
        self.assertIn("id", d)
        self.assertIn("name", d)
        self.assertIn("kind", d)

    def test_checks_endpoint_uses_updated_to_dict(self):
        """GET /api/v3/channels/ should include checks_count in each channel."""
        r = self.client.get("/api/v3/channels/", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)
        channels = r.json()["channels"]
        for ch in channels:
            self.assertIn("checks_count", ch)


# ---------------------------------------------------------------------------
# GET /api/v3/channels/<uuid>/checks/
# ---------------------------------------------------------------------------

class ListChannelChecksTestCase(BaseTestCase):
    """Tests for GET /api/v3/channels/<uuid>/checks/"""

    def setUp(self):
        super().setUp()
        self.channel = make_channel(self.project)
        self.url = f"/api/v3/channels/{self.channel.code}/checks/"

    def get(self, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        return self.client.get(self.url, HTTP_X_API_KEY=api_key)

    def test_returns_200_empty(self):
        """GET with no assigned checks should return 200 and empty list."""
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["checks"], [])

    def test_returns_assigned_checks(self):
        """GET should return all checks assigned to the channel."""
        c1 = Check.objects.create(project=self.project, name="Alpha")
        c2 = Check.objects.create(project=self.project, name="Beta")
        self.channel.checks.add(c1, c2)
        r = self.get()
        self.assertEqual(r.status_code, 200)
        data = r.json()["checks"]
        self.assertEqual(len(data), 2)

    def test_check_dict_shape(self):
        """Each check in the response should include expected fields."""
        check = Check.objects.create(project=self.project, name="My Check")
        self.channel.checks.add(check)
        r = self.get()
        item = r.json()["checks"][0]
        for field in ("name", "status", "last_ping"):
            self.assertIn(field, item)

    def test_wrong_api_key_returns_401(self):
        """Wrong API key should return 401."""
        r = self.get(api_key="Z" * 32)
        self.assertEqual(r.status_code, 401)

    def test_missing_api_key_returns_401(self):
        """No API key should return 401."""
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 401)

    def test_wrong_project_channel_returns_403(self):
        """Channel from another project should return 403."""
        other_ch = make_channel(self.bobs_project)
        url = f"/api/v3/channels/{other_ch.code}/checks/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 403)

    def test_nonexistent_channel_returns_404(self):
        """Non-existent channel UUID should return 404."""
        url = f"/api/v3/channels/{uuid.uuid4()}/checks/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 404)

    def test_readonly_key_accepted(self):
        """A read-only API key should be able to list channel checks."""
        self.project.api_key_readonly = "R" * 32
        self.project.save()
        r = self.get(api_key="R" * 32)
        self.assertEqual(r.status_code, 200)

    def test_cors_headers_present(self):
        """Response must include Access-Control-Allow-Origin: *."""
        r = self.get()
        self.assertEqual(r.get("Access-Control-Allow-Origin"), "*")

    def test_options_returns_204(self):
        """OPTIONS preflight must return 204 with CORS headers."""
        r = self.client.options(self.url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.get("Access-Control-Allow-Origin"), "*")


# ---------------------------------------------------------------------------
# POST /api/v3/channels/<uuid>/checks/
# ---------------------------------------------------------------------------

class SetChannelChecksTestCase(BaseTestCase):
    """Tests for POST /api/v3/channels/<uuid>/checks/"""

    def setUp(self):
        super().setUp()
        self.channel = make_channel(self.project)
        self.url = f"/api/v3/channels/{self.channel.code}/checks/"

    def post(self, data, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        payload = {**data, "api_key": api_key}
        return self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
        )

    def test_assign_checks(self):
        """POST with a list of UUIDs should assign those checks."""
        c1 = Check.objects.create(project=self.project)
        c2 = Check.objects.create(project=self.project)
        r = self.post({"checks": [str(c1.code), str(c2.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["checks"]), 2)
        self.assertEqual(self.channel.checks.count(), 2)

    def test_empty_list_clears_assignments(self):
        """POST with an empty list should remove all assigned checks."""
        check = Check.objects.create(project=self.project)
        self.channel.checks.add(check)
        r = self.post({"checks": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.channel.checks.count(), 0)
        self.assertEqual(r.json()["checks"], [])

    def test_post_replaces_existing_assignments(self):
        """POST should replace (not append) the existing check set."""
        old = Check.objects.create(project=self.project, name="Old")
        self.channel.checks.add(old)
        new = Check.objects.create(project=self.project, name="New")
        r = self.post({"checks": [str(new.code)]})
        self.assertEqual(r.status_code, 200)
        assigned = list(self.channel.checks.all())
        self.assertEqual(len(assigned), 1)
        self.assertEqual(assigned[0].pk, new.pk)

    def test_response_contains_new_check_list(self):
        """POST response should include the current (updated) check list."""
        check = Check.objects.create(project=self.project, name="Alpha")
        r = self.post({"checks": [str(check.code)]})
        self.assertEqual(r.status_code, 200)
        names = [c["name"] for c in r.json()["checks"]]
        self.assertIn("Alpha", names)

    def test_missing_checks_field_returns_400(self):
        """Missing 'checks' key should return 400."""
        r = self.post({})
        self.assertEqual(r.status_code, 400)
        self.assertIn("checks", r.json()["error"].lower())

    def test_non_list_checks_returns_400(self):
        """Non-list 'checks' value should return 400."""
        r = self.post({"checks": "not-a-list"})
        self.assertEqual(r.status_code, 400)

    def test_too_many_checks_returns_400(self):
        """More than 50 entries should return 400."""
        r = self.post({"checks": [str(uuid.uuid4()) for _ in range(51)]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("too many", r.json()["error"].lower())

    def test_invalid_uuid_in_list_returns_400(self):
        """A non-UUID string in the list should return 400."""
        r = self.post({"checks": ["not-a-uuid"]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("invalid uuid", r.json()["error"].lower())

    def test_check_from_different_project_returns_400(self):
        """A UUID belonging to a different project should return 400."""
        other = Check.objects.create(project=self.bobs_project)
        r = self.post({"checks": [str(other.code)]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("check not found", r.json()["error"].lower())

    def test_nonexistent_uuid_returns_400(self):
        """A UUID that doesn't exist at all should return 400."""
        r = self.post({"checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("check not found", r.json()["error"].lower())

    def test_wrong_api_key_returns_401(self):
        """Wrong API key should return 401."""
        r = self.post({"checks": []}, api_key="Z" * 32)
        self.assertEqual(r.status_code, 401)

    def test_wrong_project_channel_returns_403(self):
        """Channel from another project should return 403."""
        other_ch = make_channel(self.bobs_project)
        url = f"/api/v3/channels/{other_ch.code}/checks/"
        r = self.client.post(
            url,
            json.dumps({"checks": [], "api_key": "X" * 32}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_nonexistent_channel_returns_404(self):
        """Non-existent channel UUID should return 404."""
        url = f"/api/v3/channels/{uuid.uuid4()}/checks/"
        r = self.client.post(
            url,
            json.dumps({"checks": [], "api_key": "X" * 32}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 404)

    def test_partial_invalid_list_not_partially_applied(self):
        """Validation errors should not partially modify the assignment."""
        good = Check.objects.create(project=self.project)
        self.channel.checks.add(good)
        # One valid, one invalid UUID in the list
        r = self.post({"checks": [str(good.code), "bad-uuid"]})
        self.assertEqual(r.status_code, 400)
        # The original assignment should be intact
        self.assertEqual(self.channel.checks.count(), 1)

    def test_checks_count_updated_after_post(self):
        """After a successful POST, Channel.to_dict()['checks_count'] should reflect new count."""
        c1 = Check.objects.create(project=self.project)
        c2 = Check.objects.create(project=self.project)
        self.post({"checks": [str(c1.code), str(c2.code)]})
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.to_dict()["checks_count"], 2)


# ---------------------------------------------------------------------------
# DELETE /api/v3/channels/<uuid>/checks/<check_uuid>/
# ---------------------------------------------------------------------------

class RemoveChannelCheckTestCase(BaseTestCase):
    """Tests for DELETE /api/v3/channels/<uuid>/checks/<check_code>/"""

    def setUp(self):
        super().setUp()
        self.channel = make_channel(self.project)

    def delete(self, channel_code, check_code, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        url = f"/api/v3/channels/{channel_code}/checks/{check_code}/"
        return self.client.delete(url, HTTP_X_API_KEY=api_key)

    def test_removes_assigned_check(self):
        """DELETE should remove the check from the channel and return 204."""
        check = Check.objects.create(project=self.project)
        self.channel.checks.add(check)
        r = self.delete(self.channel.code, check.code)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.channel.checks.count(), 0)

    def test_only_removes_targeted_check(self):
        """DELETE should remove only the targeted check, leaving others."""
        c1 = Check.objects.create(project=self.project)
        c2 = Check.objects.create(project=self.project)
        self.channel.checks.add(c1, c2)
        r = self.delete(self.channel.code, c1.code)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.channel.checks.count(), 1)
        self.assertTrue(self.channel.checks.filter(pk=c2.pk).exists())

    def test_check_not_assigned_returns_404(self):
        """DELETE for a check UUID not in the channel should return 404."""
        check = Check.objects.create(project=self.project)
        # Not added to channel
        r = self.delete(self.channel.code, check.code)
        self.assertEqual(r.status_code, 404)

    def test_nonexistent_check_returns_404(self):
        """DELETE for a completely unknown UUID should return 404."""
        r = self.delete(self.channel.code, uuid.uuid4())
        self.assertEqual(r.status_code, 404)

    def test_nonexistent_channel_returns_404(self):
        """DELETE against a non-existent channel should return 404."""
        r = self.delete(uuid.uuid4(), uuid.uuid4())
        self.assertEqual(r.status_code, 404)

    def test_wrong_project_channel_returns_403(self):
        """DELETE against a channel from another project should return 403."""
        other_ch = make_channel(self.bobs_project)
        other_check = Check.objects.create(project=self.bobs_project)
        other_ch.checks.add(other_check)
        r = self.delete(other_ch.code, other_check.code)
        self.assertEqual(r.status_code, 403)

    def test_wrong_api_key_returns_401(self):
        """Wrong API key should return 401."""
        check = Check.objects.create(project=self.project)
        self.channel.checks.add(check)
        r = self.delete(self.channel.code, check.code, api_key="Z" * 32)
        self.assertEqual(r.status_code, 401)

    def test_check_from_other_project_not_in_channel_returns_404(self):
        """A check from another project that was somehow passed should return 404."""
        other_check = Check.objects.create(project=self.bobs_project)
        # Not assigned; our channel belongs to Alice's project → lookup by code fails
        r = self.delete(self.channel.code, other_check.code)
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# URL routing
# ---------------------------------------------------------------------------

class ChannelChecksRoutingTestCase(BaseTestCase):
    """Tests that URL routes exist across API versions and behave correctly."""

    def setUp(self):
        super().setUp()
        self.channel = make_channel(self.project)

    def test_v1_get(self):
        """GET channel checks must work under /api/v1/."""
        url = f"/api/v1/channels/{self.channel.code}/checks/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v2_get(self):
        """GET channel checks must work under /api/v2/."""
        url = f"/api/v2/channels/{self.channel.code}/checks/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v3_get(self):
        """GET channel checks must work under /api/v3/."""
        url = f"/api/v3/channels/{self.channel.code}/checks/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_post_replaces_v3(self):
        """POST must be routable under /api/v3/."""
        url = f"/api/v3/channels/{self.channel.code}/checks/"
        r = self.client.post(
            url,
            json.dumps({"checks": [], "api_key": "X" * 32}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)

    def test_delete_routable_v3(self):
        """DELETE must be routable under /api/v3/."""
        check = Check.objects.create(project=self.project)
        self.channel.checks.add(check)
        url = f"/api/v3/channels/{self.channel.code}/checks/{check.code}/"
        r = self.client.delete(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 204)

    def test_options_channel_checks_returns_204(self):
        """OPTIONS on the checks collection URL should return 204 with CORS."""
        url = f"/api/v3/channels/{self.channel.code}/checks/"
        r = self.client.options(url)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.get("Access-Control-Allow-Origin"), "*")

    def test_options_channel_check_returns_204(self):
        """OPTIONS on the single-check URL should return 204 with CORS."""
        url = f"/api/v3/channels/{self.channel.code}/checks/{uuid.uuid4()}/"
        r = self.client.options(url)
        self.assertEqual(r.status_code, 204)

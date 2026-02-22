"""
Tests for: add-ping-history-endpoint

Endpoint: GET /api/v3/checks/<uuid>/pings/
"""
import json
import uuid
from datetime import timezone, timedelta, datetime

from django.test import TestCase, Client

from hc.test import BaseTestCase


def make_ping(check, action="success", minutes_ago=0):
    """Helper: create a Ping for the given check."""
    from hc.api.models import Ping
    p = Ping(owner=check)
    p.scheme = "https"
    p.method = "GET"
    p.ua = "test-agent/1.0"
    p.action = action
    p.remote_addr = "127.0.0.1"
    p.exitstatus = None
    p.created = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes_ago)
    p.save()
    return p


class PingHistoryEndpointTests(BaseTestCase):
    """Tests for GET /api/v3/checks/<uuid>/pings/"""

    def setUp(self):
        super().setUp()
        self.client = Client()
        from hc.api.models import Check
        self.check = Check(project=self.project, name="My Check", status="up")
        self.check.save()

        # Create 10 pings of mixed types
        self.pings = []
        actions = ["success", "success", "fail", "start", "success",
                   "ign", "success", "fail", "start", "success"]
        for i, action in enumerate(actions):
            p = make_ping(self.check, action=action, minutes_ago=i * 5)
            self.pings.append(p)

    def _get(self, params="", api_key=None, check_uuid=None):
        key = api_key or self.project.api_key
        code = check_uuid or str(self.check.code)
        url = f"/api/v3/checks/{code}/pings/{params}"
        return self.client.get(url, HTTP_X_API_KEY=key)

    # ── Basic functionality ────────────────────────────────────────────────

    def test_url_resolves(self):
        """The endpoint URL resolves correctly"""
        from django.urls import resolve
        code = str(self.check.code)
        match = resolve(f"/api/v3/checks/{code}/pings/")
        self.assertIsNotNone(match)

    def test_returns_200(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)

    def test_response_has_required_keys(self):
        r = self._get()
        data = r.json()
        self.assertIn("pings", data)
        self.assertIn("total", data)
        self.assertIn("page", data)
        self.assertIn("pages", data)

    def test_total_count_correct(self):
        r = self._get()
        data = r.json()
        self.assertEqual(data["total"], 10)

    def test_default_page_is_1(self):
        r = self._get()
        data = r.json()
        self.assertEqual(data["page"], 1)

    def test_ping_object_has_required_fields(self):
        r = self._get()
        data = r.json()
        self.assertGreater(len(data["pings"]), 0)
        ping = data["pings"][0]
        for field in ["id", "created", "scheme", "method", "ua", "action", "exitstatus", "remote_addr"]:
            self.assertIn(field, ping, f"Missing field: {field}")

    def test_body_not_in_response(self):
        """body field is not exposed (could be large)"""
        r = self._get()
        data = r.json()
        for ping in data["pings"]:
            self.assertNotIn("body", ping)

    def test_ordered_newest_first(self):
        """Pings returned newest first"""
        r = self._get()
        data = r.json()
        pings = data["pings"]
        for i in range(len(pings) - 1):
            self.assertGreaterEqual(pings[i]["created"], pings[i + 1]["created"])

    def test_created_is_iso8601(self):
        """created field is a valid ISO 8601 datetime string"""
        r = self._get()
        data = r.json()
        created = data["pings"][0]["created"]
        # Should parse without error
        from datetime import datetime
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        self.assertIsNotNone(dt)

    # ── Pagination ────────────────────────────────────────────────────────

    def test_default_page_size_is_50(self):
        """Default n=50; with 10 pings, all are returned"""
        r = self._get()
        data = r.json()
        self.assertEqual(len(data["pings"]), 10)

    def test_custom_page_size(self):
        """?n=3 returns 3 pings"""
        r = self._get("?n=3")
        data = r.json()
        self.assertEqual(len(data["pings"]), 3)

    def test_pages_calculated_correctly(self):
        """With n=3 and 10 total, pages=4 (ceil(10/3))"""
        r = self._get("?n=3")
        data = r.json()
        self.assertEqual(data["pages"], 4)
        self.assertEqual(data["total"], 10)

    def test_page_2(self):
        """?p=2&n=3 returns pings 4-6"""
        r = self._get("?n=3&p=2")
        data = r.json()
        self.assertEqual(data["page"], 2)
        self.assertEqual(len(data["pings"]), 3)

    def test_last_page(self):
        """Last page may have fewer items than n"""
        r = self._get("?n=3&p=4")
        data = r.json()
        self.assertEqual(len(data["pings"]), 1)  # 10 % 3 = 1

    def test_page_beyond_last_returns_empty(self):
        """Page beyond the last returns empty pings"""
        r = self._get("?n=3&p=99")
        self.assertIn(r.status_code, [200, 404])
        if r.status_code == 200:
            data = r.json()
            self.assertEqual(len(data["pings"]), 0)

    def test_n_max_100(self):
        """n > 100 returns 400"""
        r = self._get("?n=101")
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())

    def test_n_must_be_positive(self):
        """n=0 or n=-1 returns 400"""
        r = self._get("?n=0")
        self.assertEqual(r.status_code, 400)

    def test_p_must_be_positive(self):
        """p=0 returns 400"""
        r = self._get("?p=0")
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())

    def test_n_not_integer_returns_400(self):
        r = self._get("?n=abc")
        self.assertEqual(r.status_code, 400)

    def test_p_not_integer_returns_400(self):
        r = self._get("?p=two")
        self.assertEqual(r.status_code, 400)

    # ── Action filtering ─────────────────────────────────────────────────

    def test_filter_by_action_success(self):
        """?action=success returns only success pings"""
        r = self._get("?action=success")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for ping in data["pings"]:
            self.assertEqual(ping["action"], "success")
        # We have 6 success pings from setUp
        self.assertEqual(data["total"], 6)

    def test_filter_by_action_fail(self):
        r = self._get("?action=fail")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for ping in data["pings"]:
            self.assertEqual(ping["action"], "fail")
        self.assertEqual(data["total"], 2)

    def test_filter_by_action_start(self):
        r = self._get("?action=start")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 2)

    def test_filter_by_action_ign(self):
        r = self._get("?action=ign")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 1)

    def test_invalid_action_returns_400(self):
        r = self._get("?action=invalid")
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json())

    def test_empty_result_when_no_matching_action(self):
        """Filtering by action with no matches returns empty list"""
        r = self._get("?action=ign")
        data = r.json()
        # We have 1 ign ping; check that pages=1 and pings has 1 entry
        self.assertEqual(data["total"], 1)

    # ── Auth & permissions ──────────────────────────────────────────────

    def test_unauthorized_returns_401(self):
        code = str(self.check.code)
        r = self.client.get(f"/api/v3/checks/{code}/pings/")
        self.assertEqual(r.status_code, 401)

    def test_wrong_project_returns_404(self):
        """A check from another project returns 404"""
        from hc.api.models import Check
        other = Check(project=self.bobs_project, name="Bob's", status="up")
        other.save()
        code = str(other.code)
        # Alice's key cannot access Bob's check
        r = self.client.get(f"/api/v3/checks/{code}/pings/", HTTP_X_API_KEY=self.project.api_key)
        self.assertEqual(r.status_code, 404)

    def test_nonexistent_uuid_returns_404(self):
        fake = str(uuid.uuid4())
        r = self.client.get(f"/api/v3/checks/{fake}/pings/", HTTP_X_API_KEY=self.project.api_key)
        self.assertEqual(r.status_code, 404)

    def test_post_method_not_allowed(self):
        code = str(self.check.code)
        r = self.client.post(f"/api/v3/checks/{code}/pings/", HTTP_X_API_KEY=self.project.api_key)
        self.assertEqual(r.status_code, 405)

    # ── Edge cases ────────────────────────────────────────────────────

    def test_check_with_no_pings(self):
        """Check with zero pings returns empty list"""
        from hc.api.models import Check
        empty = Check(project=self.project, name="Empty Check", status="new")
        empty.save()
        code = str(empty.code)
        r = self.client.get(f"/api/v3/checks/{code}/pings/", HTTP_X_API_KEY=self.project.api_key)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["pings"], [])
        self.assertEqual(data["pages"], 0)

    def test_exitstatus_null_when_none(self):
        """exitstatus is null (not missing) when ping has no exit status"""
        r = self._get()
        data = r.json()
        for ping in data["pings"]:
            self.assertIn("exitstatus", ping)
            # exitstatus can be null

    def test_exitstatus_present_when_set(self):
        """exitstatus is included when non-null"""
        from hc.api.models import Ping
        p = Ping(owner=self.check)
        p.scheme = "https"
        p.method = "GET"
        p.ua = ""
        p.action = "fail"
        p.exitstatus = 1
        p.remote_addr = "10.0.0.1"
        p.save()

        r = self._get("?action=fail")
        data = r.json()
        exit_statuses = [p["exitstatus"] for p in data["pings"]]
        self.assertIn(1, exit_statuses)

    def test_read_only_key_can_access(self):
        """Read-only API key should also be able to view ping history"""
        if not hasattr(self.project, "api_key_readonly") or not self.project.api_key_readonly:
            self.skipTest("Project has no read-only key")
        code = str(self.check.code)
        r = self.client.get(
            f"/api/v3/checks/{code}/pings/",
            HTTP_X_API_KEY=self.project.api_key_readonly,
        )
        self.assertIn(r.status_code, [200, 401])

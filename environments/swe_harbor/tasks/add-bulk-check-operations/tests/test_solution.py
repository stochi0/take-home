"""Tests for the Bulk Check Operations feature."""
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

from hc.api.models import Check
from hc.test import BaseTestCase


# ---------------------------------------------------------------------------
# Check.merge_tags() model tests
# ---------------------------------------------------------------------------

class MergeTagsTestCase(BaseTestCase):
    """Tests for Check.merge_tags()."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_merge_tags_method_exists(self):
        """Check.merge_tags should be callable."""
        self.assertTrue(callable(getattr(self.check, "merge_tags", None)))

    def test_merge_tags_adds_to_empty(self):
        """merge_tags on a check with no tags should set them."""
        self.check.tags = ""
        self.check.save()
        self.check.merge_tags("backend api")
        self.check.refresh_from_db()
        tags = set(self.check.tags_list())
        self.assertIn("backend", tags)
        self.assertIn("api", tags)

    def test_merge_tags_adds_without_duplicates(self):
        """merge_tags should not duplicate existing tags."""
        self.check.tags = "backend"
        self.check.save()
        self.check.merge_tags("backend frontend")
        self.check.refresh_from_db()
        tags = self.check.tags_list()
        self.assertEqual(tags.count("backend"), 1)
        self.assertIn("frontend", tags)

    def test_merge_tags_preserves_existing(self):
        """merge_tags should keep tags that are not in the new set."""
        self.check.tags = "old-tag"
        self.check.save()
        self.check.merge_tags("new-tag")
        self.check.refresh_from_db()
        tags = set(self.check.tags_list())
        self.assertIn("old-tag", tags)
        self.assertIn("new-tag", tags)

    def test_merge_tags_ignores_extra_whitespace(self):
        """merge_tags should handle extra whitespace in new_tags_str."""
        self.check.tags = ""
        self.check.save()
        self.check.merge_tags("  alpha   beta  ")
        self.check.refresh_from_db()
        tags = set(self.check.tags_list())
        self.assertIn("alpha", tags)
        self.assertIn("beta", tags)

    def test_merge_tags_persists_to_db(self):
        """merge_tags should save changes to the database."""
        self.check.merge_tags("saved-tag")
        fresh = Check.objects.get(pk=self.check.pk)
        self.assertIn("saved-tag", fresh.tags_list())


# ---------------------------------------------------------------------------
# POST /api/v3/checks/bulk/pause/
# ---------------------------------------------------------------------------

class BulkPauseTestCase(BaseTestCase):
    """Tests for POST /api/v3/checks/bulk/pause/"""

    URL = "/api/v3/checks/bulk/pause/"

    def post(self, data, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        payload = {**data, "api_key": api_key}
        return self.client.post(
            self.URL,
            json.dumps(payload),
            content_type="application/json",
        )

    def test_pause_single_check(self):
        """Should pause a single active check and return paused=1."""
        check = Check.objects.create(project=self.project, status="up")
        r = self.post({"checks": [str(check.code)]})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["paused"], 1)
        self.assertEqual(doc["already_paused"], 0)
        self.assertEqual(doc["not_found"], 0)
        check.refresh_from_db()
        self.assertEqual(check.status, "paused")

    def test_pause_multiple_checks(self):
        """Should pause multiple checks in one request."""
        c1 = Check.objects.create(project=self.project, status="up")
        c2 = Check.objects.create(project=self.project, status="new")
        r = self.post({"checks": [str(c1.code), str(c2.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["paused"], 2)

    def test_already_paused_counted_separately(self):
        """Already-paused checks should go into already_paused, not paused."""
        c_active = Check.objects.create(project=self.project, status="up")
        c_paused = Check.objects.create(project=self.project, status="paused")
        r = self.post({"checks": [str(c_active.code), str(c_paused.code)]})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["paused"], 1)
        self.assertEqual(doc["already_paused"], 1)
        self.assertEqual(doc["not_found"], 0)

    def test_not_found_uuid(self):
        """A UUID that doesn't exist should be counted in not_found."""
        r = self.post({"checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["not_found"], 1)
        self.assertEqual(doc["paused"], 0)

    def test_other_project_check_counted_as_not_found(self):
        """A check from a different project should be counted in not_found."""
        other_check = Check.objects.create(project=self.bobs_project, status="up")
        r = self.post({"checks": [str(other_check.code)]})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["not_found"], 1)
        self.assertEqual(doc["paused"], 0)
        other_check.refresh_from_db()
        self.assertNotEqual(other_check.status, "paused")

    def test_mixed_checks(self):
        """Mixed valid/invalid/other-project checks should produce correct counts."""
        my_check = Check.objects.create(project=self.project, status="up")
        already_paused = Check.objects.create(project=self.project, status="paused")
        other_check = Check.objects.create(project=self.bobs_project, status="up")
        r = self.post({
            "checks": [
                str(my_check.code),
                str(already_paused.code),
                str(other_check.code),
                str(uuid.uuid4()),
            ]
        })
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["paused"], 1)
        self.assertEqual(doc["already_paused"], 1)
        self.assertEqual(doc["not_found"], 2)

    def test_missing_checks_field_returns_400(self):
        """Missing 'checks' key should return 400."""
        r = self.post({})
        self.assertEqual(r.status_code, 400)
        self.assertIn("checks", r.json()["error"].lower())

    def test_checks_not_list_returns_400(self):
        """Non-list 'checks' should return 400."""
        r = self.post({"checks": "not-a-list"})
        self.assertEqual(r.status_code, 400)

    def test_empty_checks_list_returns_400(self):
        """Empty 'checks' list should return 400."""
        r = self.post({"checks": []})
        self.assertEqual(r.status_code, 400)

    def test_too_many_checks_returns_400(self):
        """More than 50 checks should return 400."""
        r = self.post({"checks": [str(uuid.uuid4()) for _ in range(51)]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("too many", r.json()["error"].lower())

    def test_invalid_uuid_in_list_returns_400(self):
        """A non-UUID string in the list should return 400."""
        r = self.post({"checks": ["not-a-uuid"]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("invalid uuid", r.json()["error"].lower())

    def test_wrong_api_key_returns_401(self):
        """Wrong API key should return 401."""
        r = self.post({"checks": [str(uuid.uuid4())]}, api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_response_shape(self):
        """Response should have exactly paused, already_paused, not_found keys."""
        r = self.post({"checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertIn("paused", doc)
        self.assertIn("already_paused", doc)
        self.assertIn("not_found", doc)

    def test_cors_headers(self):
        """Response should include CORS headers."""
        c = Check.objects.create(project=self.project)
        r = self.post({"checks": [str(c.code)]})
        self.assertEqual(r.get("Access-Control-Allow-Origin"), "*")


# ---------------------------------------------------------------------------
# POST /api/v3/checks/bulk/resume/
# ---------------------------------------------------------------------------

class BulkResumeTestCase(BaseTestCase):
    """Tests for POST /api/v3/checks/bulk/resume/"""

    URL = "/api/v3/checks/bulk/resume/"

    def post(self, data, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        payload = {**data, "api_key": api_key}
        return self.client.post(
            self.URL,
            json.dumps(payload),
            content_type="application/json",
        )

    def test_resume_paused_check(self):
        """Should resume a paused check and return resumed=1."""
        check = Check.objects.create(project=self.project, status="paused")
        r = self.post({"checks": [str(check.code)]})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["resumed"], 1)
        self.assertEqual(doc["not_paused"], 0)
        self.assertEqual(doc["not_found"], 0)
        check.refresh_from_db()
        self.assertEqual(check.status, "new")

    def test_resume_multiple_paused(self):
        """Should resume multiple paused checks."""
        c1 = Check.objects.create(project=self.project, status="paused")
        c2 = Check.objects.create(project=self.project, status="paused")
        r = self.post({"checks": [str(c1.code), str(c2.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["resumed"], 2)

    def test_active_check_counted_as_not_paused(self):
        """An active (non-paused) check should be counted in not_paused."""
        check = Check.objects.create(project=self.project, status="up")
        r = self.post({"checks": [str(check.code)]})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["resumed"], 0)
        self.assertEqual(doc["not_paused"], 1)

    def test_new_check_counted_as_not_paused(self):
        """A check with status=new should be counted in not_paused."""
        check = Check.objects.create(project=self.project, status="new")
        r = self.post({"checks": [str(check.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["not_paused"], 1)

    def test_not_found_uuid(self):
        """A nonexistent UUID should be counted in not_found."""
        r = self.post({"checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["not_found"], 1)

    def test_other_project_check_is_not_found(self):
        """A check from a different project should appear in not_found."""
        other = Check.objects.create(project=self.bobs_project, status="paused")
        r = self.post({"checks": [str(other.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["not_found"], 1)
        other.refresh_from_db()
        self.assertEqual(other.status, "paused")

    def test_mixed_results(self):
        """Mixed paused/active/missing checks produce correct counts."""
        paused = Check.objects.create(project=self.project, status="paused")
        active = Check.objects.create(project=self.project, status="up")
        r = self.post({
            "checks": [str(paused.code), str(active.code), str(uuid.uuid4())]
        })
        doc = r.json()
        self.assertEqual(doc["resumed"], 1)
        self.assertEqual(doc["not_paused"], 1)
        self.assertEqual(doc["not_found"], 1)

    def test_missing_checks_field_returns_400(self):
        """Missing 'checks' key should return 400."""
        r = self.post({})
        self.assertEqual(r.status_code, 400)

    def test_too_many_checks_returns_400(self):
        """More than 50 checks should return 400."""
        r = self.post({"checks": [str(uuid.uuid4()) for _ in range(51)]})
        self.assertEqual(r.status_code, 400)

    def test_invalid_uuid_returns_400(self):
        """A non-UUID string in the list should return 400."""
        r = self.post({"checks": ["oops"]})
        self.assertEqual(r.status_code, 400)

    def test_wrong_api_key_returns_401(self):
        """Wrong API key should return 401."""
        r = self.post({"checks": [str(uuid.uuid4())]}, api_key="Z" * 32)
        self.assertEqual(r.status_code, 401)

    def test_response_shape(self):
        """Response should have exactly resumed, not_paused, not_found keys."""
        r = self.post({"checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertIn("resumed", doc)
        self.assertIn("not_paused", doc)
        self.assertIn("not_found", doc)


# ---------------------------------------------------------------------------
# POST /api/v3/checks/bulk/tag/
# ---------------------------------------------------------------------------

class BulkTagTestCase(BaseTestCase):
    """Tests for POST /api/v3/checks/bulk/tag/"""

    URL = "/api/v3/checks/bulk/tag/"

    def post(self, data, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        payload = {**data, "api_key": api_key}
        return self.client.post(
            self.URL,
            json.dumps(payload),
            content_type="application/json",
        )

    def test_tag_single_check(self):
        """Should add tags to a check and return updated=1."""
        check = Check.objects.create(project=self.project, tags="")
        r = self.post({"checks": [str(check.code)], "tags": "prod backend"})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertEqual(doc["updated"], 1)
        self.assertEqual(doc["not_found"], 0)
        check.refresh_from_db()
        tags = set(check.tags_list())
        self.assertIn("prod", tags)
        self.assertIn("backend", tags)

    def test_tag_multiple_checks(self):
        """Should add tags to multiple checks."""
        c1 = Check.objects.create(project=self.project, tags="")
        c2 = Check.objects.create(project=self.project, tags="existing")
        r = self.post({"checks": [str(c1.code), str(c2.code)], "tags": "new-tag"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["updated"], 2)
        c2.refresh_from_db()
        self.assertIn("existing", c2.tags_list())
        self.assertIn("new-tag", c2.tags_list())

    def test_tags_no_duplicates(self):
        """Tags already on the check should not be duplicated."""
        check = Check.objects.create(project=self.project, tags="existing")
        r = self.post({"checks": [str(check.code)], "tags": "existing"})
        self.assertEqual(r.status_code, 200)
        check.refresh_from_db()
        self.assertEqual(check.tags_list().count("existing"), 1)

    def test_not_found_uuid(self):
        """A nonexistent UUID should be counted in not_found."""
        r = self.post({"checks": [str(uuid.uuid4())], "tags": "tag1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["not_found"], 1)
        self.assertEqual(r.json()["updated"], 0)

    def test_other_project_check_is_not_found(self):
        """A check from a different project should be in not_found."""
        other = Check.objects.create(project=self.bobs_project, tags="")
        r = self.post({"checks": [str(other.code)], "tags": "hack"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["not_found"], 1)
        other.refresh_from_db()
        self.assertNotIn("hack", other.tags_list())

    def test_missing_tags_field_returns_400(self):
        """Missing 'tags' key should return 400."""
        check = Check.objects.create(project=self.project)
        r = self.post({"checks": [str(check.code)]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("tags", r.json()["error"].lower())

    def test_tags_not_string_returns_400(self):
        """Non-string 'tags' should return 400."""
        check = Check.objects.create(project=self.project)
        r = self.post({"checks": [str(check.code)], "tags": 123})
        self.assertEqual(r.status_code, 400)
        self.assertIn("string", r.json()["error"].lower())

    def test_empty_tags_returns_400(self):
        """Empty 'tags' string should return 400."""
        check = Check.objects.create(project=self.project)
        r = self.post({"checks": [str(check.code)], "tags": ""})
        self.assertEqual(r.status_code, 400)

    def test_whitespace_only_tags_returns_400(self):
        """Whitespace-only 'tags' should return 400."""
        check = Check.objects.create(project=self.project)
        r = self.post({"checks": [str(check.code)], "tags": "   "})
        self.assertEqual(r.status_code, 400)

    def test_missing_checks_field_returns_400(self):
        """Missing 'checks' key should return 400."""
        r = self.post({"tags": "prod"})
        self.assertEqual(r.status_code, 400)

    def test_too_many_checks_returns_400(self):
        """More than 50 UUIDs should return 400."""
        r = self.post({"checks": [str(uuid.uuid4()) for _ in range(51)], "tags": "x"})
        self.assertEqual(r.status_code, 400)

    def test_invalid_uuid_returns_400(self):
        """A non-UUID string in the list should return 400."""
        r = self.post({"checks": ["bad-uuid"], "tags": "tag"})
        self.assertEqual(r.status_code, 400)

    def test_wrong_api_key_returns_401(self):
        """Wrong API key should return 401."""
        r = self.post({"checks": [str(uuid.uuid4())], "tags": "t"}, api_key="Z" * 32)
        self.assertEqual(r.status_code, 401)

    def test_response_shape(self):
        """Response should have exactly updated and not_found keys."""
        r = self.post({"checks": [str(uuid.uuid4())], "tags": "tag"})
        self.assertEqual(r.status_code, 200)
        doc = r.json()
        self.assertIn("updated", doc)
        self.assertIn("not_found", doc)

    def test_cors_headers(self):
        """Response should include CORS headers."""
        r = self.post({"checks": [str(uuid.uuid4())], "tags": "t"})
        self.assertEqual(r.get("Access-Control-Allow-Origin"), "*")


# ---------------------------------------------------------------------------
# URL routing tests
# ---------------------------------------------------------------------------

class BulkOperationsUrlRoutingTestCase(BaseTestCase):
    """Tests that bulk URL routes exist and respond correctly."""

    def post(self, url, data, api_key="X" * 32):
        payload = {**data, "api_key": api_key}
        return self.client.post(
            url,
            json.dumps(payload),
            content_type="application/json",
        )

    def test_bulk_pause_v1(self):
        """Bulk pause should work under /api/v1/."""
        r = self.post("/api/v1/checks/bulk/pause/", {"checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 200)

    def test_bulk_pause_v3(self):
        """Bulk pause should work under /api/v3/."""
        r = self.post("/api/v3/checks/bulk/pause/", {"checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 200)

    def test_bulk_resume_v3(self):
        """Bulk resume should work under /api/v3/."""
        r = self.post("/api/v3/checks/bulk/resume/", {"checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 200)

    def test_bulk_tag_v3(self):
        """Bulk tag should work under /api/v3/."""
        r = self.post("/api/v3/checks/bulk/tag/", {"checks": [str(uuid.uuid4())], "tags": "x"})
        self.assertEqual(r.status_code, 200)

    def test_options_bulk_pause(self):
        """OPTIONS on bulk/pause/ should return 204 with CORS headers."""
        r = self.client.options("/api/v3/checks/bulk/pause/")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.get("Access-Control-Allow-Origin"), "*")

    def test_options_bulk_resume(self):
        """OPTIONS on bulk/resume/ should return 204 with CORS headers."""
        r = self.client.options("/api/v3/checks/bulk/resume/")
        self.assertEqual(r.status_code, 204)

    def test_options_bulk_tag(self):
        """OPTIONS on bulk/tag/ should return 204 with CORS headers."""
        r = self.client.options("/api/v3/checks/bulk/tag/")
        self.assertEqual(r.status_code, 204)

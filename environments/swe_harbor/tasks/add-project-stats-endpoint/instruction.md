# Task: Add Project Stats API Endpoint and `archive_stale` Management Command

## Background

You are working on the [Healthchecks](https://github.com/healthchecks/healthchecks) codebase (v3.6),
an open-source cron job monitoring service. The codebase is at `/app/`.

The key models are:
- `hc.api.models.Check` — a monitored job; has `status`, `project`, `name`, `last_ping`, `n_pings`, `tags`
- `hc.accounts.models.Project` — a group of checks owned by a user; has `api_key`, `api_key_readonly`

Key files you'll need to work with:
- `hc/api/views.py` — API views
- `hc/api/urls.py` — URL routing
- `hc/api/management/commands/` — existing management commands (for reference)
- `hc/api/models.py` — models

## What to Implement

This task has **two parts** that depend on each other:

---

### Part A: `GET /api/v3/projects/<project_uuid>/stats/`

Create a new API endpoint that returns aggregate statistics about all checks in a project.

**URL:** `/api/v3/projects/<project_uuid>/stats/`

**Auth:** `X-Api-Key` header. The project UUID in the URL must match the project the key belongs to.
If the UUID matches a different project, return 404.

**Response (HTTP 200):**
```json
{
  "project_uuid": "abc-123-...",
  "total": 42,
  "by_status": {
    "up": 30,
    "down": 5,
    "grace": 3,
    "paused": 2,
    "new": 2,
    "started": 0
  },
  "total_pings": 18540,
  "stale_checks": 3
}
```

Fields:
- `project_uuid`: the project's UUID as a string
- `total`: total number of checks in the project
- `by_status`: breakdown of checks by status (always include all 6 statuses, even if 0)
- `total_pings`: sum of `n_pings` across all checks in the project
- `stale_checks`: number of checks that have **never been pinged** (`n_pings == 0`) and were
  created more than 7 days ago. A check is identified as stale if `n_pings == 0`
  and `created` is more than 7 days before now.
  (The `Check` model has a `created` field — check `hc/api/models.py` to confirm.)

**Error cases:**
- `401` if the API key is missing or invalid
- `404` if the project UUID doesn't match the authenticated project

**Note:** Read-only API keys should also be able to call this endpoint.

---

### Part B: `manage.py archive_stale_checks` Management Command

Create a Django management command that finds and archives stale checks across **all** projects.

**File to create:** `hc/api/management/commands/archive_stale_checks.py`

**Behavior:**
- Find all checks where `n_pings == 0` AND `created` is more than 30 days ago
- Set their `status` to `"paused"` (this is the "archived" state)
- Print a summary: `Archived N stale checks.`
- Support a `--dry-run` flag: when passed, print what would be archived but don't
  actually modify any checks. Output for dry run: `[DRY RUN] Would archive N stale checks.`
- Support a `--days <N>` flag (default: 30) to customize the staleness threshold

**Usage:**
```bash
python manage.py archive_stale_checks              # archive checks not pinged in 30+ days
python manage.py archive_stale_checks --days 60    # use 60-day threshold
python manage.py archive_stale_checks --dry-run    # preview only
```

---

### Files to Create/Modify

| File | Action |
|------|--------|
| `hc/api/views.py` | Add `project_stats` view function |
| `hc/api/urls.py` | Add URL route for `v3/projects/<uuid:code>/stats/` |
| `hc/api/management/commands/archive_stale_checks.py` | **Create** this new file |

Do NOT modify test files or any existing management commands.

---

## Implementation Notes

- Look at existing management commands in `hc/api/management/commands/` for the pattern to follow
- The `BaseCommand` class is in `django.core.management.base`
- Use `from django.utils import timezone; now = timezone.now()` for the current time
- For the view, look at how other views use `@authorize` or `@authorize_read` decorators
- The `Check` model's `created` field is a `DateTimeField` with `auto_now_add=True`
- Use Django ORM aggregation: `from django.db.models import Sum; qs.aggregate(Sum('n_pings'))`

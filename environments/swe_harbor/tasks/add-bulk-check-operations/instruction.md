# Add Bulk Check Operations

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs.

## What to build

Add three bulk-operation API endpoints that let users pause, resume, and tag multiple checks in a single request. Also add a `merge_tags()` helper to the `Check` model that the bulk-tag endpoint relies on.

## 1. `Check.merge_tags()` method (`/app/hc/api/models.py`)

Add to the `Check` model (after `tags_list()`):

```python
def merge_tags(self, new_tags_str: str) -> None:
    """Merge new space-separated tags into existing tags without duplicates."""
    existing = set(self.tags_list())
    new = {t.strip() for t in new_tags_str.split() if t.strip()}
    merged = existing | new
    self.tags = " ".join(sorted(merged))
    self.save()
```

## 2. API endpoints (`/app/hc/api/views.py`)

All three endpoints share these rules:

- Use `@authorize` (write key required), `@cors("POST")`, and `@csrf_exempt`
- JSON body must contain `"checks"`: a non-empty array of UUID strings (max 50)
- Validation (apply in this order):
  1. Missing or non-array `checks` → `400` with `{"error": "checks must be a non-empty list"}`
  2. Empty array → `400` with `{"error": "checks must be a non-empty list"}`
  3. More than 50 entries → `400` with `{"error": "too many checks (max 50)"}`
  4. Any entry that is not a valid UUID string → `400` with `{"error": "invalid uuid: <value>"}`
- Any UUID that exists but belongs to a **different** project is silently counted as `"not_found"`.

### `POST /api/v3/checks/bulk/pause/`

Pause multiple checks.

- For each valid check UUID belonging to the authenticated project:
  - If already paused: count in `already_paused`
  - Otherwise: pause it (set `status="paused"`, `last_start=None`, `alert_after=None`, create a flip with `create_flip("paused", mark_as_processed=True)`) and count in `paused`
- Checks not found or in a different project: count in `not_found`
- Returns `200` with:
  ```json
  {"paused": N, "already_paused": N, "not_found": N}
  ```

### `POST /api/v3/checks/bulk/resume/`

Resume multiple paused checks.

- For each valid check UUID belonging to the authenticated project:
  - If not paused: count in `not_paused`
  - If paused: resume it (set `status="new"`, `last_start=None`, `last_ping=None`, `alert_after=None`, create a flip with `create_flip("new", mark_as_processed=True)`) and count in `resumed`
- Checks not found or in a different project: count in `not_found`
- Returns `200` with:
  ```json
  {"resumed": N, "not_paused": N, "not_found": N}
  ```

### `POST /api/v3/checks/bulk/tag/`

Add tags to multiple checks.

- Additional validation (after shared validation):
  - `tags` key is required; missing → `400` with `{"error": "tags is required"}`
  - `tags` must be a string → `400` with `{"error": "tags must be a string"}`
  - After stripping whitespace, `tags` must be non-empty → `400` with `{"error": "tags must not be empty"}`
- For each valid check UUID belonging to the authenticated project:
  - Call `check.merge_tags(tags_str)` to add the tags without duplicates
  - Count in `updated`
- Checks not found or in a different project: count in `not_found`
- Returns `200` with:
  ```json
  {"updated": N, "not_found": N}
  ```

## 3. URL routes (`/app/hc/api/urls.py`)

Add the following entries to `api_urls`, **before** the `checks/<uuid:code>` pattern:

```python
path("checks/bulk/pause/", views.bulk_pause, name="hc-api-bulk-pause"),
path("checks/bulk/resume/", views.bulk_resume, name="hc-api-bulk-resume"),
path("checks/bulk/tag/", views.bulk_tag, name="hc-api-bulk-tag"),
```

## Constraints

- Don't modify existing tests
- Checks belonging to a different project must be treated the same as not-found (for security)
- Follow existing patterns for decorators, error responses, etc.
- The UUID validity check should use `hc.lib.string.is_valid_uuid_string` (already importable)
- No extra database queries beyond what's necessary — fetch all matching checks in a single queryset per endpoint

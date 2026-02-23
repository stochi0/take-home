# Add Channel–Checks Assignment API

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs.

## Background

A **Channel** is an alert delivery integration (email, Slack, webhook, etc.). A channel notifies its assigned checks when those checks go down. The `Channel` model already has a `checks` ManyToManyField to `Check` (see `hc/api/models.py`), but there is currently no REST API to read or modify these assignments.

## What to build

Expose the Channel–Check assignment through three API endpoints, and enhance `Channel.to_dict()` to surface the assignment count. This touches **three files**: `hc/api/models.py`, `hc/api/views.py`, and `hc/api/urls.py`.

---

## 1. `Channel.to_dict()` (`/app/hc/api/models.py`)

Add `"checks_count"` (integer) to the returned dict so callers know how many checks a channel monitors without a separate request:

```python
def to_dict(self) -> dict:
    return {
        "id": str(self.code),
        "name": self.name,
        "kind": self.kind,
        "checks_count": self.checks.count(),
    }
```

---

## 2. API endpoints (`/app/hc/api/views.py`)

### `GET /api/v3/channels/<uuid:code>/checks/`

List all checks assigned to a channel.

- Use `@authorize_read` (read-only key accepted)
- The channel's project must match the authenticated project; return `403` if not
- Returns `{"checks": [check.to_dict(readonly=request.readonly, v=request.v) for ...]}` with status `200`
- `404` if the channel doesn't exist

### `POST /api/v3/channels/<uuid:code>/checks/`

Replace the full set of checks assigned to a channel.

- Use `@authorize` (write key required)
- JSON body: `"checks"` (required) — a list of check UUID strings; an empty list is valid and clears all assignments
- Validation (in order):
  1. Missing `checks` key or non-list value → `400` with `{"error": "checks must be a list"}`
  2. More than 50 entries → `400` with `{"error": "too many checks (max 50)"}`
  3. Any entry that is not a valid UUID string → `400` with `{"error": "invalid uuid: <value>"}`
  4. Any UUID that doesn't exist in the authenticated project → `400` with `{"error": "check not found: <uuid>"}`
- On success: call `channel.checks.set(...)` to replace the M2M set, then return `{"checks": [...]}` (the new list) with status `200`
- `403` if the channel belongs to a different project, `404` if channel doesn't exist

### `DELETE /api/v3/channels/<uuid:code>/checks/<uuid:check_code>/`

Remove a single check from a channel's assignment.

- Use `@authorize` (write key required) with `@cors("DELETE")` and `@csrf_exempt`
- Returns HTTP `204` (no body) on success
- `403` if the channel belongs to a different project
- `404` if the channel doesn't exist, or if `check_code` is not currently assigned to this channel

Wire GET/POST as a single dispatcher function `channel_checks` decorated with `@csrf_exempt` and `@cors("GET", "POST")`. The inner handlers `list_channel_checks` and `set_channel_checks` carry `@authorize_read` / `@authorize`. The DELETE handler should be a separate function `channel_check` decorated with `@cors("DELETE")`, `@csrf_exempt`, and `@authorize`.

---

## 3. URL routes (`/app/hc/api/urls.py`)

Add to the `api_urls` list (after the existing `path("channels/", views.channels)` entry):

```python
path("channels/<uuid:code>/checks/", views.channel_checks, name="hc-api-channel-checks"),
path("channels/<uuid:code>/checks/<uuid:check_code>/", views.channel_check, name="hc-api-channel-check"),
```

---

## Constraints

- Do **not** modify existing tests
- No new migrations are needed (the `checks` M2M already exists on `Channel`)
- Follow existing decorator and error-response patterns
- Use `hc.lib.string.is_valid_uuid_string` for UUID validation (already imported in `views.py`)
- An empty `checks` list in the POST body is valid and should clear all assignments
- Checks from a different project must cause a `400` error (not silent skip), for auditability

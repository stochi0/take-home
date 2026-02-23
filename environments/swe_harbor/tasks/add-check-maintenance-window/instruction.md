# Add Check Maintenance Windows

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs.

## What to build

Add a maintenance window feature to the REST API so users can schedule time intervals during which a check is considered "in maintenance." Maintenance windows suppress the urgency of status readings — during a window `in_maintenance` is `true` in the check's API response.

## 1. `MaintenanceWindow` model (`/app/hc/api/models.py`)

New model with these fields:

| Field | Type | Details |
|-------|------|---------|
| `code` | `UUIDField` | `default=uuid.uuid4, editable=False, unique=True` |
| `owner` | `ForeignKey` to `Check` | `on_delete=models.CASCADE, related_name="maintenance_windows"` |
| `start_at` | `DateTimeField` | required, no default |
| `end_at` | `DateTimeField` | required, no default |
| `reason` | `CharField` | `max_length=200, blank=True, default=""` |
| `created` | `DateTimeField` | `default=now` |

Add `to_dict()` returning:
```python
{
    "uuid": str(self.code),
    "start_at": isostring(self.start_at),
    "end_at": isostring(self.end_at),
    "reason": self.reason,
    "created": isostring(self.created),
    "active": self.start_at <= now() < self.end_at,
}
```

`Meta` class: `ordering = ["-start_at"]`.

## 2. Migration (`/app/hc/api/migrations/`)

Generate with `python manage.py makemigrations api --name maintenancewindow`.

## 3. API endpoints (`/app/hc/api/views.py`)

### `POST /api/v3/checks/<uuid:code>/maintenance/`

Create a maintenance window.

- Use `@authorize` (write key required)
- JSON body:
  - `start_at` (required): ISO 8601 datetime string
  - `end_at` (required): ISO 8601 datetime string; must be after `start_at`
  - `reason` (optional): string, max 200 chars
- Validate `start_at` is present and a valid ISO 8601 datetime; return `400` with `{"error": "invalid start_at"}` if missing or unparseable
- Validate `end_at` is present and a valid ISO 8601 datetime; return `400` with `{"error": "invalid end_at"}` if missing or unparseable
- Validate `end_at > start_at`; return `400` with `{"error": "end_at must be after start_at"}` if not
- Validate `reason` is a string if present; return `400` with `{"error": "reason is not a string"}` if not
- Validate `reason` is at most 200 chars; return `400` with `{"error": "reason is too long"}` if over
- Max 20 windows per check; return `403` with `{"error": "too many maintenance windows"}` if at limit
- Return the window JSON with status `201`
- `403` if check is in a different project
- `404` if check doesn't exist

### `GET /api/v3/checks/<uuid:code>/maintenance/`

List maintenance windows for a check.

- Use `@authorize_read`
- Returns `{"maintenance_windows": [...]}`, ordered by newest `start_at` first
- Optional query param: `active=1` — only return windows where `start_at <= now() < end_at`
- `403` if wrong project, `404` if check doesn't exist

### `DELETE /api/v3/checks/<uuid:code>/maintenance/<uuid:window_code>/`

Delete a specific maintenance window.

- Use `@authorize` (write key required) with `@cors("DELETE")` and `@csrf_exempt`
- Returns HTTP `204` (no body) on success
- `403` if check is in a different project
- `404` if check doesn't exist or window doesn't belong to the check

Wire the GET/POST as a dispatcher called `check_maintenance` decorated with `@csrf_exempt` and `@cors("GET", "POST")`. The inner functions `list_maintenance` and `create_maintenance` carry the `@authorize_read` / `@authorize` decorators respectively. The DELETE handler should be a separate function called `check_maintenance_window` decorated with `@cors("DELETE")`, `@csrf_exempt`, and `@authorize`.

## 4. URL routes (`/app/hc/api/urls.py`)

Add to the `api_urls` list:

```python
path("checks/<uuid:code>/maintenance/", views.check_maintenance, name="hc-api-maintenance"),
path("checks/<uuid:code>/maintenance/<uuid:window_code>/", views.check_maintenance_window, name="hc-api-maintenance-window"),
```

## 5. `Check.to_dict()` (`/app/hc/api/models.py`)

Add `"in_maintenance"` (boolean) to the dict. It should be `True` when any maintenance window satisfies `start_at <= now() < end_at`.

```python
result["in_maintenance"] = self.maintenance_windows.filter(
    start_at__lte=now(),
    end_at__gt=now()
).exists()
```

Insert this before the `if self.kind == "simple":` block.

## Constraints

- Don't modify existing tests
- Max 20 windows per check
- Use `isostring()` for datetime formatting (already in the codebase)
- Follow existing patterns for decorators, error responses, etc.
- The `active` boolean in `to_dict()` is computed at serialization time using `now()`

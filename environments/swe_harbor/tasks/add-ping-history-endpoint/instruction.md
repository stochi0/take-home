# Task: Add Ping History Endpoint

## Background

You are working on the [Healthchecks](https://github.com/healthchecks/healthchecks) codebase (v3.6),
an open-source cron job monitoring service. The codebase is at `/app/`.

The API lives in `hc/api/`. Key files:
- `hc/api/views.py` — view functions
- `hc/api/urls.py` — URL routing

The `Check` model (`hc/api/models.py`) has:
- `code` — UUIDField, the check's public UUID
- `project` — ForeignKey to `Project`

The `Ping` model (`hc/api/models.py`) has:
- `owner` — ForeignKey to `Check` (related_name is `"ping_set"`)
- `created` — DateTimeField, when the ping arrived
- `scheme` — CharField, e.g. `"http"`, `"https"`, `"email"`
- `method` — CharField, e.g. `"GET"`, `"POST"`
- `ua` — TextField, user agent string
- `body` — TextField (may be None/empty)
- `action` — CharField with values: `"start"`, `"success"`, `"fail"`, `"ign"`
- `exitstatus` — SmallIntegerField (may be None)
- `remote_addr` — GenericIPAddressField, the client IP

## What to Implement

### New Endpoint: `GET /api/v3/checks/<uuid>/pings/`

Create a paginated endpoint that returns the ping history for a specific check.

**Authentication:** Same as all other API endpoints — `X-Api-Key` header.

**URL:** `/api/v3/checks/<uuid>/pings/`

where `<uuid>` is the check's UUID (same format as other check endpoints).

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `n` | int | 50 | Number of results per page (max 100) |
| `p` | int | 1 | Page number (1-indexed) |
| `action` | str | (all) | Filter by action type: `start`, `success`, `fail`, `ign` |

**Response (HTTP 200):**

```json
{
  "pings": [
    {
      "id": 12345,
      "created": "2024-01-15T10:30:00+00:00",
      "scheme": "https",
      "method": "GET",
      "ua": "curl/7.88.1",
      "action": "success",
      "exitstatus": null,
      "remote_addr": "1.2.3.4"
    }
  ],
  "total": 247,
  "page": 1,
  "pages": 5
}
```

Fields:
- `pings`: array of ping objects, most recent first (ordered by `-created`)
- `total`: total count of pings matching the filter
- `page`: current page number
- `pages`: total number of pages
- `id`: the ping's database primary key
- `created`: ISO 8601 datetime
- `scheme`, `method`, `ua`, `action`, `exitstatus`, `remote_addr`: from the Ping model

**Error cases:**
- `404` if the check UUID doesn't exist or doesn't belong to the authenticated project
- `400` with `{"error": "invalid page"}` if `p` is not a positive integer
- `400` with `{"error": "invalid n"}` if `n` is not a positive integer or exceeds 100
- `400` with `{"error": "invalid action"}` if `action` is not one of the allowed values
- `401` if API key is missing/invalid

**Method restriction:** Only GET is allowed. Return 405 for other methods.

### Files to Modify

1. `hc/api/views.py` — add the new `get_pings` view function
2. `hc/api/urls.py` — add the URL route

Do NOT modify test files. Do NOT change any existing view or URL.

## Notes

- Use `order_by("-created")` for chronological ordering (newest first)
- Use Python slicing for pagination: `qs[offset:offset+n]`
- For `pages` calculation: `math.ceil(total / n)` — but if total is 0, return `pages: 0`
- The `created` datetime should be formatted as ISO 8601 with timezone: use `.isoformat()`
- `exitstatus` may be `None` — return it as `null` in JSON
- `body` should NOT be included in the response (it may be large)

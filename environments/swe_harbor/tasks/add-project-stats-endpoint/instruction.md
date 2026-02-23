# Task: Project Stats Endpoint + Stale Check Archiver Command

You are working on the Healthchecks codebase at `/app`.

## Part A: New endpoint

Add:

`GET /api/v3/projects/<uuid>/stats/`

### Requirements

- File changes:
  - `hc/api/views.py`
  - `hc/api/urls.py`
- Authentication: API key header (`X-Api-Key`), read-only keys should also work.
- The project in URL must match the authenticated project, otherwise return `404`.

### Response (`200`)
```json
{
  "project_uuid": "<uuid>",
  "total": 42,
  "by_status": {
    "up": 30,
    "down": 5,
    "grace": 3,
    "paused": 2,
    "new": 1,
    "started": 1
  },
  "total_pings": 18540,
  "stale_checks": 3
}
```

Where:
- `total`: number of checks in project.
- `by_status`: always include all 6 keys (`up`, `down`, `grace`, `paused`, `new`, `started`) even if zero.
- `total_pings`: sum of `Check.n_pings` across all project checks (`0` when empty).
- `stale_checks`: checks with `n_pings == 0` and `created` older than 7 days.

### Error cases
- Missing/wrong key -> `401`
- Wrong project UUID -> `404`

## Part B: Management command

Create:

`hc/api/management/commands/archive_stale_checks.py`

### Behavior
- Archive stale checks by setting status to `"paused"`.
- “Stale” means:
  - `n_pings == 0`
  - `created` older than threshold (`--days`, default `30`)
  - not already paused
- Flags:
  - `--dry-run` -> report only, no updates
  - `--days N` -> custom threshold, `N` must be >= 1

### Output
- Normal: `Archived N stale checks.`
- Dry run: `[DRY RUN] Would archive N stale checks.`

Do not modify tests.

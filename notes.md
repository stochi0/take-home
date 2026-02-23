## Report

### Why we’re doing this

These four tasks are designed to evaluate and train agents (including **RL training**) on **realistic Django product work** inside an existing codebase:

- Read and extend an established REST API
- Enforce **auth + project scoping** correctly (avoid data leaks)
- Implement **validation with stable error semantics** (tests depend on exact ordering/messages)
- Make safe model changes (migrations, serialization) and operational tooling (management commands)
- Handle non-trivial API behaviors (bulk ops, M2M assignment, time-window logic) without regressions

### Aim

- **End-to-end feature delivery** across model → view → URL routing → serialization → tests
- **Security-minded API design** (403 vs 404 decisions, silent “not found” behavior where required)
- **Correctness under edge cases** (invalid UUIDs, limits, cross-project references, time boundaries)
- **Maintainable integration** that follows the codebase’s existing patterns (decorators, helpers, query patterns)

### Larger goal to build these specific task environments 

- Large refactors or redesigning Healthchecks’ architecture
- New frameworks or major dependency changes

### What “done” looks like

- Each endpoint is reachable under **`/api/v3/`** via `hc/api/urls.py`
- Responses and error cases match the spec **exactly** (status codes + payloads)
- DB changes are migration-backed (when applicable)
- Work fits the existing Healthchecks idioms (decorators, `to_dict()`, `isostring()`, `now()`)

### How this becomes an RL “task” in the environment

In `environments/swe_harbor/`, each directory under `tasks/` is an **episode definition** running against the same pinned Healthchecks codebase:

- **Environment**: `environments/swe_harbor/swe_harbor.py` orchestrates a containerized run.
- **Observation** (what the agent gets): the repository + the task’s `instruction.md` (the agent does **not** get the tests).
- **Actions** (what the agent does): edits files under `/app` and runs commands to implement the spec.
- **Reward signal**: `tests/test.sh` runs pytest and writes `1` (pass) or `0` (fail) to `/logs/verifier/reward.txt`.
- **Generalization pressure**: because tests are hidden from the agent, the agent must solve from spec + codebase patterns, not from test leakage.

---

## Context

This repository is a task harness around a shared Django app (**Healthchecks v3.6**).

- **Task definitions**: `environments/swe_harbor/tasks/*`
- **Shared app codebase**: `environments/swe_harbor/environment/app/` (mounted at `/app` inside the task container)

The four tasks documented below live under:

- `environments/swe_harbor/tasks/add-project-stats-endpoint/`
- `environments/swe_harbor/tasks/add-check-maintenance-window/`
- `environments/swe_harbor/tasks/add-bulk-check-operations/`
- `environments/swe_harbor/tasks/add-channel-checks-api/`


## Environment

Healthchecks: this main app which a part of the environment where different tasks can be executed by the agent

### Main layers

- **Routing**: `environments/swe_harbor/environment/app/hc/api/urls.py`
  - `api_urls = [...]` is included under **`/api/v1/`**, **`/api/v2/`**, and **`/api/v3/`**.
  - Adding a `path(...)` to `api_urls` automatically exposes it under `/api/v3/...`.
- **Request handlers (function-based views)**: `.../hc/api/views.py`
  - Uses decorators from `hc.api.decorators`:
    - `@authorize`: requires a **write** API key
    - `@authorize_read`: accepts **read-only** keys too
    - `@cors(...)` + `@csrf_exempt`: used for API endpoints (especially POST/DELETE)
  - Views rely on request context set by auth (e.g., authenticated project, readonly flag, API version).
- **Data model & serialization**: `.../hc/api/models.py`
  - Models expose `to_dict()` used by API responses.
  - Helpers like `isostring(...)` and `now()` are used for consistent datetime formatting and “active” computations.
- **Schema changes**: `.../hc/api/migrations/`
  - New models/fields require Django migrations.
- **Operational / background-like actions**: `.../hc/api/management/commands/`
  - Management commands are invoked via `python manage.py <command> ...`.

### Cross-cutting concerns used by these tasks

- **Authentication**: API key in `X-Api-Key` header; missing/invalid keys return `401`.
- **Project scoping**:
  - Most endpoints enforce that referenced objects (checks/channels) belong to the authenticated project.
  - Depending on endpoint, “wrong project” is handled as either `403` (explicit) or `404` (conceal existence).
- **Validation patterns**:
  - UUID parsing/validation uses `hc.lib.string.is_valid_uuid_string`.
  - JSON inputs are validated in a strict order so error messages are predictable in tests.
- **Efficiency**:
  - Bulk endpoints fetch matching objects in a single queryset and then process in memory.


## Task architecture notes

### `add-project-stats-endpoint`

- **What it adds**
  - **API**: `GET /api/v3/projects/<uuid>/stats/`
  - **Mgmt command**: `archive_stale_checks` (archives stale checks by pausing them)
- **Where it fits**
  - **View**: `hc/api/views.py` implements aggregation over the project’s checks:
    - `total` checks
    - `by_status` counts (always includes: `up`, `down`, `grace`, `paused`, `new`, `started`)
    - `total_pings` as sum of `Check.n_pings`
    - `stale_checks` based on \(n\_pings == 0\) and `created` older than 7 days
  - **Routing**: `hc/api/urls.py` adds the `/projects/<uuid>/stats/` path to `api_urls`.
  - **Command**: `hc/api/management/commands/archive_stale_checks.py`
    - Applies a threshold (`--days`, default 30) and supports `--dry-run`.
- **Key design constraints**
  - **Project in URL must match authenticated project**; mismatch returns `404` (not `403`).
  - Read-only API keys must be accepted for the GET endpoint.

### `add-check-maintenance-window`

- **What it adds**
  - **Model**: `MaintenanceWindow` (time interval where a check is “in maintenance”)
  - **API**:
    - `POST /api/v3/checks/<uuid>/maintenance/` create a window
    - `GET /api/v3/checks/<uuid>/maintenance/` list windows (supports `?active=1`)
    - `DELETE /api/v3/checks/<uuid>/maintenance/<uuid>/` delete a window
  - **Check API enhancement**: `Check.to_dict()` gains `in_maintenance: bool`
- **Where it fits**
  - **Models**: `hc/api/models.py`
    - FK from `MaintenanceWindow.owner -> Check` with `related_name="maintenance_windows"`.
    - `MaintenanceWindow.to_dict()` computes `active` at serialization time with `now()`.
    - `Check.to_dict()` computes `in_maintenance` via an `exists()` query on related windows.
  - **Migration**: new migration under `hc/api/migrations/`.
  - **Views & routing**: `hc/api/views.py` + `hc/api/urls.py`
    - GET/POST share a dispatcher `check_maintenance` (CORS + csrf exempt) with inner handlers that carry `@authorize_read` / `@authorize`.
    - DELETE uses a separate handler `check_maintenance_window`.
- **Key design constraints**
  - Hard limit: **max 20** windows per check.
  - Strict validation and error strings for `start_at`, `end_at`, and `reason`.

### `add-bulk-check-operations`

- **What it adds**
  - **Model helper**: `Check.merge_tags(new_tags_str: str) -> None`
  - **Bulk API endpoints**:
    - `POST /api/v3/checks/bulk/pause/`
    - `POST /api/v3/checks/bulk/resume/`
    - `POST /api/v3/checks/bulk/tag/`
- **Where it fits**
  - **Models**: `hc/api/models.py`
    - `merge_tags` merges space-separated tags, deduplicates, sorts, and persists.
  - **Views**: `hc/api/views.py`
    - Shared request-body validation for `"checks"` (non-empty list, max 50, UUID validation).
    - Pause/resume adjust check state and create flips (`create_flip(..., mark_as_processed=True)`).
    - Tag endpoint calls `merge_tags(...)` for each found check.
  - **Routing**: `hc/api/urls.py`
    - Bulk routes must be placed **before** `checks/<uuid:code>` so they don’t get shadowed.
- **Key design constraints**
  - Checks from other projects are treated as **not found** (counted in `not_found`) instead of erroring.
  - Endpoints require **write** keys and must support CORS preflight (`OPTIONS`) due to `@cors("POST")`.

### `add-channel-checks-api`

- **What it adds**
  - **Channel API enhancement**: `Channel.to_dict()` gains `checks_count`
  - **Channel–Check assignment API**:
    - `GET /api/v3/channels/<uuid>/checks/` list assigned checks
    - `POST /api/v3/channels/<uuid>/checks/` replace assigned checks set
    - `DELETE /api/v3/channels/<uuid>/checks/<uuid>/` remove a single check
- **Where it fits**
  - **Models**: `hc/api/models.py`
    - `Channel.checks` is an existing ManyToMany to `Check`; this task only exposes/augments it.
  - **Views**: `hc/api/views.py`
    - GET/POST share dispatcher `channel_checks` (csrf exempt + CORS).
    - POST validates every UUID and requires each check to exist in the authenticated project, then uses `channel.checks.set([...])`.
    - DELETE removes a single assignment and returns `204`.
  - **Routing**: `hc/api/urls.py` adds both routes after the existing `channels/` route.
- **Key design constraints**
  - Channel from a different project yields `403`.
  - In POST, checks from a different project are a **hard `400`** (“check not found: <uuid>”), for auditability.
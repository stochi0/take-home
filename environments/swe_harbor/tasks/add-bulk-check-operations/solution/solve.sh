#!/bin/bash
set -e
cd /app

###############################################################################
# 1. Add Check.merge_tags() to hc/api/models.py
###############################################################################

python3 << 'PATCH1'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = '''    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(" ") if t.strip()]'''

new = '''    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(" ") if t.strip()]

    def merge_tags(self, new_tags_str: str) -> None:
        """Merge new space-separated tags into existing tags without duplicates."""
        existing = set(self.tags_list())
        new = {t.strip() for t in new_tags_str.split() if t.strip()}
        merged = existing | new
        self.tags = " ".join(sorted(merged))
        self.save()'''

content = content.replace(old, new, 1)

with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH1

###############################################################################
# 2. Add bulk API views to hc/api/views.py
###############################################################################

cat >> /app/hc/api/views.py << 'VIEWEOF'


def _parse_bulk_checks(request: ApiRequest) -> list[str] | HttpResponse:
    """Parse and validate the 'checks' field from request.json.

    Returns a list of UUID strings on success, or an HttpResponse on error.
    """
    checks = request.json.get("checks")
    if not isinstance(checks, list) or len(checks) == 0:
        return JsonResponse({"error": "checks must be a non-empty list"}, status=400)
    if len(checks) > 50:
        return JsonResponse({"error": "too many checks (max 50)"}, status=400)
    for entry in checks:
        if not isinstance(entry, str) or not is_valid_uuid_string(entry):
            return JsonResponse({"error": f"invalid uuid: {entry}"}, status=400)
    return checks


@cors("POST")
@csrf_exempt
@authorize
def bulk_pause(request: ApiRequest) -> HttpResponse:
    result = _parse_bulk_checks(request)
    if isinstance(result, HttpResponse):
        return result
    uuids = result

    checks = {
        str(c.code): c
        for c in Check.objects.filter(code__in=uuids, project=request.project)
    }

    paused_count = 0
    already_paused_count = 0
    not_found_count = 0

    for uid in uuids:
        check = checks.get(uid)
        if check is None:
            not_found_count += 1
            continue
        if check.status == "paused":
            already_paused_count += 1
        else:
            check.create_flip("paused", mark_as_processed=True)
            check.status = "paused"
            check.last_start = None
            check.alert_after = None
            check.save()
            paused_count += 1

    return JsonResponse({
        "paused": paused_count,
        "already_paused": already_paused_count,
        "not_found": not_found_count,
    })


@cors("POST")
@csrf_exempt
@authorize
def bulk_resume(request: ApiRequest) -> HttpResponse:
    result = _parse_bulk_checks(request)
    if isinstance(result, HttpResponse):
        return result
    uuids = result

    checks = {
        str(c.code): c
        for c in Check.objects.filter(code__in=uuids, project=request.project)
    }

    resumed_count = 0
    not_paused_count = 0
    not_found_count = 0

    for uid in uuids:
        check = checks.get(uid)
        if check is None:
            not_found_count += 1
            continue
        if check.status != "paused":
            not_paused_count += 1
        else:
            check.create_flip("new", mark_as_processed=True)
            check.status = "new"
            check.last_start = None
            check.last_ping = None
            check.alert_after = None
            check.save()
            resumed_count += 1

    return JsonResponse({
        "resumed": resumed_count,
        "not_paused": not_paused_count,
        "not_found": not_found_count,
    })


@cors("POST")
@csrf_exempt
@authorize
def bulk_tag(request: ApiRequest) -> HttpResponse:
    result = _parse_bulk_checks(request)
    if isinstance(result, HttpResponse):
        return result
    uuids = result

    tags_value = request.json.get("tags")
    if tags_value is None:
        return JsonResponse({"error": "tags is required"}, status=400)
    if not isinstance(tags_value, str):
        return JsonResponse({"error": "tags must be a string"}, status=400)
    if not tags_value.strip():
        return JsonResponse({"error": "tags must not be empty"}, status=400)

    checks = {
        str(c.code): c
        for c in Check.objects.filter(code__in=uuids, project=request.project)
    }

    updated_count = 0
    not_found_count = 0

    for uid in uuids:
        check = checks.get(uid)
        if check is None:
            not_found_count += 1
            continue
        check.merge_tags(tags_value)
        updated_count += 1

    return JsonResponse({
        "updated": updated_count,
        "not_found": not_found_count,
    })
VIEWEOF

###############################################################################
# 3. Add URL routes to hc/api/urls.py
###############################################################################

python3 << 'PATCH2'
with open("hc/api/urls.py", "r") as f:
    content = f.read()

old = '''    path("checks/", views.checks),
    path("checks/<uuid:code>", views.single, name="hc-api-single"),'''

new = '''    path("checks/", views.checks),
    path("checks/bulk/pause/", views.bulk_pause, name="hc-api-bulk-pause"),
    path("checks/bulk/resume/", views.bulk_resume, name="hc-api-bulk-resume"),
    path("checks/bulk/tag/", views.bulk_tag, name="hc-api-bulk-tag"),
    path("checks/<uuid:code>", views.single, name="hc-api-single"),'''

content = content.replace(old, new, 1)

with open("hc/api/urls.py", "w") as f:
    f.write(content)
PATCH2

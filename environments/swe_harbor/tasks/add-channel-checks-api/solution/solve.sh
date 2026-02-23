#!/bin/bash
set -e
cd /app

###############################################################################
# 1. Update Channel.to_dict() in hc/api/models.py to include checks_count
###############################################################################

python3 << 'PATCH1'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = '''    def to_dict(self) -> dict[str, str]:
        return {"id": str(self.code), "name": self.name, "kind": self.kind}'''

new = '''    def to_dict(self) -> dict:
        return {
            "id": str(self.code),
            "name": self.name,
            "kind": self.kind,
            "checks_count": self.checks.count(),
        }'''

if old not in content:
    raise SystemExit("Could not find Channel.to_dict() anchor in models.py")

content = content.replace(old, new, 1)

with open("hc/api/models.py", "w") as f:
    f.write(content)

print("Patched Channel.to_dict()")
PATCH1

###############################################################################
# 2. Add API views to hc/api/views.py
###############################################################################

cat >> /app/hc/api/views.py << 'VIEWEOF'


@authorize_read
def list_channel_checks(request: ApiRequest, code: UUID) -> HttpResponse:
    channel = get_object_or_404(Channel, code=code)
    if channel.project_id != request.project.id:
        return HttpResponseForbidden()

    checks = [c.to_dict(readonly=request.readonly, v=request.v) for c in channel.checks.all()]
    return JsonResponse({"checks": checks})


@authorize
def set_channel_checks(request: ApiRequest, code: UUID) -> HttpResponse:
    channel = get_object_or_404(Channel, code=code)
    if channel.project_id != request.project.id:
        return HttpResponseForbidden()

    raw = request.json.get("checks")
    if not isinstance(raw, list):
        return JsonResponse({"error": "checks must be a list"}, status=400)

    if len(raw) > 50:
        return JsonResponse({"error": "too many checks (max 50)"}, status=400)

    for entry in raw:
        if not isinstance(entry, str) or not is_valid_uuid_string(entry):
            return JsonResponse({"error": f"invalid uuid: {entry}"}, status=400)

    # Fetch all matching checks in one query
    found = {
        str(c.code): c
        for c in Check.objects.filter(code__in=raw, project=request.project)
    }
    for uid in raw:
        if uid not in found:
            return JsonResponse({"error": f"check not found: {uid}"}, status=400)

    check_objs = [found[uid] for uid in raw]
    channel.checks.set(check_objs)

    updated_checks = [c.to_dict(readonly=False, v=request.v) for c in channel.checks.all()]
    return JsonResponse({"checks": updated_checks})


@csrf_exempt
@cors("GET", "POST")
def channel_checks(request: HttpRequest, code: UUID) -> HttpResponse:
    if request.method == "POST":
        return set_channel_checks(request, code)
    return list_channel_checks(request, code)


@cors("DELETE")
@csrf_exempt
@authorize
def channel_check(request: ApiRequest, code: UUID, check_code: UUID) -> HttpResponse:
    channel = get_object_or_404(Channel, code=code)
    if channel.project_id != request.project.id:
        return HttpResponseForbidden()

    try:
        check = channel.checks.get(code=check_code)
    except Check.DoesNotExist:
        return HttpResponseNotFound()

    channel.checks.remove(check)
    return HttpResponse(status=204)
VIEWEOF

###############################################################################
# 3. Add URL routes to hc/api/urls.py
###############################################################################

python3 << 'PATCH2'
with open("hc/api/urls.py", "r") as f:
    content = f.read()

old = '    path("channels/", views.channels),'

new = '''    path("channels/", views.channels),
    path(
        "channels/<uuid:code>/checks/",
        views.channel_checks,
        name="hc-api-channel-checks",
    ),
    path(
        "channels/<uuid:code>/checks/<uuid:check_code>/",
        views.channel_check,
        name="hc-api-channel-check",
    ),'''

if old not in content:
    raise SystemExit("Could not find channels route anchor in urls.py")

content = content.replace(old, new, 1)

with open("hc/api/urls.py", "w") as f:
    f.write(content)

print("Patched urls.py")
PATCH2

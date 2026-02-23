#!/bin/bash
set -e
cd /app

###############################################################################
# 1. Add the MaintenanceWindow model to hc/api/models.py
###############################################################################

cat >> /app/hc/api/models.py << 'PYEOF'


class MaintenanceWindow(models.Model):
    code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    owner = models.ForeignKey(Check, models.CASCADE, related_name="maintenance_windows")
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    reason = models.CharField(max_length=200, blank=True, default="")
    created = models.DateTimeField(default=now)

    class Meta:
        ordering = ["-start_at"]

    def to_dict(self) -> dict:
        return {
            "uuid": str(self.code),
            "start_at": isostring(self.start_at),
            "end_at": isostring(self.end_at),
            "reason": self.reason,
            "created": isostring(self.created),
            "active": self.start_at <= now() < self.end_at,
        }
PYEOF

###############################################################################
# 2. Add in_maintenance to Check.to_dict()
###############################################################################

python3 << 'PATCH1'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = '''        if self.kind == "simple":
            result["timeout"] = int(self.timeout.total_seconds())
        elif self.kind in ("cron", "oncalendar"):
            result["schedule"] = self.schedule
            result["tz"] = self.tz

        return result'''

new = '''        result["in_maintenance"] = self.maintenance_windows.filter(
            start_at__lte=now(),
            end_at__gt=now()
        ).exists()

        if self.kind == "simple":
            result["timeout"] = int(self.timeout.total_seconds())
        elif self.kind in ("cron", "oncalendar"):
            result["schedule"] = self.schedule
            result["tz"] = self.tz

        return result'''

content = content.replace(old, new, 1)

with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH1

###############################################################################
# 3. Add API views for maintenance windows
###############################################################################

cat >> /app/hc/api/views.py << 'VIEWEOF'


@authorize_read
def list_maintenance(request: ApiRequest, code: UUID) -> HttpResponse:
    check = get_object_or_404(Check, code=code)
    if check.project_id != request.project.id:
        return HttpResponseForbidden()

    from hc.api.models import MaintenanceWindow

    q = MaintenanceWindow.objects.filter(owner=check)

    if request.GET.get("active") == "1":
        t = now()
        q = q.filter(start_at__lte=t, end_at__gt=t)

    return JsonResponse({"maintenance_windows": [w.to_dict() for w in q]})


@authorize
def create_maintenance(request: ApiRequest, code: UUID) -> HttpResponse:
    check = get_object_or_404(Check, code=code)
    if check.project_id != request.project.id:
        return HttpResponseForbidden()

    from hc.api.models import MaintenanceWindow

    if check.maintenance_windows.count() >= 20:
        return JsonResponse({"error": "too many maintenance windows"}, status=403)

    start_at_raw = request.json.get("start_at", "")
    if not start_at_raw:
        return JsonResponse({"error": "invalid start_at"}, status=400)
    try:
        start_at = datetime.fromisoformat(str(start_at_raw))
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid start_at"}, status=400)

    end_at_raw = request.json.get("end_at", "")
    if not end_at_raw:
        return JsonResponse({"error": "invalid end_at"}, status=400)
    try:
        end_at = datetime.fromisoformat(str(end_at_raw))
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid end_at"}, status=400)

    if end_at <= start_at:
        return JsonResponse({"error": "end_at must be after start_at"}, status=400)

    reason = request.json.get("reason", "")
    if not isinstance(reason, str):
        return JsonResponse({"error": "reason is not a string"}, status=400)
    if len(reason) > 200:
        return JsonResponse({"error": "reason is too long"}, status=400)

    window = MaintenanceWindow(
        owner=check,
        start_at=start_at,
        end_at=end_at,
        reason=reason,
    )
    window.save()

    return JsonResponse(window.to_dict(), status=201)


@csrf_exempt
@cors("GET", "POST")
def check_maintenance(request: HttpRequest, code: UUID) -> HttpResponse:
    if request.method == "POST":
        return create_maintenance(request, code)
    return list_maintenance(request, code)


@cors("DELETE")
@csrf_exempt
@authorize
def check_maintenance_window(request: ApiRequest, code: UUID, window_code: UUID) -> HttpResponse:
    check = get_object_or_404(Check, code=code)
    if check.project_id != request.project.id:
        return HttpResponseForbidden()

    from hc.api.models import MaintenanceWindow

    window = get_object_or_404(MaintenanceWindow, code=window_code, owner=check)
    window.delete()
    return HttpResponse(status=204)
VIEWEOF

###############################################################################
# 4. Add URL routes
###############################################################################

python3 << 'PATCH2'
with open("hc/api/urls.py", "r") as f:
    content = f.read()

old = '    path("channels/", views.channels),'

new = '''    path(
        "checks/<uuid:code>/maintenance/",
        views.check_maintenance,
        name="hc-api-maintenance",
    ),
    path(
        "checks/<uuid:code>/maintenance/<uuid:window_code>/",
        views.check_maintenance_window,
        name="hc-api-maintenance-window",
    ),
    path("channels/", views.channels),'''

content = content.replace(old, new, 1)

with open("hc/api/urls.py", "w") as f:
    f.write(content)
PATCH2

###############################################################################
# 5. Create and apply the migration
###############################################################################

python manage.py makemigrations api --name maintenancewindow 2>&1
python manage.py migrate 2>&1

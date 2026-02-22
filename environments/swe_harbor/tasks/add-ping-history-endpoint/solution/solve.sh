#!/bin/bash
# Reference solution for add-ping-history-endpoint task
set -e
cd /app

python3 << 'PYEOF'
import re, math

# ── 1. Read views.py ─────────────────────────────────────────────────────────
with open("hc/api/views.py") as f:
    src = f.read()

# ── 2. Add the get_pings view ─────────────────────────────────────────────────
get_pings_view = '''

@authorize
def get_pings(request, code):
    """GET /api/v3/checks/<uuid>/pings/ — return paginated ping history."""
    import math as _math
    from hc.api.models import Ping

    # Resolve the check; 404 if not in this project
    try:
        check = Check.objects.get(code=code, project=request.project)
    except Check.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)

    if request.method != "GET":
        return HttpResponse(status=405)

    # Parse ?n= (page size, max 100)
    try:
        n = int(request.GET.get("n", 50))
        if n < 1 or n > 100:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid n"}, status=400)

    # Parse ?p= (page number, 1-indexed)
    try:
        p = int(request.GET.get("p", 1))
        if p < 1:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid page"}, status=400)

    # Parse ?action= (optional filter)
    allowed_actions = {"start", "success", "fail", "ign"}
    action = request.GET.get("action", "")
    if action and action not in allowed_actions:
        return JsonResponse({"error": "invalid action"}, status=400)

    qs = Ping.objects.filter(owner=check).order_by("-created")
    if action:
        qs = qs.filter(action=action)

    total = qs.count()
    pages = _math.ceil(total / n) if total > 0 else 0
    offset = (p - 1) * n
    pings_page = qs[offset:offset + n]

    def ping_to_dict(ping):
        return {
            "id": ping.id,
            "created": ping.created.isoformat(),
            "scheme": ping.scheme,
            "method": ping.method,
            "ua": ping.ua or "",
            "action": ping.action,
            "exitstatus": ping.exitstatus,
            "remote_addr": ping.remote_addr or "",
        }

    return JsonResponse({
        "pings": [ping_to_dict(p_) for p_ in pings_page],
        "total": total,
        "page": p,
        "pages": pages,
    })

'''

# Insert before the first @csrf_exempt or @require_POST (ping-related views)
if "\n@csrf_exempt\ndef ping" in src:
    src = src.replace("\n@csrf_exempt\ndef ping", get_pings_view + "\n@csrf_exempt\ndef ping", 1)
elif "\ndef ping(" in src:
    src = src.replace("\ndef ping(", get_pings_view + "\ndef ping(", 1)
else:
    src += get_pings_view
print("Added get_pings view")

# Ensure HttpResponse is imported
if "from django.http import" in src and "HttpResponse" not in src:
    src = re.sub(
        r'(from django\.http import )([^\n]+)',
        lambda m: m.group(1) + m.group(2) + ", HttpResponse",
        src,
        count=1
    )
elif "HttpResponse" not in src:
    src = "from django.http import HttpResponse\n" + src

with open("hc/api/views.py", "w") as f:
    f.write(src)
print("Wrote views.py")

# ── 3. Patch urls.py ─────────────────────────────────────────────────────────
with open("hc/api/urls.py") as f:
    urls = f.read()

# Add import
if "get_pings" not in urls:
    urls = re.sub(
        r'(from hc\.api\.views import\s+[^\n]+)',
        lambda m: m.group(0) + "\nfrom hc.api.views import get_pings",
        urls,
        count=1
    )
    if "get_pings" not in urls:
        urls = "from hc.api.views import get_pings\n" + urls

# Add URL route — must appear BEFORE the generic checks/<uuid:code>/ catch-all
ping_url = '    path("v3/checks/<uuid:code>/pings/", get_pings),'
if ping_url not in urls:
    if 'path("v3/checks/<uuid:code>/' in urls:
        urls = urls.replace(
            'path("v3/checks/<uuid:code>/',
            ping_url + '\n    path("v3/checks/<uuid:code>/',
            1
        )
        print("Added get_pings route before checks/<uuid>")
    else:
        urls = re.sub(r'(urlpatterns\s*=\s*\[)', r'\1\n' + ping_url, urls, count=1)
        print("Added get_pings route at top of urlpatterns")

with open("hc/api/urls.py", "w") as f:
    f.write(urls)
print("Wrote urls.py")

PYEOF

# Verify imports
python3 -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hc.settings')
django.setup()
import hc.api.views
import hc.api.urls
print('Import check passed')
" 2>&1

echo "Solution applied."

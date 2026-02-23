#!/bin/bash
set -e
cd /app

python3 << 'PYEOF'
from pathlib import Path

views_path = Path("hc/api/views.py")
src = views_path.read_text()

marker = '''@cors("GET")
@csrf_exempt
@authorize
def ping_body(request: ApiRequest, code: UUID, n: int) -> HttpResponse:
'''

insert = '''@cors("GET")
@csrf_exempt
@authorize_read
def project_stats(request: ApiRequest, code: UUID) -> HttpResponse:
    from django.db.models import Sum

    if str(request.project.code) != str(code):
        return HttpResponseNotFound()

    checks = Check.objects.filter(project=request.project)
    total = checks.count()

    by_status = {
        "up": 0,
        "down": 0,
        "grace": 0,
        "paused": 0,
        "new": 0,
        "started": 0,
    }
    for status in by_status:
        by_status[status] = checks.filter(status=status).count()

    total_pings = checks.aggregate(value=Sum("n_pings"))["value"] or 0

    cutoff = now() - td(days=7)
    stale_checks = checks.filter(n_pings=0, created__lt=cutoff).count()

    return JsonResponse(
        {
            "project_uuid": str(request.project.code),
            "total": total,
            "by_status": by_status,
            "total_pings": total_pings,
            "stale_checks": stale_checks,
        }
    )


@cors("GET")
@csrf_exempt
@authorize
def ping_body(request: ApiRequest, code: UUID, n: int) -> HttpResponse:
'''

if marker not in src:
    raise SystemExit("Could not locate ping_body marker for project_stats insertion")

src = src.replace(marker, insert, 1)
views_path.write_text(src)
print("Added project_stats view")

urls_path = Path("hc/api/urls.py")
urls = urls_path.read_text()

anchor = '    path("checks/", views.checks),\n'
if anchor not in urls:
    raise SystemExit("Could not locate checks route anchor in urls.py")

addition = anchor + '    path("projects/<uuid:code>/stats/", views.project_stats),\n'
urls = urls.replace(anchor, addition, 1)
urls_path.write_text(urls)
print("Added project_stats route")
PYEOF

cat > hc/api/management/commands/archive_stale_checks.py << 'PYEOF'
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import now
from datetime import timedelta as td

from hc.api.models import Check


class Command(BaseCommand):
    help = "Archive stale checks that were never pinged."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]

        if days < 1:
            raise CommandError("--days must be >= 1")

        cutoff = now() - td(days=days)
        qs = Check.objects.filter(n_pings=0, created__lt=cutoff).exclude(status="paused")
        count = qs.count()

        if dry_run:
            self.stdout.write(f"[DRY RUN] Would archive {count} stale checks.")
            return

        qs.update(status="paused")
        self.stdout.write(f"Archived {count} stale checks.")
PYEOF

echo "Solution applied"

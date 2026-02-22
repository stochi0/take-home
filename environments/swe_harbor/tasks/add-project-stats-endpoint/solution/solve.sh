#!/bin/bash
# Reference solution for add-project-stats-endpoint task
set -e
cd /app

# ── Part A: Project Stats API endpoint ──────────────────────────────────────
python3 << 'PYEOF'
import re

with open("hc/api/views.py") as f:
    src = f.read()

project_stats_view = '''

@authorize
def project_stats(request, code):
    """GET /api/v3/projects/<uuid>/stats/ — aggregate stats for a project."""
    from django.db.models import Sum
    from django.utils import timezone

    # The authenticated project must match the URL UUID
    if str(request.project.code) != str(code):
        return JsonResponse({"error": "not found"}, status=404)

    project = request.project
    checks = project.check_set.all()
    total = checks.count()

    status_counts = {"up": 0, "down": 0, "grace": 0, "paused": 0, "new": 0, "started": 0}
    for status in status_counts:
        status_counts[status] = checks.filter(status=status).count()

    agg = checks.aggregate(total_pings=Sum("n_pings"))
    total_pings = agg["total_pings"] or 0

    cutoff = timezone.now() - timezone.timedelta(days=7)
    stale = checks.filter(n_pings=0, created__lt=cutoff).count()

    return JsonResponse({
        "project_uuid": str(project.code),
        "total": total,
        "by_status": status_counts,
        "total_pings": total_pings,
        "stale_checks": stale,
    })

'''

# Insert before ping view
if "\n@csrf_exempt\ndef ping" in src:
    src = src.replace("\n@csrf_exempt\ndef ping", project_stats_view + "\n@csrf_exempt\ndef ping", 1)
elif "\ndef ping(" in src:
    src = src.replace("\ndef ping(", project_stats_view + "\ndef ping(", 1)
else:
    src += project_stats_view

with open("hc/api/views.py", "w") as f:
    f.write(src)
print("Added project_stats view")

# ── URL routing ──────────────────────────────────────────────────────────────
with open("hc/api/urls.py") as f:
    urls = f.read()

if "project_stats" not in urls:
    urls = re.sub(
        r'(from hc\.api\.views import\s+[^\n]+)',
        lambda m: m.group(0) + "\nfrom hc.api.views import project_stats",
        urls,
        count=1
    )
    if "project_stats" not in urls:
        urls = "from hc.api.views import project_stats\n" + urls

url_entry = '    path("v3/projects/<uuid:code>/stats/", project_stats),'
if url_entry not in urls:
    if 'path("v3/checks/' in urls:
        urls = urls.replace(
            'path("v3/checks/',
            url_entry + '\n    path("v3/checks/',
            1
        )
    else:
        urls = re.sub(r'(urlpatterns\s*=\s*\[)', r'\1\n' + url_entry, urls, count=1)
    print("Added project_stats URL route")

with open("hc/api/urls.py", "w") as f:
    f.write(urls)
print("Wrote urls.py")

PYEOF

# ── Part B: Management command ───────────────────────────────────────────────
mkdir -p hc/api/management/commands

cat > hc/api/management/commands/archive_stale_checks.py << 'PYEOF'
"""
Management command: archive_stale_checks

Finds checks that have never been pinged (n_pings == 0) and were created
more than --days days ago, and archives them by setting status to 'paused'.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Archive stale checks that have never been pinged."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Staleness threshold in days (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview without making changes",
        )

    def handle(self, *args, **options):
        from hc.api.models import Check

        days = options["days"]
        dry_run = options["dry_run"]

        cutoff = timezone.now() - timezone.timedelta(days=days)
        qs = Check.objects.filter(n_pings=0, created__lt=cutoff)
        count = qs.count()

        if dry_run:
            self.stdout.write(f"[DRY RUN] Would archive {count} stale checks.")
        else:
            qs.update(status="paused")
            self.stdout.write(f"Archived {count} stale checks.")
PYEOF

echo "Created archive_stale_checks management command"

# Verify
python3 -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hc.settings')
django.setup()
import hc.api.views
import hc.api.urls
from django.core.management import call_command
print('Import checks passed')
" 2>&1

echo "Solution applied."

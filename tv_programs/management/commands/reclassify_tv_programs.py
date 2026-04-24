from __future__ import annotations

from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from tv_programs.classification import classify
from tv_programs.models import Program


class Command(BaseCommand):
    help = (
        "Re-run heuristic TV classification for Program rows. "
        "Fills content_type, classification_*, and is idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=str,
            help="Only programs with start_time on or after this date (YYYY-MM-DD, UTC).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print counts without writing to the database",
        )

    def handle(self, *args, **options):
        since: str | None = options.get("since")
        dry: bool = options.get("dry_run", False)
        dt_filter = None
        if since:
            d = parse_date(since)
            if not d:
                raise CommandError("Invalid --since date, expected YYYY-MM-DD")
            dt_filter = timezone.make_aware(
                datetime.combine(d, time.min),
                timezone.get_current_timezone(),
            )
        qs = Program.objects.all().order_by("start_time")
        if dt_filter is not None:
            qs = qs.filter(start_time__gte=dt_filter)
        n = 0
        to_update: list[Program] = []
        for prog in qs.iterator():
            c = classify(
                prog.title_lv,
                (prog.description_lv or ""),
                prog.channel.name,
                prog.duration_minutes,
            )
            if (
                prog.content_type == c.content_type
                and (prog.classification_confidence or 0) == c.confidence
                and (prog.classification_reasoning or "") == (c.reasoning or "")[:255]
            ):
                continue
            if dry:
                n += 1
                continue
            prog.content_type = c.content_type
            prog.classification_confidence = c.confidence
            prog.classification_reasoning = c.reasoning[:255] if c.reasoning else ""
            to_update.append(prog)
            n += 1
            if len(to_update) >= 500:
                Program.objects.bulk_update(
                    to_update,
                    [
                        "content_type",
                        "classification_confidence",
                        "classification_reasoning",
                    ],
                )
                to_update = []
        if to_update and not dry:
            Program.objects.bulk_update(
                to_update,
                [
                    "content_type",
                    "classification_confidence",
                    "classification_reasoning",
                ],
            )
        if dry:
            self.stdout.write(self.style.WARNING(f"Dry run: {n} program(s) would be updated"))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Updated {n} program(s) (classification fields)")
            )

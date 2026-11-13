from __future__ import annotations

from datetime import datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from tv_programs.classification import Classification, classify
from tv_programs.models import Program, Show

# Rollup priority for Show.content_type: a "movie" verdict on any
# airing wins — the same content in a short or general-channel
# slot is still a film — else not_movie beats unknown.
_CT_PRIORITY = {
    Program.ContentType.MOVIE: 2,
    Program.ContentType.NOT_MOVIE: 1,
    Program.ContentType.UNKNOWN: 0,
}


class Command(BaseCommand):
    help = (
        "Re-run heuristic TV classification for Program rows and "
        "roll the result up to their canonical Shows (Programs "
        "inherit show.content_type at scrape time). "
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
        qs = Program.objects.select_related("channel").order_by(
            "start_time"
        )
        if dt_filter is not None:
            qs = qs.filter(start_time__gte=dt_filter)
        n = 0
        to_update: list[Program] = []
        fresh: dict = {}
        prog_show: dict = {}
        for prog in qs.iterator():
            c = classify(
                prog.title_lv,
                (prog.description_lv or ""),
                prog.channel.name,
                prog.duration_minutes,
            )
            fresh[prog.pk] = c
            prog_show[prog.pk] = prog.show_id
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

        # Roll program verdicts up to the canonical Show — new
        # airings inherit show.content_type at scrape time, so a
        # Program-only fix would be undone by the next scrape.
        by_show: dict = {}
        for pid, c in fresh.items():
            sid = prog_show.get(pid)
            if sid:
                by_show.setdefault(sid, []).append(c)
        if dt_filter is not None and by_show:
            # Out-of-scope airings keep their stored verdict.
            for sid, ct, conf, rsn in (
                Program.objects.filter(show_id__in=by_show)
                .exclude(pk__in=fresh)
                .values_list(
                    "show_id",
                    "content_type",
                    "classification_confidence",
                    "classification_reasoning",
                )
            ):
                by_show[sid].append(
                    Classification(ct, conf or 0.0, rsn or "")
                )

        shows_changed = 0
        to_update_shows: list[Show] = []
        for show in Show.objects.filter(pk__in=by_show).iterator():
            best = max(
                by_show[show.pk],
                key=lambda c: _CT_PRIORITY.get(c.content_type, 0),
            )
            reasoning = (best.reasoning or "")[:255]
            if (
                show.content_type == best.content_type
                and (show.classification_confidence or 0)
                == best.confidence
                and (show.classification_reasoning or "") == reasoning
            ):
                continue
            shows_changed += 1
            if dry:
                continue
            show.content_type = best.content_type
            show.classification_confidence = best.confidence
            show.classification_reasoning = reasoning
            to_update_shows.append(show)
        if to_update_shows:
            Show.objects.bulk_update(
                to_update_shows,
                [
                    "content_type",
                    "classification_confidence",
                    "classification_reasoning",
                ],
            )
        if dry:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {n} program(s) and "
                    f"{shows_changed} show(s) would be updated"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {n} program(s) and "
                    f"{shows_changed} show(s) (classification fields)"
                )
            )

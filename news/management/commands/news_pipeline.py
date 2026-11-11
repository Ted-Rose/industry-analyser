"""Daily news pipeline as one cycle-checkpointed job.

Runs the four daily phases in order — ``scrape_news`` →
``link_news_stories`` → ``reclassify_news_articles`` →
``build_news_digest`` — each checkpointed as a ScrapeJobItem
under job slug ``news.pipeline`` with today's (UTC) cycle key.
A phase that raises is recorded FAILED, later phases do not run
and the run ends PARTIAL, so the next invocation in the same
cycle resumes at the failed phase instead of repeating finished
work. Re-invoking after a fully DONE cycle runs nothing.

This is orchestration only — each phase is a ``call_command``
exactly like ``run_all_jobs`` used to invoke them individually,
so the delegated commands stay standalone (e.g.
``link_news_stories --days N`` for outage catch-up,
``build_news_digest --days N`` for missed days).
"""
import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from scrape_jobs.models import ScrapeJob, ScrapeJobRunItem
from scrape_jobs.runner import ScrapeJobRunner

logger = logging.getLogger('news')

JOB_SLUG = 'news.pipeline'

# (item key, delegated command, item label, priority) —
# pending_items orders by -priority, so descending priority is
# the execution order.
PHASES = (
    ('scrape', 'scrape_news', 'RSS feed scrape', 40),
    ('link', 'link_news_stories', 'Story clustering', 30),
    ('reclassify', 'reclassify_news_articles',
     'Topic reclassification', 20),
    ('digest', 'build_news_digest', 'Daily digest build', 10),
)


def _cycle_done_keys(cycle_key, fresh):
    """DONE item keys of this job's ``cycle_key`` runs — read-only.

    ``ScrapeJobRunner(dry_run=True)`` skips the completed-keys read
    (it writes nothing and the job row may not exist), which would
    list every phase as pending. This mirrors
    ``ScrapeJobRunner._cycle_completed_keys`` as a pure query so
    --dry-run can show only genuinely pending phases.
    """
    job = ScrapeJob.objects.filter(slug=JOB_SLUG).first()
    if job is None or fresh or not job.is_enabled:
        return set()
    return set(
        ScrapeJobRunItem.objects.filter(
            run__in=job.runs.filter(cycle_key=cycle_key),
            status=ScrapeJobRunItem.DONE,
        ).values_list('item__key', flat=True)
    )


class Command(BaseCommand):
    help = (
        'Run the daily news pipeline as one checkpointed job: '
        'scrape feeds, link stories, reclassify topics and '
        'build the digest — resumable per phase within the '
        'daily cycle'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--fresh',
            action='store_true',
            help="Ignore this cycle's completed phases — full "
                 'pass; also forwards --fresh to scrape_news '
                 'so feeds are re-fetched',
        )
        parser.add_argument(
            '--from',
            type=str,
            default=None,
            dest='from_phase',
            metavar='PHASE',
            help='Resume at this phase (one of: scrape, link, '
                 'reclassify, digest), skipping earlier ones '
                 'even when they never ran this cycle',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Print the pending phases without invoking '
                 'any command or writing job bookkeeping',
        )

    def handle(self, *args, **options):
        runner = ScrapeJobRunner(
            slug=JOB_SLUG,
            description='Daily news pipeline: scrape, link, '
                        'reclassify, digest',
            fresh=options['fresh'],
            resume_from=options['from_phase'],
            dry_run=options['dry_run'],
        )
        entries = [
            (key, label, priority, command)
            for key, command, label, priority in PHASES
        ]
        try:
            items = runner.sync_items(entries)
            if options['dry_run']:
                # The dry-run runner hardcodes an empty
                # completed set — fill it from the DB read-only
                # so the pending list is honest.
                runner.completed_keys = _cycle_done_keys(
                    runner.cycle_key, options['fresh'],
                )
            pending = runner.pending_items(items)

            if options['dry_run']:
                self._print_dry_run(runner, items, pending)
                return

            for item in pending:
                logger.info(
                    '%s phase %r starting', JOB_SLUG, item.key
                )
                # --fresh re-scrapes: forwarded only to
                # scrape_news, which bypasses its cycle gate
                # and conditional GETs.
                argv = (
                    ['--fresh']
                    if item.key == 'scrape' and options['fresh']
                    else []
                )
                try:
                    call_command(item.obj, *argv)
                except (Exception, SystemExit) as e:
                    # Abort at the failed phase: downstream
                    # phases on stale data would produce
                    # misleading digests. The FAILED item keeps
                    # the phase pending so the next cycle
                    # invocation resumes here; finish() ends
                    # the run PARTIAL.
                    runner.item_failed(item, e)
                    runner.finish()
                    raise CommandError(
                        f'{JOB_SLUG} aborted at phase '
                        f'{item.key!r}: {e}'
                    ) from e
                runner.item_done(item)
            runner.finish()
        except CommandError:
            raise
        except Exception as e:
            # A pre-loop failure (item sync, unknown --from)
            # would otherwise leave the RUNNING run dangling
            # until the next invocation's stale sweep.
            if not options['dry_run']:
                runner.finish('FAILED', str(e))
            raise CommandError(str(e)) from e

    def _print_dry_run(self, runner, items, pending):
        keys = ', '.join(i.key for i in pending) or '(none)'
        self.stdout.write(
            f'{JOB_SLUG} cycle={runner.cycle_key} — '
            f'pending phases: {keys}'
        )
        done = [
            i.key for i in items if i.key in runner.completed_keys
        ]
        if done:
            self.stdout.write(
                'already done this cycle: ' + ', '.join(done)
            )

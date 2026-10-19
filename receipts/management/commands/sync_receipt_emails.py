"""Poll the receipt collector inbox over IMAP (plan §5.5).

``python manage.py sync_receipt_emails`` fetches UNSEEN mail from
the collector Gmail inbox and ingests PDF attachments into
Receipt/ReceiptItem rows. Exits 0 even when individual mails fail
(per-mail errors are logged + get ``parse_error`` rows); exits
non-zero when IMAP connect/login fails, when an ``AIJobError``
aborts the run (request cap, provider outage, disabled or
unseeded job — a silent exit-0 would hide that in Cloud Run), or
when non-IMAP4 errors (socket/OSError/SSL) propagate from
fetch/search/store. A bad message cannot wedge the daily job,
but a broken run must fail loudly.
"""

import logging
import traceback
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ai_providers.client import get_job_client
from ai_providers.errors import AIJobError

from receipts.ai_jobs import RECEIPT_EXTRACT
from receipts.imap_client import connect, iter_messages, mark_seen
from receipts.ingest import _write_parse_error, process_message

logger = logging.getLogger('receipts')


class Command(BaseCommand):
    help = (
        'Fetch UNSEEN mail from the receipts collector inbox and '
        'ingest PDF attachments into Receipt rows.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            default=None,
            help='Username owning the receipts '
                 '(default: first superuser)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Max messages to process this run (default 100)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Scan ALL messages, not just UNSEEN (backfill)',
        )
        parser.add_argument(
            '--dry-run',
            dest='dry_run',
            action='store_true',
            help='Fetch and parse but write nothing, make no AI '
                 'calls, and leave messages UNSEEN',
        )
        parser.add_argument(
            '--last-day-only',
            action='store_true',
            help='Exit early unless today is the last day of the '
                 'month — for schedulers firing on days 28-31 '
                 '(GCP unix-cron has no L token)',
        )
        parser.add_argument(
            '--max-api-requests',
            type=int,
            default=None,
            help=(
                'Cap AI requests sent this run. The effective cap '
                'is the lower of this value and the AIJob row\'s '
                'max_requests_per_run (editable in admin).'
            ),
        )

    def _resolve_user(self, username):
        User = get_user_model()
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f"user '{username}' not found")
        user = (
            User.objects.filter(is_superuser=True)
            .order_by('pk')
            .first()
        )
        if user is None:
            raise CommandError(
                'no superuser exists — pass --user USERNAME'
            )
        return user

    def handle(self, *args, **options):
        if options['last_day_only']:
            tomorrow = timezone.now().date() + timedelta(days=1)
            if tomorrow.day != 1:
                self.stdout.write(
                    'Not the last day of the month — skipping.'
                )
                return
        user = self._resolve_user(options['user'])
        dry_run = options['dry_run']

        ai_client = None

        def get_ai_client():
            # Built lazily: the AIJob row is seeded (a write) only
            # when an image-only PDF actually needs it.
            nonlocal ai_client
            if ai_client is None:
                ai_client = get_job_client(
                    RECEIPT_EXTRACT,
                    max_requests_per_run=options['max_api_requests'],
                )
            return ai_client

        try:
            imap = connect()
        except Exception as e:
            raise CommandError(f'IMAP connect/login failed: {e}')

        counts = {
            'messages': 0,
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'ai_pending': 0,
        }
        aborted = None
        try:
            for num, msg in iter_messages(
                imap, scan_all=options['all'],
                limit=options['limit'],
            ):
                counts['messages'] += 1
                try:
                    result = process_message(
                        user, msg,
                        get_ai_client=get_ai_client,
                        dry_run=dry_run,
                    )
                except AIJobError as e:
                    # Cap reached / provider outage / unseeded or
                    # disabled job: every remaining image-PDF
                    # message would fail the same way, so abort
                    # the run — this message stays UNSEEN (no
                    # parse_error row was written) for retry, and
                    # the run exits non-zero below.
                    counts['errors'] += 1
                    partial = getattr(e, 'partial_result', None)
                    if partial is not None:
                        # Attachments processed before the failure
                        # still count in the summary.
                        counts['created'] += partial.created
                        counts['skipped'] += partial.skipped
                        counts['errors'] += partial.errors
                        counts['ai_pending'] += partial.ai_pending
                    aborted = e
                    logger.error(
                        'message %s aborted the run: %s',
                        num, e)
                    break
                except Exception as e:
                    # Deterministic per-message failure outside the
                    # attachment path (e.g. malformed MIME) would
                    # retry forever — record a parse_error row
                    # keyed on the message (dedup still applies)
                    # and mark it seen.
                    counts['errors'] += 1
                    logger.error(
                        'message %s failed unrecoverably: %s',
                        num, e, exc_info=True,
                    )
                    if not dry_run:
                        message_id = (
                            msg.get('Message-ID') or '')[:255]
                        seq = (
                            num.decode()
                            if isinstance(num, bytes)
                            else str(num)
                        )
                        _write_parse_error(
                            user,
                            f'msg-{message_id or seq}'[:64],
                            '', message_id,
                            traceback.format_exc(),
                        )
                        mark_seen(imap, num)
                    continue
                counts['created'] += result.created
                counts['skipped'] += result.skipped
                counts['errors'] += result.errors
                counts['ai_pending'] += result.ai_pending
                if not dry_run:
                    # \Seen only after successful processing — a
                    # crashed run leaves the mail for retry.
                    mark_seen(imap, num)
        finally:
            try:
                imap.logout()
            except Exception:
                pass

        suffix = ' [dry-run]' if dry_run else ''
        # In dry-run nothing was written — 'created' counts what
        # would have been stored.
        created_label = (
            'receipt(s) would have been written'
            if dry_run else 'receipt(s)'
        )
        self.stdout.write(self.style.SUCCESS(
            f"Done{suffix}: {counts['messages']} message(s), "
            f"{counts['created']} {created_label}, "
            f"{counts['skipped']} duplicate(s) skipped, "
            f"{counts['errors']} error(s), "
            f"{counts['ai_pending']} would need AI extraction."
        ))
        if aborted is not None:
            raise CommandError(
                f'run aborted after {counts["messages"]} '
                f'message(s): {aborted}'
            )

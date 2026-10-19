"""Poll the receipt collector inbox over IMAP (plan §5.5).

``python manage.py sync_receipt_emails`` fetches UNSEEN mail from
the collector Gmail inbox and ingests PDF attachments into
Receipt/ReceiptItem rows. Exits 0 even when individual mails fail
(per-mail errors are logged + get ``parse_error`` rows); non-zero
only if IMAP connect/login fails — a bad message cannot wedge the
daily Cloud Run job.
"""

import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ai_providers.client import get_job_client

from receipts.ai_jobs import RECEIPT_EXTRACT
from receipts.imap_client import connect, iter_messages, mark_seen
from receipts.ingest import process_message

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
        try:
            for num, msg in iter_messages(
                imap, scan_all=options['all']
            ):
                if counts['messages'] >= options['limit']:
                    break
                counts['messages'] += 1
                try:
                    result = process_message(
                        user, msg,
                        get_ai_client=get_ai_client,
                        dry_run=dry_run,
                    )
                except Exception as e:
                    # Unrecoverable (e.g. even the parse_error row
                    # failed) — leave UNSEEN for the next run.
                    counts['errors'] += 1
                    logger.error(
                        'message %s failed unrecoverably: %s',
                        num, e, exc_info=True,
                    )
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
        self.stdout.write(self.style.SUCCESS(
            f"Done{suffix}: {counts['messages']} message(s), "
            f"{counts['created']} receipt(s), "
            f"{counts['skipped']} duplicate(s) skipped, "
            f"{counts['errors']} error(s), "
            f"{counts['ai_pending']} would need AI extraction."
        ))

"""Thin wrapper over imaplib for the receipt collector inbox
(plan §5.1).

``UNSEEN`` is the incremental cursor — no state table is needed.
Messages are fetched with ``BODY.PEEK[]`` so a crashed run leaves
them UNSEEN for retry; ``\\Seen`` is stored only after a message
was fully processed (or its ``parse_error`` row was written), so
poison mail doesn't retry forever.
"""

import imaplib
import logging
from email import policy
from email.parser import BytesParser

from django.conf import settings

logger = logging.getLogger('receipts')

IMAP_HOST = 'imap.gmail.com'
IMAP_MAILBOX = 'INBOX'


def connect(user=None, password=None, host=IMAP_HOST):
    """Log in and select the inbox; returns the IMAP4_SSL handle.

    Raises ``ValueError`` when the settings are empty and
    ``imaplib.IMAP4.error`` on a refused login — the caller turns
    those into a non-zero command exit.
    """
    user = user if user is not None else settings.RECEIPTS_IMAP_USER
    password = (
        password
        if password is not None
        else settings.RECEIPTS_IMAP_PASSWORD
    )
    if not user or not password:
        raise ValueError(
            'RECEIPTS_IMAP_USER / RECEIPTS_IMAP_PASSWORD are not '
            'configured (see plan appendix A6).'
        )
    imap = imaplib.IMAP4_SSL(host)
    imap.login(user, password)
    typ, _ = imap.select(IMAP_MAILBOX)
    if typ != 'OK':
        try:
            imap.logout()
        except imaplib.IMAP4.error:
            pass
        raise imaplib.IMAP4.error(
            f'select {IMAP_MAILBOX} returned {typ}')
    return imap


def iter_messages(imap, scan_all=False, limit=None):
    """Yield ``(num, EmailMessage)`` for each matching message.

    ``scan_all=False`` searches ``UNSEEN`` (the incremental sync);
    ``True`` searches ``ALL`` for a manual backfill. ``limit``
    caps how many message bodies are fetched. A fetch that fails
    is logged and skipped — the message stays UNSEEN.
    """
    criteria = 'ALL' if scan_all else 'UNSEEN'
    typ, data = imap.search(None, criteria)
    if typ != 'OK' or not data or not data[0]:
        logger.info('imap search %s returned %s', criteria, typ)
        return
    nums = data[0].split()
    if limit is not None:
        nums = nums[:limit]
    for num in nums:
        # PEEK so a crashed run leaves the message UNSEEN for retry.
        try:
            typ, msg = imap.fetch(num, '(BODY.PEEK[])')
        except imaplib.IMAP4.error as e:
            # abort/error on one message must not kill the run.
            logger.error(
                'imap fetch raised for message %s: %s', num, e)
            continue
        if typ != 'OK' or not msg:
            logger.error('imap fetch failed for message %s', num)
            continue
        # The literal rides in a (attrs, bytes) tuple part; other
        # parts (e.g. a trailing flags string) are skipped.
        raw = next(
            (part[1] for part in msg if isinstance(part, tuple)),
            None,
        )
        if raw is None:
            logger.error(
                'imap fetch: no literal for message %s', num)
            continue
        yield num, BytesParser(policy=policy.default).parsebytes(raw)


def mark_seen(imap, num):
    """Store ``\\Seen`` — called after a message is fully
    processed, including when its failures were recorded as
    ``parse_error`` rows (poison mail must not retry forever)."""
    imap.store(num, '+FLAGS', '\\Seen')

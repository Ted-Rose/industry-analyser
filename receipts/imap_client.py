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
    imap.select(IMAP_MAILBOX)
    return imap


def iter_messages(imap, scan_all=False):
    """Yield ``(num, EmailMessage)`` for each matching message.

    ``scan_all=False`` searches ``UNSEEN`` (the incremental sync);
    ``True`` searches ``ALL`` for a manual backfill. A fetch that
    fails is logged and skipped — the message stays UNSEEN.
    """
    criteria = 'ALL' if scan_all else 'UNSEEN'
    typ, data = imap.search(None, criteria)
    if typ != 'OK' or not data or not data[0]:
        logger.info('imap search %s returned %s', criteria, typ)
        return
    for num in data[0].split():
        # PEEK so a crashed run leaves the message UNSEEN for retry.
        typ, msg = imap.fetch(num, '(BODY.PEEK[])')
        if typ != 'OK' or not msg or not msg[0]:
            logger.error('imap fetch failed for message %s', num)
            continue
        raw = msg[0][1]
        yield num, BytesParser(policy=policy.default).parsebytes(raw)


def mark_seen(imap, num):
    """Store ``\\Seen`` — only called after successful processing."""
    imap.store(num, '+FLAGS', '\\Seen')

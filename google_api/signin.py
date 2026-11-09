"""Resolve the Django user behind a Google sign-in.

The OIDC userinfo claims drive the resolution order: a stored
`google_sub` wins (stable identity that survives email changes),
then a Google-verified email links the existing account
case-insensitively, and only then is a new non-staff user with an
unusable password created. An unverified/missing email never
links or populates an existing account.
"""
import logging
import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError

logger = logging.getLogger('google_api')

# Django's username contract is ^\S+$ over the
# [@.+-_A-Za-z0-9] alphabet — whitespace is dropped, anything
# else outside it becomes a dash.
_WHITESPACE = re.compile(r'\s+')
_USERNAME_DISALLOWED = re.compile(r'[^A-Za-z0-9@.+\-_]')

# Leave headroom under the 150-char username limit for the -N
# collision suffix.
_USERNAME_BASE_MAX = 140


def _derive_username(userinfo):
    """Unique username from the verified email's local-part —
    `google-<sub>` when there is no verified email or the
    local-part sanitizes to nothing."""
    sub = userinfo.get('sub') or ''
    email = userinfo.get('email') or ''
    base = ''
    if email and userinfo.get('email_verified'):
        local = email.split('@', 1)[0]
        local = _WHITESPACE.sub('', local)
        base = _USERNAME_DISALLOWED.sub('-', local)[:_USERNAME_BASE_MAX]
    if not base:
        base = _USERNAME_DISALLOWED.sub(
            '-', f'google-{sub[:16]}'
        )[:_USERNAME_BASE_MAX]
    username = base
    suffix = 0
    User = get_user_model()
    while User.objects.filter(username__iexact=username).exists():
        suffix += 1
        username = f'{base}-{suffix}'
    return username


def resolve_google_user(userinfo):
    """The Django user for an OIDC userinfo payload.

    Order: (1) the user whose credentials row stores
    `google_sub == sub`; (2) with a verified email, the
    `email__iexact` match — linking the grant to that account;
    (3) a new non-staff user with an unusable password.
    """
    from .models import GoogleOAuthCredentials

    User = get_user_model()
    sub = userinfo.get('sub')
    email = userinfo.get('email') or ''
    verified_email = (
        email if email and userinfo.get('email_verified') else ''
    )

    if sub:
        row = (
            GoogleOAuthCredentials.objects.filter(google_sub=sub)
            .select_related('user')
            .first()
        )
        if row is not None:
            return row.user

    if verified_email:
        user = (
            User.objects.filter(email__iexact=verified_email)
            .order_by('id')
            .first()
        )
        if user is not None:
            existing = GoogleOAuthCredentials.objects.filter(
                user=user
            ).first()
            if (
                existing is not None
                and existing.google_sub
                and existing.google_sub != sub
            ):
                # One row per user — the update overwrites the
                # stored sub; surface the rebinding.
                logger.warning(
                    f'Rebinding Google identity for user '
                    f'{user.username}: stored google_sub '
                    f'{existing.google_sub} replaced by {sub}'
                )
            return user

    # _derive_username's exists() check races a concurrent
    # first sign-in deriving the same base: the loser
    # IntegrityErrors on the unique username column — re-
    # derive (the winner's row is visible now) and retry,
    # the same way views.py retries a contested google_sub.
    for attempt in range(3):
        user = User(
            username=_derive_username(userinfo),
            email=verified_email,
            is_staff=False,
        )
        user.set_unusable_password()
        try:
            user.save()
        except IntegrityError:
            if attempt == 2:
                raise
            continue
        logger.info(
            f'Created user {user.username} for Google sub {sub}'
        )
        return user

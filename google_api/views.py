import logging
import os
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from google_auth_oauthlib.flow import InstalledAppFlow
from oauthlib.oauth2.rfc6749.errors import (
    AccessDeniedError,
    InvalidGrantError,
    MissingCodeError,
)

from .utils import GOOGLE_TASKS_SCOPES, google_auth

logger = logging.getLogger('google_api')


@login_required
def login_view(request):
    """
    Google OAuth entry point — redirects to the consent screen
    (or straight back when usable credentials already exist).
    """
    next_url = request.GET.get('next', '/')
    request.session['oauth_redirect_url'] = next_url

    if not getattr(settings, 'GOOGLE_APP_SECRETS_PATH', ''):
        return HttpResponse(
            'Google OAuth is not configured on this install.',
            status=503,
        )

    auth = google_auth(scopes=GOOGLE_TASKS_SCOPES, user=request.user)

    if isinstance(auth, dict) and 'authorization_url' in auth:
        request.session['state'] = auth['state']
        request.session['oauth_scopes'] = auth['scopes']
        return redirect(auth['authorization_url'])

    # Already authenticated, redirect to next URL
    return redirect(next_url)


@login_required
def callback(request):
    """
    OAuth callback handler.
    Saves credentials to database for long-term storage.
    """
    from datetime import datetime, timezone as dt_timezone

    from google_api.models import GoogleOAuthCredentials

    scopes = request.session.pop('oauth_scopes', GOOGLE_TASKS_SCOPES)
    client_secrets_path = getattr(
        settings, 'GOOGLE_APP_SECRETS_PATH', ''
    )

    redirect_uri = f"{settings.BASE_URL}/google/callback"
    flow = InstalledAppFlow.from_client_secrets_file(
        client_secrets_path,
        scopes,
        redirect_uri=redirect_uri
    )
    try:
        flow.fetch_token(
            authorization_response=request.build_absolute_uri()
        )
    except (
        AccessDeniedError,
        InvalidGrantError,
        MissingCodeError,
    ) as e:
        # Auth code already consumed or expired (e.g. the callback
        # URL was reloaded), consent denied (?error=access_denied),
        # or no code at all (back button / direct hit) — restart the
        # OAuth flow instead of a 500.
        logger.warning(
            f'OAuth callback failed ({e.error}); '
            'redirecting to login'
        )
        login_url = reverse('google_api:login')
        next_url = request.session.get('oauth_redirect_url')
        if next_url:
            login_url = f'{login_url}?next={quote(next_url)}'
        return redirect(login_url)
    credentials = flow.credentials

    # The flow attaches to an already-authenticated Django user —
    # it must never create or re-authenticate one.
    user = request.user

    # Ensure expiry is timezone-aware
    expiry = credentials.expiry
    expiry_is_naive = (
        expiry and (
            expiry.tzinfo is None or
            expiry.tzinfo.utcoffset(expiry) is None
        )
    )
    if expiry_is_naive:
        logger.warning(
            'Callback received naive expiry datetime, '
            'converting to UTC'
        )
        expiry = expiry.replace(tzinfo=dt_timezone.utc)

    GoogleOAuthCredentials.objects.update_or_create(
        user=user,
        defaults={
            'access_token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_expiry': expiry,
            'scopes': list(credentials.scopes or []),
        }
    )
    logger.info(
        f'Saved credentials for user {user.username} '
        f'with scopes: {list(credentials.scopes or [])}'
    )

    redirect_url = request.session.pop('oauth_redirect_url', '/')

    return redirect(redirect_url)

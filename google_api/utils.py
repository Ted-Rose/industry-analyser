import json
import logging
import os
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger('google_api')

# We request tokens with include_granted_scopes='true' (incremental
# authorization), so Google may return more scopes than this flow asked
# for (e.g. a previously granted scope). Without this, oauthlib
# raises a Warning on the scope change and the callback fails.
os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')

# Allow HTTP for local development (ONLY for development!)
# In production, always use HTTPS
os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

# The only scope this project requests — the news digest creates
# one Google task per build. openid/userinfo scopes are not needed:
# the callback attaches credentials to the logged-in Django user.
GOOGLE_TASKS_SCOPES = [
    'https://www.googleapis.com/auth/tasks',
]


def get_user_credentials(user, scopes=None):
    """
    Get Google OAuth credentials for a user from the database.

    Args:
        user: Django User object
        scopes: Optional list of required scopes

    Returns:
        Credentials object if valid, None if missing or invalid
    """
    from google_api.models import GoogleOAuthCredentials

    try:
        oauth_creds = GoogleOAuthCredentials.objects.get(user=user)

        # Check if required scopes are granted
        if scopes and not oauth_creds.has_all_scopes(scopes):
            logger.warning(
                f'User {user.username} missing required scopes. '
                f'Required: {scopes}, Granted: {oauth_creds.scopes}'
            )
            return None

        client_secrets_path = getattr(
            settings, 'GOOGLE_APP_SECRETS_PATH', ''
        )
        with open(client_secrets_path, 'r') as file:
            data = json.load(file)

        client_id = data.get('web', {}).get('client_id')
        client_secret = data.get('web', {}).get('client_secret')
        token_uri = data.get('web', {}).get('token_uri')

        # Google Auth library expects NAIVE UTC datetimes, not aware!
        # Convert timezone-aware datetime to naive UTC
        token_expiry = oauth_creds.token_expiry
        if token_expiry:
            is_aware = (
                token_expiry.tzinfo is not None and
                token_expiry.tzinfo.utcoffset(token_expiry) is not None
            )
            if is_aware:
                logger.info(
                    f'Converting timezone-aware to naive UTC for '
                    f'user {user.username}. tzinfo={token_expiry.tzinfo}'
                )
                # Convert to UTC and remove timezone info
                token_expiry = token_expiry.astimezone(dt_timezone.utc)
                token_expiry = token_expiry.replace(tzinfo=None)
            else:
                logger.info(
                    f'token_expiry already naive for user '
                    f'{user.username}'
                )

        tzinfo_str = (
            token_expiry.tzinfo if token_expiry else None
        )
        logger.info(
            f'Creating Credentials for {user.username} with '
            f'expiry={token_expiry}, tzinfo={tzinfo_str}'
        )

        creds = Credentials(
            token=oauth_creds.access_token,
            refresh_token=oauth_creds.refresh_token,
            client_secret=client_secret,
            client_id=client_id,
            token_uri=token_uri,
            scopes=oauth_creds.scopes,
            expiry=token_expiry,
        )

        # Double-check: creds.expiry should be naive UTC
        creds_is_aware = (
            creds.expiry and
            creds.expiry.tzinfo is not None and
            creds.expiry.tzinfo.utcoffset(creds.expiry) is not None
        )
        if creds_is_aware:
            logger.warning(
                'Credentials object has timezone-aware expiry! '
                f'Converting to naive UTC. expiry={creds.expiry}'
            )
            # Convert to naive UTC
            creds.expiry = creds.expiry.astimezone(dt_timezone.utc)
            creds.expiry = creds.expiry.replace(tzinfo=None)

        # Refresh if expired - wrap in try/except to catch timezone errors
        try:
            is_expired = creds.expired
        except TypeError as e:
            if 'offset-naive and offset-aware' in str(e):
                logger.error(
                    f'TypeError when checking creds.expired: {e}. '
                    f'creds.expiry={creds.expiry}, '
                    f'tzinfo={creds.expiry.tzinfo if creds.expiry else None}'
                )
                # Convert to naive UTC and try again
                if creds.expiry:
                    if creds.expiry.tzinfo:
                        creds.expiry = creds.expiry.astimezone(
                            dt_timezone.utc
                        )
                    creds.expiry = creds.expiry.replace(tzinfo=None)
                    is_expired = creds.expired
                else:
                    is_expired = True
            else:
                raise

        if is_expired and creds.refresh_token:
            logger.info(f'Refreshing expired token for user {user.username}')
            try:
                creds.refresh(Request())
            except RefreshError as e:
                logger.warning(
                    f'Token refresh failed for user {user.username}: '
                    f'{e}. Re-authentication required.'
                )
                return None

            # Update database with new token
            # Google returns naive UTC, Django needs timezone-aware
            refreshed_expiry = creds.expiry
            if refreshed_expiry:
                if refreshed_expiry.tzinfo is None:
                    # Naive datetime from Google, assume UTC
                    refreshed_expiry = refreshed_expiry.replace(
                        tzinfo=dt_timezone.utc
                    )

            oauth_creds.access_token = creds.token
            oauth_creds.token_expiry = refreshed_expiry
            oauth_creds.save()
            logger.info(f'Token refreshed for user {user.username}')

        return creds

    except GoogleOAuthCredentials.DoesNotExist:
        logger.info(f'No credentials found for user {user.username}')
        return None


def google_auth(scopes=None, user=None):
    """
    Get or create Google OAuth credentials.

    Args:
        scopes: List of OAuth scopes to request
        user: Django User object

    Returns:
        Credentials object or dict with authorization_url if reauth needed
    """
    if scopes is None:
        scopes = GOOGLE_TASKS_SCOPES
    logger.info(f'google_auth called with scopes: {scopes}')

    client_secrets_path = getattr(
        settings, 'GOOGLE_APP_SECRETS_PATH', ''
    )

    # Try to get credentials from database if user is provided
    if user and user.is_authenticated:
        db_creds = get_user_credentials(user, scopes)
        if db_creds and db_creds.valid:
            return db_creds

    if not settings.BASE_URL:
        # Empty BASE_URL produces a relative redirect_uri
        # ('/google/callback') which Google rejects with an
        # opaque 'invalid_request' error.
        raise ImproperlyConfigured(
            'BASE_URL is not set - configure BASE_URL in .env '
            'with the full site URL, e.g. https://example.com'
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        client_secrets_path,
        scopes,
        redirect_uri=f"{settings.BASE_URL}/google/callback"
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    return {
        "authorization_url": authorization_url,
        "state": state,
        "scopes": scopes
    }


def build_google_service(service_name, version, user=None, scopes=None):
    """
    Generic service builder for Google APIs.
    Args:
        service_name: e.g., 'tasks'
        version: e.g., 'v1'
        user: Django User object
        scopes: list of OAuth scopes
    Returns:
        Google API service object or auth dict if reauth needed
    """
    credentials = google_auth(scopes, user=user)
    if isinstance(credentials, dict) and 'authorization_url' in credentials:
        return credentials
    return build(service_name, version, credentials=credentials)

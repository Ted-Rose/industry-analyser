import logging
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from google_auth_oauthlib.flow import InstalledAppFlow
from oauthlib.oauth2 import OAuth2Error
from requests.exceptions import RequestException

from .signin import resolve_google_user
from .utils import (
    GOOGLE_SIGNIN_SCOPES,
    GOOGLE_TASKS_SCOPES,
    USERINFO_ENDPOINT,
    google_auth,
)

logger = logging.getLogger('google_api')

# Session keys that carry one OAuth round-trip — discarded
# together on a state mismatch.
_OAUTH_SESSION_KEYS = (
    'state',
    'oauth_scopes',
    'oauth_code_verifier',
    'oauth_redirect_url',
    'oauth_flow',
)


def _sanitize_next(value):
    """Only a same-origin relative path may be the post-OAuth
    redirect — '/' prefix but not '//' and no backslashes (a
    '/\\host' URL normalizes to '//host' in the browser).
    Anything else falls back to '/'."""
    if (
        isinstance(value, str)
        and value.startswith('/')
        and not value.startswith('//')
        and '\\' not in value
    ):
        return value
    return '/'


def _stash_flow(request, auth, flow_mode, next_url):
    """Session state one OAuth round-trip needs: the CSRF
    `state`, the PKCE verifier, the granted-scope list, which
    flow launched it and where to land afterwards."""
    request.session['state'] = auth['state']
    request.session['oauth_scopes'] = auth['scopes']
    request.session['oauth_code_verifier'] = auth.get(
        'code_verifier'
    )
    request.session['oauth_flow'] = flow_mode
    request.session['oauth_redirect_url'] = next_url


def _not_configured():
    return HttpResponse(
        'Google OAuth is not configured on this install.',
        status=503,
    )


def _login_redirect(next_url=None):
    """The /accounts/login/ bounce, carrying the sanitized
    `next` the way a denied/failed sign-in restart should."""
    login_url = settings.LOGIN_URL
    if next_url:
        login_url = f'{login_url}?next={quote(next_url)}'
    return redirect(login_url)


@login_required
def login_view(request):
    """
    Google OAuth entry point — redirects to the consent screen
    (or straight back when usable credentials already exist).
    """
    next_url = _sanitize_next(request.GET.get('next', '/'))
    request.session['oauth_redirect_url'] = next_url

    if not getattr(settings, 'GOOGLE_APP_SECRETS_PATH', ''):
        return _not_configured()

    auth = google_auth(scopes=GOOGLE_TASKS_SCOPES, user=request.user)

    if isinstance(auth, dict) and 'authorization_url' in auth:
        _stash_flow(request, auth, 'connect', next_url)
        return redirect(auth['authorization_url'])

    # Already authenticated, redirect to next URL
    return redirect(next_url)


def signin_view(request):
    """
    Public "Sign in with Google" entry point — like login_view
    but the callback resolves (or creates) and logs in the
    Django user from the OIDC userinfo claims. `?tasks=1` adds
    the auth/tasks scope to the same consent; with no `next`
    it also defaults the landing to the digest subscribe page.
    """
    next_param = request.GET.get('next')
    if next_param is None and request.GET.get('tasks') == '1':
        next_url = '/news/preferences/?subscribe=1'
    else:
        next_url = _sanitize_next(next_param)

    if not getattr(settings, 'GOOGLE_APP_SECRETS_PATH', ''):
        return _not_configured()

    scopes = list(GOOGLE_SIGNIN_SCOPES)
    if request.GET.get('tasks') == '1':
        scopes += GOOGLE_TASKS_SCOPES

    # Never pass request.user: sign-in must always reach the
    # consent screen — the Google identity, not the current
    # session, decides who lands logged in. With no user to look
    # up, google_auth can only return the auth dict (or raise);
    # the stored-credentials early return needs a user.
    auth = google_auth(scopes=scopes)

    if isinstance(auth, dict) and 'authorization_url' in auth:
        _stash_flow(request, auth, 'signin', next_url)
        return redirect(auth['authorization_url'])


def _build_flow(request, scopes):
    """The callback leg's Flow — rebuilt per request, so the
    PKCE verifier the start view's Flow generated must ride
    the session or the token exchange fails invalid_grant."""
    client_secrets_path = getattr(
        settings, 'GOOGLE_APP_SECRETS_PATH', ''
    )
    redirect_uri = f"{settings.BASE_URL}/google/callback"
    flow = InstalledAppFlow.from_client_secrets_file(
        client_secrets_path,
        scopes,
        redirect_uri=redirect_uri
    )
    flow.code_verifier = request.session.pop(
        'oauth_code_verifier', None
    )
    return flow


def _fetch_userinfo(flow):
    """OIDC userinfo via the just-issued token — the dict on
    success, None on a non-200/transport/JSON failure."""
    try:
        response = flow.authorized_session().get(USERINFO_ENDPOINT)
        if response.status_code != 200:
            logger.warning(
                f'Userinfo answered {response.status_code}'
            )
            return None
        return response.json()
    except Exception as e:
        logger.warning(f'Userinfo fetch failed: {e}')
        return None


def callback(request):
    """
    Shared OAuth callback for both flow modes, dispatched on
    the session-stashed `oauth_flow` key: 'connect' (default —
    attach the grant to the already-authenticated user, today's
    /google/login behavior) or 'signin' (resolve/create the
    Django user from the OIDC userinfo and log them in).
    """
    from datetime import timezone as dt_timezone

    from google_api.models import GoogleOAuthCredentials

    flow_mode = request.session.pop('oauth_flow', 'connect')
    start_url = reverse(
        'google_api:signin' if flow_mode == 'signin'
        else 'google_api:login'
    )
    next_url = request.session.get('oauth_redirect_url')

    # Login-CSRF: the callback must continue a flow this session
    # started — a non-empty session-stashed state must match the
    # query param before any token exchange. "Both sides empty"
    # is NOT a match: fetch_token's own state check is inert on a
    # rebuilt Flow, so a bare ?code= hit on a session that never
    # started a flow would otherwise reach the token exchange.
    stashed_state = request.session.pop('state', None)
    if (
        not stashed_state
        or request.GET.get('state') != stashed_state
    ):
        logger.warning(
            'OAuth callback state mismatch; restarting flow'
        )
        for key in _OAUTH_SESSION_KEYS:
            request.session.pop(key, None)
        return redirect(start_url)

    if flow_mode == 'connect' and not request.user.is_authenticated:
        # The connect branch keeps the old @login_required
        # contract — anonymous hits bounce to the Django login.
        # `next` carries the bare callback path: echoing the full
        # query string would copy the auth code into the login
        # URL (browser history, referers). The stashed round-trip
        # is over either way — discard its leftovers like a state
        # mismatch would.
        for key in _OAUTH_SESSION_KEYS:
            request.session.pop(key, None)
        return redirect(
            f'{settings.LOGIN_URL}?next={quote(request.path)}'
        )

    scopes = request.session.pop('oauth_scopes', GOOGLE_TASKS_SCOPES)
    flow = _build_flow(request, scopes)
    try:
        flow.fetch_token(
            authorization_response=request.build_absolute_uri()
        )
    except (OAuth2Error, RequestException) as e:
        # OAuth2Error covers the protocol failures — auth code
        # already consumed or expired (e.g. the callback URL was
        # reloaded), consent denied (?error=access_denied), no
        # code at all (back button / direct hit), a token
        # response missing access_token; RequestException covers
        # the token endpoint being unreachable. All restart the
        # OAuth flow instead of a 500.
        detail = getattr(e, 'error', None) or e
        logger.warning(
            f'OAuth callback failed ({detail}); '
            'redirecting to login'
        )
        if flow_mode == 'signin':
            return _login_redirect(next_url)
        restart_url = reverse('google_api:login')
        if next_url:
            restart_url = f'{restart_url}?next={quote(next_url)}'
        return redirect(restart_url)
    credentials = flow.credentials

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

    # Read before auth_login — logging a different user in
    # flushes the session.
    redirect_url = request.session.pop('oauth_redirect_url', '/')
    defaults = {
        'access_token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_expiry': expiry,
        'scopes': list(credentials.scopes or []),
    }

    if flow_mode == 'signin':
        userinfo = _fetch_userinfo(flow)
        sub = (userinfo or {}).get('sub')
        if not sub:
            # No session, no credentials row — the restart is
            # a clean bounce back to the login page.
            logger.warning(
                'Sign-in callback got no usable userinfo'
            )
            return _login_redirect(next_url)
        user = resolve_google_user(userinfo)
        if not user.is_active:
            # authenticate() would reject the account via
            # user_can_authenticate — this bypass must apply
            # the same bar or a staff-deactivated user keeps
            # signing in through Google.
            logger.warning(
                f'Google sign-in denied for deactivated '
                f'user {user.username}'
            )
            return _login_redirect(next_url)
        auth_login(
            request, user,
            backend='accounts.backends.CaseInsensitiveAuthBackend',
        )
        defaults['google_sub'] = sub
    else:
        # Connect attaches the grant to the already-authenticated
        # Django user — it must never create or re-authenticate
        # one. google_sub rides along best-effort: only call
        # userinfo when the grant carries an OIDC scope, else a
        # tasks-only connect 401s on every run.
        user = request.user
        granted = set(credentials.scopes or [])
        if granted & set(GOOGLE_SIGNIN_SCOPES):
            userinfo = _fetch_userinfo(flow)
            if userinfo and userinfo.get('sub'):
                defaults['google_sub'] = userinfo['sub']

    sub = defaults.get('google_sub')
    if sub and (
        GoogleOAuthCredentials.objects
        .filter(google_sub=sub)
        .exclude(user_id=user.pk)
        .exists()
    ):
        # A google_sub belongs to exactly one user — keep this
        # user's grant but leave the identity link on the row
        # that already holds it; writing it anyway would hit the
        # unique column's IntegrityError and clobber the other
        # account's link.
        logger.warning(
            f'google_sub {sub} is already linked to another '
            f'user; saving {user.username}\'s grant without '
            'rebinding it'
        )
        defaults.pop('google_sub')

    try:
        GoogleOAuthCredentials.objects.update_or_create(
            user=user,
            defaults=defaults,
        )
    except IntegrityError:
        # The existence check above races a concurrent callback:
        # the loser hits the unique google_sub column mid-write.
        # Keep this user's grant — retry with the contested link
        # left off, exactly like the pre-check branch does.
        logger.warning(
            f'google_sub {sub} claimed by a concurrent '
            f'callback; retrying {user.username}\'s grant '
            'without rebinding it'
        )
        defaults.pop('google_sub', None)
        GoogleOAuthCredentials.objects.update_or_create(
            user=user,
            defaults=defaults,
        )
    logger.info(
        f'Saved credentials for user {user.username} '
        f'with scopes: {list(credentials.scopes or [])}'
    )

    return redirect(redirect_url)

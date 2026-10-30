"""django-ninja router for session auth (mounted at
/api/accounts/).

register/ and login/ are anonymous ops (auth=None) that enforce
CSRF inline via ninja's check_csrf — the same check
APIKeyCookie-based auth handlers run. A @csrf_protect decorator
cannot be used here: decorator_from_middleware post-processes the
view's return value and ninja endpoints return (status, dict)
tuples, not HttpResponses (the /accounts/ shell guarantees a
csrftoken cookie via ensure_csrf_cookie). logout/ keeps the
default django_auth — anonymous logout correctly 401s. me/ is
public and never 401s so clients can probe auth state without
triggering the shared client's login-redirect path.

Credential rules mirror the Bible Research users app: usernames
match ^\\S+$ and are unique case-insensitively (required for the
iexact login lookup to stay deterministic), email is optional but
iexact-unique when provided, passwords run every configured
AUTH_PASSWORD_VALIDATORS against the unsaved user, and login
failures are one uniform invalid_credentials 401 — no user
enumeration.
"""
import re
from typing import Optional

from django.contrib.auth import (
    authenticate,
    login as auth_login,
    logout as auth_logout,
)
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import (
    validate_password,
)
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.db import IntegrityError
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.utils import check_csrf
from pydantic import Field

from industry_analyser.api import ApiHttpError

router = Router()

# Usernames may not contain whitespace — the iexact login backend
# already treats the namespace loosely, and spaced names serve no
# legitimate purpose.
_NO_WHITESPACE_RE = re.compile(r'^\S+$')

_AUTH_BACKEND = 'accounts.backends.CaseInsensitiveAuthBackend'


class UserOut(Schema):
    id: int
    username: str
    email: str
    is_staff: bool


class RegisterIn(Schema):
    # Length caps mirror the User columns (username 150, email
    # 254) — without them an over-long value sails past schema
    # validation and create_user raises a Postgres DataError
    # (not IntegrityError) → 500.
    username: str = Field(max_length=150)
    password: str = Field(max_length=1024)
    password_confirm: str = Field(max_length=1024)
    email: str = Field(default='', max_length=254)


class LoginIn(Schema):
    username: str = Field(max_length=150)
    password: str = Field(max_length=1024)


class AuthOut(Schema):
    user: UserOut


class MeOut(Schema):
    user: Optional[UserOut] = None
    is_authenticated: bool


class SuccessOut(Schema):
    success: bool


def _enforce_csrf(request):
    """The CSRF enforcement cookie-auth handlers get for free, run
    inline for auth=None ops — same 403 HttpError SessionAuth
    raises, so the body stays in the uniform error contract.

    Ordering note: ninja parses/validates the request body before
    the view callable runs, so this check happens after body
    parsing (SessionAuth would run it during auth, before parse).
    A bad-CSRF request with a malformed body therefore 422s where
    a SessionAuth endpoint would 403 — cosmetic only."""
    if check_csrf(request) is not None:
        raise HttpError(403, 'CSRF check Failed')


@router.post('/register/', auth=None, response={201: AuthOut})
def register(request, payload: RegisterIn):
    _enforce_csrf(request)
    username = payload.username
    email = (payload.email or '').strip()
    if not _NO_WHITESPACE_RE.fullmatch(username or ''):
        raise ApiHttpError(
            400, 'Username may not contain whitespace.',
            code='invalid_username',
        )
    # Login resolves usernames with iexact, so uniqueness must be
    # case-insensitive too — 'Alice'/'alice' coexisting would make
    # auth resolve nondeterministically.
    if User.objects.filter(username__iexact=username).exists():
        raise ApiHttpError(
            400, 'A user with this username already exists.',
            code='username_taken',
        )
    if email and User.objects.filter(email__iexact=email).exists():
        raise ApiHttpError(
            400, 'A user with this email already exists.',
            code='email_taken',
        )
    if payload.password != payload.password_confirm:
        raise ApiHttpError(
            400, "Password fields didn't match.",
            code='password_mismatch',
        )
    # An unsaved User lets the similarity validator compare the
    # password against username/email before the row exists.
    try:
        validate_password(
            payload.password,
            user=User(username=username, email=email),
        )
    except DjangoValidationError as exc:
        raise ApiHttpError(
            400, ' '.join(exc.messages), code='weak_password',
        )
    try:
        user = User.objects.create_user(
            username=username, email=email,
            password=payload.password,
        )
    except IntegrityError:
        # A uniqueness check → insert race still hits the DB
        # constraint — surface a 400, never a 500.
        raise ApiHttpError(
            400, 'A user with this username already exists.',
            code='username_taken',
        )
    # Passing the backend keeps login() deterministic even if a
    # second AUTHENTICATION_BACKENDS entry is added later.
    auth_login(request, user, backend=_AUTH_BACKEND)
    return 201, {'user': user}


@router.post('/login/', auth=None, response=AuthOut)
def session_login(request, payload: LoginIn):
    _enforce_csrf(request)
    user = authenticate(
        request,
        username=payload.username,
        password=payload.password,
    )
    if user is None:
        # One uniform failure for unknown usernames, wrong
        # passwords and inactive accounts — no user enumeration.
        raise ApiHttpError(
            401, 'Invalid username or password.',
            code='invalid_credentials',
        )
    auth_login(request, user)
    return {'user': user}


@router.post('/logout/', response=SuccessOut)
def session_logout(request):
    auth_logout(request)
    return {'success': True}


@router.get('/me/', auth=None, response=MeOut)
def me(request):
    """Auth-state probe — always 200. A 401 here would trigger
    apiFetch's navigate-to-login_url path, redirecting the very
    page that asked."""
    if request.user.is_authenticated:
        return {'user': request.user, 'is_authenticated': True}
    return {'user': None, 'is_authenticated': False}

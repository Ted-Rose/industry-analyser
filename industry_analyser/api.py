"""Shared django-ninja API layer (Stage 0 of the React rewrite).

One NinjaAPI mounted at /api/ — apps register routers on it in
industry_analyser/urls.py (e.g. api.add_router('/vacancies/', router)
→ /api/vacancies/...). Auth is ninja's django_auth (session cookie,
CSRF enforced on unsafe methods) with JSON 401s instead of redirects.
Public read endpoints opt out per-op with auth=None.
"""
from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, JsonResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError
from ninja.security import django_auth

api = NinjaAPI(
    title='industry-analyser API',
    version='0.1.0',
    auth=django_auth,
    # Schema is committed in-repo (frontend/openapi.json) and type
    # generation uses `manage.py export_openapi_schema`, so
    # restricting the served docs/spec to staff does not affect that
    # workflow — an open /api/docs would expose the whole schema.
    docs_decorator=staff_member_required,
)


class ApiHttpError(HttpError):
    """HttpError carrying a stable `code` slug the SPA can map onto a
    translated/user-facing message; `detail` stays in the body as the
    English fallback. When no `code` is supplied the emitted body
    falls back to the generic `error` status slug.
    """

    def __init__(self, status_code, message, code=None, params=None):
        super().__init__(status_code, message)
        self.code = code
        self.params = params


_ERROR_SLUGS = {
    400: 'bad_request',
    401: 'unauthenticated',
    403: 'forbidden',
    404: 'not_found',
    405: 'method_not_allowed',
    409: 'conflict',
    422: 'validation_error',
    429: 'throttled',
    500: 'server_error',
    502: 'upstream_error',
}


def error_slug(status_code):
    """Stable machine-readable slug for the uniform error shape."""
    return _ERROR_SLUGS.get(status_code, 'error')


# API mounts whose SPA page lives somewhere other than /<app>/:
# /api/<app>/<sub> → the mapped path. 'dashboard' mounts at the site
# root, so /api/dashboard/... 401s must send the user back to '/', not
# '/dashboard/'.
SPA_BASES = {'dashboard': '/'}


def spa_url_for(request):
    """Map an /api/<app>/<sub> request URL onto the SPA page the user
    should return to after auth. API paths are JSON endpoints, not
    pages, so `next`/`login_url` must never point back at them —
    /api/vacancies/keywords/?x=y → /vacancies/keywords/?x=y."""
    path = request.path
    prefix = '/api/'
    if path.startswith(prefix):
        app, _, sub = path[len(prefix):].partition('/')
        if app in SPA_BASES:
            path = SPA_BASES[app] + sub
        else:
            path = f'/{app}/{sub}'
    if request.GET:
        path = f'{path}?{request.GET.urlencode()}'
    return path


@api.exception_handler(AuthenticationError)
def _on_unauthenticated(request, exc):
    """Session auth failed → JSON 401, never a login redirect."""
    return api.create_response(request, {
        'error': 'unauthenticated',
        'login_url': (
            f'/admin/login/'
            f'?{urlencode({"next": spa_url_for(request)})}'
        ),
    }, status=401)


@api.exception_handler(Http404)
def _on_not_found(request, exc):
    return api.create_response(request, {
        'error': 'not_found',
        'detail': str(exc) or 'Not Found',
    }, status=404)


@api.exception_handler(ValidationError)
def _on_validation_error(request, exc):
    """Schema validation failures keep the uniform {error, detail}
    contract instead of ninja's bare {detail: [...]} shape."""
    return api.create_response(request, {
        'error': 'validation_error',
        'detail': exc.errors,
    }, status=422)


@api.exception_handler(HttpError)
def _on_http_error(request, exc):
    # `error` is always the machine-readable status slug; `code` adds
    # a more specific catalog key when the endpoint set one
    # (ApiHttpError). errorDetail() prefers `code` + `params`.
    body = {
        'error': error_slug(exc.status_code),
        'detail': str(exc),
        'code': getattr(exc, 'code', None) or error_slug(
            exc.status_code
        ),
    }
    params = getattr(exc, 'params', None)
    if params:
        body['params'] = params
    return api.create_response(request, body, status=exc.status_code)

from django.contrib import admin

from google_api.models import GoogleOAuthCredentials


@admin.register(GoogleOAuthCredentials)
class GoogleOAuthCredentialsAdmin(admin.ModelAdmin):
    # Tokens are never rendered: the change form lists only the
    # fields below and every one is read-only.
    _SAFE_FIELDS = (
        'user', 'google_sub', 'token_expiry', 'scopes',
        'created_at', 'updated_at',
    )
    list_display = _SAFE_FIELDS
    fields = _SAFE_FIELDS
    readonly_fields = _SAFE_FIELDS
    list_filter = ('created_at', 'updated_at')
    search_fields = ('user__username', 'user__email')

    def has_add_permission(self, request):
        return False

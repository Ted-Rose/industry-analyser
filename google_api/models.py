from django.conf import settings
from django.db import models
from django.utils import timezone


class GoogleOAuthCredentials(models.Model):
    """
    Stores Google OAuth2 credentials for each user.
    Supports long-lasting refresh tokens for the Tasks API.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='google_credentials'
    )
    access_token = models.TextField(
        help_text='Current access token (expires in ~1 hour)'
    )
    refresh_token = models.TextField(
        help_text='Refresh token (long-lasting, used to get new access tokens)'
    )
    token_expiry = models.DateTimeField(
        help_text='When the access token expires'
    )
    scopes = models.JSONField(
        default=list,
        help_text='List of granted OAuth scopes'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'google_oauth_credentials'
        verbose_name = 'Google OAuth Credentials'
        verbose_name_plural = 'Google OAuth Credentials'

    def __str__(self):
        return f'Google credentials for {self.user.username}'

    def is_expired(self):
        """Check if the access token has expired."""
        if not self.token_expiry:
            return True
        return timezone.now() >= self.token_expiry

    def has_scope(self, scope):
        """Check if a specific scope is granted."""
        return scope in self.scopes

    def has_all_scopes(self, required_scopes):
        """Check if all required scopes are granted."""
        return all(scope in self.scopes for scope in required_scopes)

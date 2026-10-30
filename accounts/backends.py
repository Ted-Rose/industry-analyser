"""Case-insensitive username authentication backend.

Mirrors the Bible Research users app: registered as the sole
AUTHENTICATION_BACKENDS entry so session login (the
/api/accounts/ endpoints and the admin) resolves usernames
case-insensitively — a user registered as 'Alice' logs in as
'alice'.
"""
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class CaseInsensitiveAuthBackend(ModelBackend):
    """Authenticate with a case-insensitive username lookup.

    Rows that differ only by case can coexist in the database
    (uniqueness is enforced app-side at registration), so an
    iexact hit prefers the exact-case match; a missing user still
    runs the hasher once to keep the timing profile flat.
    """

    def authenticate(
        self, request, username=None, password=None, **kwargs
    ):
        if username is None or password is None:
            return None

        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            # Keep the timing close to the found-user path so
            # username probing stays expensive.
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            matches = User.objects.filter(username__iexact=username)
            # order_by('id') keeps the fallback deterministic —
            # an unordered .first() follows whatever the DB
            # planner happens to return.
            user = next(
                (u for u in matches if u.username == username),
                matches.order_by('id').first(),
            )

        if (
            user.check_password(password)
            and self.user_can_authenticate(user)
        ):
            return user
        return None

"""Best-effort Google Tasks hook for the daily news digest —
one task per enabled NewsDigestSubscription, inserted into
each subscriber's own Google task list."""
import logging

from django.conf import settings
from googleapiclient.discovery import build

from google_api.utils import GOOGLE_TASKS_SCOPES, get_user_credentials

from .models import NewsDigestSubscription, NewsDigestTask
from .preferences import ordered_story_articles

logger = logging.getLogger('news')


def _feature_enabled():
    # Empty client secrets disables the integration entirely
    # (same convention as GCS_AUDIO_BUCKET). Recipients come
    # from enabled subscriptions, not a settings username.
    return bool(getattr(settings, 'GOOGLE_OAUTH_CLIENT_JSON', ''))


def _resolve_task_list_id(service):
    """Opaque id of the task list titled GOOGLE_TASKS_LIST_TITLE
    (case-insensitive match; auto-created when absent)."""
    title = settings.GOOGLE_TASKS_LIST_TITLE
    wanted = title.strip().lower()
    page_token = None
    while True:
        kwargs = {'pageToken': page_token} if page_token else {}
        response = service.tasklists().list(**kwargs).execute()
        for task_list in response.get('items', []):
            if task_list.get('title', '').strip().lower() == wanted:
                return task_list['id']
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    created = service.tasklists().insert(
        body={'title': title}
    ).execute()
    logger.info('Created Google task list %r', title)
    return created['id']


def _record_failure(digest, user, error):
    try:
        NewsDigestTask.objects.update_or_create(
            digest=digest,
            user=user,
            defaults={'status': 'failed', 'error': str(error)},
        )
    except Exception:
        logger.exception(
            'Could not record Google task failure for digest %s '
            'user %s',
            digest.date,
            user.username,
        )


def _task_body(digest, user):
    """The insert body for one subscriber — notes carry the
    digest link plus each headline with the article from the
    subscriber's own most-preferred covering outlet."""
    date_str = digest.date.isoformat()
    link_base = getattr(
        settings, 'GOOGLE_TASKS_LINK_BASE_URL', settings.BASE_URL
    )
    notes = [f'{link_base}/news/{date_str}/', '']
    for item in digest.items.order_by('rank').select_related('story'):
        # The subscriber's most preferred outlet that covered the
        # story, in brackets after the headline.
        article = next(
            iter(ordered_story_articles(item.story, user)), None
        )
        src = f' ({article.link})' if article else ''
        notes.append(f'{item.rank}. {item.headline}{src}')
    # No 'due' — the task is a pointer at the digest page, not a
    # deadline (explicit product decision).
    return {
        'title': f'News digest {date_str}',
        'notes': '\n'.join(notes),
    }


def _run_for_user(digest, user):
    """One subscriber's attempt. A 'created' link row is the
    rebuild dedup; a 'failed'/'pending' row is retried."""
    if NewsDigestTask.objects.filter(
        digest=digest, user=user, status='created'
    ).exists():
        return
    link, _ = NewsDigestTask.objects.update_or_create(
        digest=digest,
        user=user,
        defaults={'status': 'pending', 'error': ''},
    )
    creds = get_user_credentials(user, GOOGLE_TASKS_SCOPES)
    if creds is None:
        msg = (
            f'No Google credentials for user {user.username!r} — '
            f're-authorize at {settings.BASE_URL}/google/login'
        )
        logger.warning(msg)
        link.status = 'failed'
        link.error = msg
        link.save(update_fields=['status', 'error', 'updated_at'])
        return

    service = build('tasks', 'v1', credentials=creds)
    task_list_id = _resolve_task_list_id(service)
    created = service.tasks().insert(
        tasklist=task_list_id,
        body=_task_body(digest, user),
    ).execute()

    link.task_id = created['id']
    link.task_list_id = task_list_id
    link.status = 'created'
    link.save(
        update_fields=['task_id', 'task_list_id', 'status', 'updated_at']
    )
    logger.info(
        'Google task %s created for digest %s user %s',
        created['id'],
        digest.date.isoformat(),
        user.username,
    )


def create_digest_task(digest):
    """Create the digest's Google task for every enabled
    subscriber. Never raises — one subscriber's failure is
    logged plus recorded on their link row as 'failed' and
    must not reach the others or build_digest()."""
    try:
        if not _feature_enabled():
            return
        subscribers = NewsDigestSubscription.objects.filter(
            is_enabled=True,
        ).select_related('user')
        for subscription in subscribers:
            try:
                _run_for_user(digest, subscription.user)
            except Exception as e:
                logger.exception(
                    'Google task creation failed for digest %s '
                    'user %s',
                    digest.date,
                    subscription.user.username,
                )
                _record_failure(digest, subscription.user, e)
    except Exception:
        logger.exception(
            'Google task fan-out failed for digest %s', digest.date
        )

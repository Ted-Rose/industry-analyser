"""Best-effort Google Tasks hook for the daily news digest —
one task per NewsDigest in a configured Google task list."""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from googleapiclient.discovery import build

from google_api.utils import GOOGLE_TASKS_SCOPES, get_user_credentials

from .models import NewsDigestTask
from .preferences import ordered_story_articles

logger = logging.getLogger('news')


def _feature_enabled():
    # Both settings required — empty disables the integration
    # entirely (same convention as GCS_AUDIO_BUCKET).
    return bool(
        getattr(settings, 'GOOGLE_OAUTH_CLIENT_JSON', '')
        and getattr(settings, 'GOOGLE_TASKS_USERNAME', '')
    )


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


def _record_failure(digest, error):
    try:
        NewsDigestTask.objects.update_or_create(
            digest=digest,
            defaults={'status': 'failed', 'error': str(error)},
        )
    except Exception:
        logger.exception(
            'Could not record Google task failure for digest %s',
            digest.date,
        )


def _run(digest):
    link, _ = NewsDigestTask.objects.update_or_create(
        digest=digest,
        defaults={'status': 'pending', 'error': ''},
    )
    username = settings.GOOGLE_TASKS_USERNAME
    user = get_user_model().objects.filter(
        username__iexact=username
    ).first()
    creds = (
        get_user_credentials(user, GOOGLE_TASKS_SCOPES)
        if user is not None
        else None
    )
    if creds is None:
        msg = (
            f'No Google credentials for user {username!r} — '
            f're-authorize at {settings.BASE_URL}/google/login'
        )
        logger.warning(msg)
        link.status = 'failed'
        link.error = msg
        link.save(update_fields=['status', 'error', 'updated_at'])
        return

    service = build('tasks', 'v1', credentials=creds)
    task_list_id = _resolve_task_list_id(service)

    date_str = digest.date.isoformat()
    link_base = getattr(
        settings, 'GOOGLE_TASKS_LINK_BASE_URL', settings.BASE_URL
    )
    notes = [f'{link_base}/news/{date_str}/', '']
    for item in digest.items.order_by('rank').select_related('story'):
        # The user's most preferred outlet that covered the story,
        # in brackets after the headline.
        article = next(
            iter(ordered_story_articles(item.story, user)), None
        )
        src = f' ({article.link})' if article else ''
        notes.append(f'{item.rank}. {item.headline}{src}')
    # No 'due' — the task is a pointer at the digest page, not a
    # deadline (explicit product decision).
    created = service.tasks().insert(
        tasklist=task_list_id,
        body={
            'title': f'News digest {date_str}',
            'notes': '\n'.join(notes),
        },
    ).execute()

    link.task_id = created['id']
    link.task_list_id = task_list_id
    link.status = 'created'
    link.save(
        update_fields=['task_id', 'task_list_id', 'status', 'updated_at']
    )
    logger.info(
        'Google task %s created for digest %s', created['id'], date_str
    )


def create_digest_task(digest):
    """Create the digest's Google task. Never raises — failures
    are logged and recorded on the link row as 'failed'."""
    try:
        if not _feature_enabled():
            return
        # Rebuild dedup: an update_or_create rebuild, --date
        # backfill or top_n change must not spawn a second task.
        if NewsDigestTask.objects.filter(
            digest=digest, status='created'
        ).exists():
            return
        _run(digest)
    except Exception as e:
        logger.exception(
            'Google task creation failed for digest %s', digest.date
        )
        _record_failure(digest, e)

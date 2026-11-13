"""Best-effort Google Tasks hook for the daily news digest —
one task per enabled NewsDigestSubscription, inserted into
each subscriber's own Google task list."""
import logging

from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_api.utils import GOOGLE_TASKS_SCOPES, get_user_credentials

from .backfill import normalize_link
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


def _record_update_error(digest, user, link, error):
    """Record a failed in-place refresh on a 'created' link
    row. The row keeps its status and task_id — the remote
    task may still exist, so flipping to 'failed' would make
    the next build take the insert path and write a duplicate
    Google task. The next build retries the patch instead."""
    link.error = str(error)
    link.save(update_fields=['error', 'updated_at'])
    logger.exception(
        'Google task %s refresh failed for digest %s user %s',
        link.task_id,
        digest.date.isoformat(),
        user.username,
    )


def _task_body(digest, user):
    """The insert/patch body for one subscriber — notes carry
    the digest link, then one markdown-style bullet per item:
    headline, the subscriber's own most-preferred covering
    outlet's name and its (normalized) article link."""
    date_str = digest.date.isoformat()
    link_base = getattr(
        settings, 'GOOGLE_TASKS_LINK_BASE_URL', settings.BASE_URL
    )
    notes = [f'{link_base}/news/{date_str}/', '']
    for item in digest.items.order_by('rank').select_related('story'):
        article = next(
            iter(ordered_story_articles(item.story, user)), None
        )
        if article is None:
            notes.append(f'- {item.headline}')
        else:
            notes.append(
                f'- {item.headline} — {article.source.name} — '
                f'{normalize_link(article.link)}'
            )
    # No 'due' — the task is a pointer at the digest page, not a
    # deadline (explicit product decision).
    return {
        'title': f'News digest {date_str}',
        'notes': '\n'.join(notes),
    }


def _run_for_user(digest, user):
    """One subscriber's attempt. An empty digest writes no link
    row and calls nothing remote (a later rebuild with items
    creates the task fresh); a 'created' link row refreshes the
    stored Google task in place via tasks().patch — a 404 (the
    subscriber deleted it) falls back to a fresh insert while
    any other patch failure keeps 'created' and is retried on
    the next build; a 'pending'/'failed' row is retried via
    insert."""
    if not digest.items.exists():
        logger.info(
            'Digest %s is empty — no Google task for %s',
            digest.date.isoformat(),
            user.username,
        )
        return
    link = NewsDigestTask.objects.filter(
        digest=digest, user=user
    ).first()
    can_update = (
        link is not None
        and link.status == 'created'
        and bool(link.task_id)
        and bool(link.task_list_id)
    )
    creds = get_user_credentials(user, GOOGLE_TASKS_SCOPES)
    if creds is None:
        msg = (
            f'No Google credentials for user {user.username!r} — '
            f're-authorize at {settings.BASE_URL}/google/login'
        )
        logger.warning(msg)
        if can_update:
            # Keep 'created': the remote task may still exist,
            # so a 'failed' flip would re-insert a duplicate on
            # the next build. The error still lands on the row.
            link.error = msg
            link.save(update_fields=['error', 'updated_at'])
        else:
            link, _ = NewsDigestTask.objects.update_or_create(
                digest=digest,
                user=user,
                defaults={'status': 'failed', 'error': msg},
            )
        return

    service = build('tasks', 'v1', credentials=creds)
    body = _task_body(digest, user)
    if can_update:
        try:
            # patch is a partial update — subscriber-set fields
            # (completed status, due) survive a rebuild;
            # update() is a full PUT and would reset them.
            service.tasks().patch(
                tasklist=link.task_list_id,
                task=link.task_id,
                body={'id': link.task_id, **body},
            ).execute()
        except HttpError as e:
            if e.status_code != 404:
                _record_update_error(digest, user, link, e)
                return
            logger.info(
                'Google task %s for digest %s user %s is gone — '
                're-inserting',
                link.task_id,
                digest.date.isoformat(),
                user.username,
            )
        except Exception as e:
            # Any patch failure keeps 'created' — see
            # _record_update_error for the duplicate-task risk.
            _record_update_error(digest, user, link, e)
            return
        else:
            link.error = ''
            link.save(update_fields=['error', 'updated_at'])
            logger.info(
                'Google task %s updated for digest %s user %s',
                link.task_id,
                digest.date.isoformat(),
                user.username,
            )
            return
    else:
        link, _ = NewsDigestTask.objects.update_or_create(
            digest=digest,
            user=user,
            defaults={'status': 'pending', 'error': ''},
        )
    task_list_id = _resolve_task_list_id(service)
    created = service.tasks().insert(
        tasklist=task_list_id,
        body=body,
    ).execute()

    link.task_id = created['id']
    link.task_list_id = task_list_id
    link.status = 'created'
    link.error = ''
    link.save(
        update_fields=[
            'task_id', 'task_list_id', 'status', 'error',
            'updated_at',
        ]
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

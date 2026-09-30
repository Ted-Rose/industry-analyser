"""Provider model-catalog sync (PR-5 card, plan section 9).

``sync_provider_models()`` pulls the provider's free model-listing
endpoint via the adapter's ``list_models()`` and reconciles it with
the ``ai_model`` table: unknown models are created
(``auto_registered=True``, ``is_enabled=enable_new``), existing rows
get catalog-provided fields (display name, prices, context length)
refreshed. Models are **never** disabled or deleted, and existing
rows are never enabled/disabled by a sync.
"""

import logging

from django.conf import settings

from ai_providers import errors
from ai_providers.models import AIModel
from ai_providers.providers import PROVIDER_CLASSES

logger = logging.getLogger('ai_providers')

# ModelInfo fields copied onto existing rows when the catalog
# provides a non-empty value; is_enabled/auto_registered/
# supports_json_mode of existing rows are never touched.
_CATALOG_FIELDS = (
    'input_price_per_mtok',
    'output_price_per_mtok',
    'context_length',
)


def build_provider_adapter(provider):
    """Instantiate the adapter class for an ``AIProvider`` row.

    The API key comes from the Django setting named by
    ``provider.api_key_setting`` (never from the DB). Raises
    ``AIProviderNotConfiguredError`` for an unknown provider_type or
    an empty key setting. Mirrors ``JobClient._build_adapter``.
    """
    cls = PROVIDER_CLASSES.get(provider.provider_type)
    if cls is None:
        raise errors.AIProviderNotConfiguredError(
            f"Provider '{provider.slug}' has unknown provider_type "
            f"'{provider.provider_type}'."
        )
    api_key = getattr(settings, provider.api_key_setting, '')
    if not api_key:
        raise errors.AIProviderNotConfiguredError(
            f"Provider '{provider.slug}' has no API key: setting "
            f"{provider.api_key_setting} is empty."
        )
    return cls(
        api_key=api_key,
        base_url=provider.base_url,
        extra_headers=provider.extra_headers,
        timeout=provider.request_timeout_seconds,
    )


def sync_provider_models(provider, enable_new=False, dry_run=False):
    """Sync ``ai_model`` rows for ``provider`` with its catalog.

    Returns ``{'created': n, 'updated': n, 'skipped': n}``:

    * ``created`` — catalog names with no ``AIModel`` row; new rows
      get ``auto_registered=True`` and ``is_enabled=enable_new``.
    * ``updated`` — existing rows whose display name, prices or
      context length changed to a catalog-provided value.
    * ``skipped`` — catalog names already present and unchanged
      (including duplicate names in the catalog itself).

    ``dry_run=True`` counts what would change but writes nothing.
    Adapter errors (missing API key, API failures) propagate.
    """
    adapter = build_provider_adapter(provider)
    catalog = adapter.list_models()
    existing = {
        row.name: row
        for row in AIModel.objects.filter(provider=provider)
    }
    counts = {'created': 0, 'updated': 0, 'skipped': 0}
    seen = set()
    for info in catalog:
        name = (info.name or '').strip()
        if not name:
            continue
        if name in seen:
            counts['skipped'] += 1
            continue
        seen.add(name)
        row = existing.get(name)
        if row is None:
            counts['created'] += 1
            if not dry_run:
                AIModel.objects.create(
                    provider=provider,
                    name=name,
                    display_name=info.display_name or '',
                    auto_registered=True,
                    is_enabled=enable_new,
                    supports_json_mode=info.supports_json_mode,
                    input_price_per_mtok=info.input_price_per_mtok,
                    output_price_per_mtok=info.output_price_per_mtok,
                    context_length=info.context_length,
                )
            continue
        changes = _catalog_changes(row, info)
        if changes:
            counts['updated'] += 1
            if not dry_run:
                for field, value in changes.items():
                    setattr(row, field, value)
                row.save(update_fields=list(changes))
        else:
            counts['skipped'] += 1
    logger.info(
        'model catalog sync provider=%s catalog=%d created=%d '
        'updated=%d skipped=%d enable_new=%s dry_run=%s',
        provider.slug, len(seen), counts['created'],
        counts['updated'], counts['skipped'], enable_new, dry_run,
    )
    return counts


def _catalog_changes(row, info):
    """Field -> new value for catalog-provided values that differ
    from the existing ``AIModel`` row."""
    changes = {}
    if info.display_name and row.display_name != info.display_name:
        changes['display_name'] = info.display_name
    for field in _CATALOG_FIELDS:
        value = getattr(info, field)
        if value is not None and getattr(row, field) != value:
            changes[field] = value
    return changes

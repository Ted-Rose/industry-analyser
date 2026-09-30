"""AI job specs and auto-registration (plan section 5.5).

Consumer apps declare the AI jobs they use in ``<app>/ai_jobs.py``.
``autodiscover_job_specs()`` imports that module for every installed
app and collects the ``AIJobSpec`` instances it declares. The
convention for ``ai_jobs.py`` modules is:

* a module-level ``JOB_SPECS`` list/tuple of ``AIJobSpec`` instances,
  and/or
* any other module-level attribute that is itself an ``AIJobSpec``.

``ensure_job()`` then makes sure a matching ``AIJob`` row exists and,
on first creation only, seeds the declared default assignments.
"""

import logging
import sys
from dataclasses import dataclass, field

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import autodiscover_modules

from ai_providers.models import AIJob, AIJobModel, AIModel, AIProvider
from ai_providers.presets import PROVIDER_PRESETS

logger = logging.getLogger('ai_providers')


@dataclass(frozen=True)
class AIJobSpec:
    """Code-side declaration of an AI job (a named AI consumer)."""

    slug: str                     # dotted: '<app>.<purpose>'
    description: str
    roles: tuple[str, ...]
    # role -> [(provider_slug, model_name), ...] in priority order
    default_assignments: dict = field(default_factory=dict)


def _iter_ai_jobs_modules():
    """Yield each installed app's ``<app>.ai_jobs`` module, if any."""
    autodiscover_modules('ai_jobs')
    for app_config in apps.get_app_configs():
        module = sys.modules.get(f'{app_config.name}.ai_jobs')
        if module is not None:
            yield module


def _collect_module_specs(module):
    """The AIJobSpec instances a module declares (see module docs)."""
    found = []
    seen_ids = set()
    candidates = list(getattr(module, 'JOB_SPECS', ()) or ())
    candidates += [
        value for name, value in vars(module).items()
        if name != 'JOB_SPECS' and isinstance(value, AIJobSpec)
    ]
    for spec in candidates:
        if not isinstance(spec, AIJobSpec):
            logger.warning(
                'Ignoring non-AIJobSpec entry %r in %s.JOB_SPECS.',
                spec, module.__name__,
            )
            continue
        if id(spec) in seen_ids:
            continue  # listed both in JOB_SPECS and as an attribute
        seen_ids.add(id(spec))
        found.append(spec)
    return found


def autodiscover_job_specs():
    """Import every ``<app>/ai_jobs.py`` and return its AIJobSpecs.

    When two modules declare the same slug the first spec wins and a
    warning is logged.
    """
    specs = []
    seen_slugs = set()
    for module in _iter_ai_jobs_modules():
        for spec in _collect_module_specs(module):
            if spec.slug in seen_slugs:
                logger.warning(
                    'Duplicate AIJobSpec slug %r in %s ignored.',
                    spec.slug, module.__name__,
                )
                continue
            seen_slugs.add(spec.slug)
            specs.append(spec)
    return specs


def _provider_from_preset(provider_slug):
    """Existing provider row, or one created from PROVIDER_PRESETS."""
    preset = PROVIDER_PRESETS.get(provider_slug)
    if preset is None:
        raise ImproperlyConfigured(
            f'AIJobSpec default assignments reference provider '
            f'{provider_slug!r}, which has no ai_provider row and no '
            f'entry in PROVIDER_PRESETS.'
        )
    provider, _ = AIProvider.objects.get_or_create(
        slug=provider_slug, defaults=dict(preset)
    )
    return provider


def ensure_job(spec, initial=None):
    """Create/sync the AIJob row for an AIJobSpec; return the AIJob.

    * Creates the row when missing; ``initial`` (e.g.
      ``{'max_requests_per_run': 20}``) is applied **only on
      creation**.
    * Always syncs ``description`` and ``declared_roles`` from spec.
    * Only when the job is newly created, seeds
      ``default_assignments``: missing providers are created from
      ``PROVIDER_PRESETS``, missing models with
      ``auto_registered=False``, and each list entry becomes an
      active ``AIJobModel`` whose ``priority`` is its position in
      the list. Rows created or edited in admin are never
      overwritten.
    """
    defaults = dict(initial or {})
    defaults.update({
        'description': spec.description,
        'declared_roles': list(spec.roles),
    })
    job, created = AIJob.objects.get_or_create(
        slug=spec.slug, defaults=defaults
    )
    if not created:
        update_fields = []
        if job.description != spec.description:
            job.description = spec.description
            update_fields.append('description')
        roles = list(spec.roles)
        if list(job.declared_roles or []) != roles:
            job.declared_roles = roles
            update_fields.append('declared_roles')
        if update_fields:
            update_fields.append('updated_at')
            job.save(update_fields=update_fields)
        return job
    for role, models in spec.default_assignments.items():
        for priority, entry in enumerate(models):
            provider_slug, model_name = entry
            provider = _provider_from_preset(provider_slug)
            model, _ = AIModel.objects.get_or_create(
                provider=provider,
                name=model_name,
                defaults={'auto_registered': False},
            )
            AIJobModel.objects.create(
                job=job,
                model=model,
                role=role,
                priority=priority,
                is_active=True,
            )
    return job

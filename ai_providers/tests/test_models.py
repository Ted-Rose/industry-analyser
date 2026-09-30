from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase, override_settings

from ai_providers.admin import (
    AIInputAdmin,
    AIJobModelInline,
    AIPromptTemplateAdmin,
    AIRequestAdmin,
)
from ai_providers.models import (
    AIInput,
    AIJob,
    AIJobModel,
    AIModel,
    AIPromptTemplate,
    AIProvider,
    AIRequest,
)


def make_provider(**kwargs):
    defaults = {
        'slug': 'gemini',
        'display_name': 'Google Gemini',
        'provider_type': 'gemini',
        'api_key_setting': 'GEMINI_API_KEY',
    }
    defaults.update(kwargs)
    return AIProvider.objects.create(**defaults)


def make_model(provider, **kwargs):
    defaults = {'provider': provider, 'name': 'gemini-2.5-pro'}
    defaults.update(kwargs)
    return AIModel.objects.create(**defaults)


def make_job(**kwargs):
    defaults = {
        'slug': 'blogs.theme_analysis',
        'declared_roles': ['cheap', 'expensive'],
    }
    defaults.update(kwargs)
    return AIJob.objects.create(**defaults)


class AIProviderCleanTests(TestCase):

    def test_openai_compatible_requires_base_url(self):
        provider = AIProvider(
            slug='openrouter',
            display_name='OpenRouter',
            provider_type='openai_compatible',
            api_key_setting='OPENROUTER_API_KEY',
        )
        with self.assertRaises(ValidationError) as ctx:
            provider.full_clean()
        self.assertIn('base_url', ctx.exception.error_dict)

    def test_openai_compatible_with_base_url_is_valid(self):
        provider = AIProvider(
            slug='openrouter',
            display_name='OpenRouter',
            provider_type='openai_compatible',
            base_url='https://openrouter.ai/api/v1',
            api_key_setting='OPENROUTER_API_KEY',
        )
        provider.full_clean()

    def test_api_key_setting_must_be_in_allowlist(self):
        provider = AIProvider(
            slug='evil',
            display_name='Evil',
            provider_type='gemini',
            api_key_setting='SECRET_KEY',
        )
        with self.assertRaises(ValidationError) as ctx:
            provider.full_clean()
        self.assertIn('api_key_setting', ctx.exception.error_dict)


class AIProviderKeyTests(TestCase):

    def setUp(self):
        self.provider = make_provider()

    @override_settings(GEMINI_API_KEY='test-key')
    def test_has_api_key_true_when_setting_populated(self):
        self.assertTrue(self.provider.has_api_key)

    @override_settings(GEMINI_API_KEY='')
    def test_has_api_key_false_when_setting_empty(self):
        self.assertFalse(self.provider.has_api_key)


class UniqueConstraintTests(TestCase):

    def setUp(self):
        self.provider = make_provider()
        self.model = make_model(self.provider)
        self.job = make_job()

    def test_provider_slug_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_provider(slug='gemini')

    def test_model_provider_name_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_model(self.provider, name='gemini-2.5-pro')

    def test_same_model_name_other_provider_allowed(self):
        other = make_provider(slug='openrouter')
        model = make_model(other, name='gemini-2.5-pro')
        self.assertEqual(str(model), 'openrouter:gemini-2.5-pro')

    def test_job_slug_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_job(slug='blogs.theme_analysis')

    def test_job_model_unique_together(self):
        AIJobModel.objects.create(
            job=self.job, model=self.model, role='cheap'
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AIJobModel.objects.create(
                    job=self.job, model=self.model, role='cheap'
                )

    def test_prompt_template_key_sha256_unique(self):
        AIPromptTemplate.objects.create(
            key='blogs.theme.violence', sha256='a' * 64, text='v1'
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AIPromptTemplate.objects.create(
                    key='blogs.theme.violence',
                    sha256='a' * 64,
                    text='v1 duplicate',
                )
        # Same key with a different hash = new version, allowed.
        AIPromptTemplate.objects.create(
            key='blogs.theme.violence', sha256='b' * 64, text='v2'
        )

    def test_input_sha256_unique(self):
        AIInput.objects.create(sha256='c' * 64, text='one', chars=3)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AIInput.objects.create(
                    sha256='c' * 64, text='two', chars=3
                )


class AIJobModelCleanTests(TestCase):

    def setUp(self):
        self.provider = make_provider()
        self.model = make_model(self.provider)
        self.job = make_job()

    def test_role_must_be_in_declared_roles(self):
        assignment = AIJobModel(
            job=self.job, model=self.model, role='other'
        )
        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()
        self.assertIn('role', ctx.exception.error_dict)

    def test_declared_role_is_valid(self):
        AIJobModel(
            job=self.job, model=self.model, role='cheap'
        ).full_clean()

    def test_active_assignment_requires_enabled_model(self):
        self.model.is_enabled = False
        self.model.save()
        assignment = AIJobModel(
            job=self.job, model=self.model, role='cheap'
        )
        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()
        self.assertIn('model', ctx.exception.error_dict)

    def test_active_assignment_requires_enabled_provider(self):
        self.provider.is_enabled = False
        self.provider.save()
        assignment = AIJobModel(
            job=self.job, model=self.model, role='cheap'
        )
        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()
        self.assertIn('model', ctx.exception.error_dict)

    def test_inactive_assignment_allows_disabled_model(self):
        self.model.is_enabled = False
        self.model.save()
        AIJobModel(
            job=self.job,
            model=self.model,
            role='cheap',
            is_active=False,
        ).full_clean()


class ProtectTests(TestCase):

    def setUp(self):
        self.provider = make_provider()
        self.model = make_model(self.provider)
        self.job = make_job()
        self.template = AIPromptTemplate.objects.create(
            key='blogs.theme.violence', sha256='a' * 64, text='text'
        )
        self.input = AIInput.objects.create(
            sha256='b' * 64, text='article', chars=7
        )
        self.request = AIRequest.objects.create(
            job=self.job,
            role='cheap',
            requested_model=self.model,
            served_model=self.model,
            attempt=1,
            status='success',
            prompt_template=self.template,
            input=self.input,
            prompt_layout='inline_v1',
            prompt_chars=100,
            prompt_sha256='c' * 64,
        )

    def test_provider_delete_protected_by_model(self):
        with self.assertRaises(ProtectedError):
            self.provider.delete()

    def test_model_delete_protected_by_assignment(self):
        AIJobModel.objects.create(
            job=self.job, model=self.model, role='cheap'
        )
        with self.assertRaises(ProtectedError):
            self.model.delete()

    def test_model_delete_protected_by_request(self):
        with self.assertRaises(ProtectedError):
            self.model.delete()

    def test_job_delete_protected_by_request(self):
        with self.assertRaises(ProtectedError):
            self.job.delete()

    def test_prompt_template_delete_protected(self):
        with self.assertRaises(ProtectedError):
            self.template.delete()

    def test_input_delete_protected(self):
        with self.assertRaises(ProtectedError):
            self.input.delete()

    def test_job_delete_cascades_assignments(self):
        job = make_job(slug='other.job', declared_roles=['default'])
        AIJobModel.objects.create(
            job=job, model=self.model, role='default'
        )
        job.delete()
        self.assertFalse(AIJobModel.objects.filter(job_id=job.id)
                         .exists())


class AIJobModelInlineFormSetTests(TestCase):
    """The parent FK is stamped on form.instance only after __init__,
    so `role` choices for extra/empty inline forms must come from the
    formset's own `instance` (the parent AIJob)."""

    def setUp(self):
        self.provider = make_provider()
        self.model = make_model(self.provider)
        self.job = make_job()
        self.site = AdminSite()
        self.request = RequestFactory().get('/admin/')
        # A permitted user is required: the admin wraps inline forms in
        # DeleteProtectedModelForm, whose has_changed() returns False
        # (i.e. the extra form is ignored) when can_add is False.
        self.request.user = get_user_model().objects.create_superuser(
            username='admin', email='a@example.com', password='x'
        )

    def _formset_class(self):
        inline = AIJobModelInline(AIJob, self.site)
        return inline.get_formset(self.request, self.job)

    def _role_choices(self):
        return [('cheap', 'cheap'), ('expensive', 'expensive')]

    def test_extra_form_role_choices_from_parent(self):
        formset = self._formset_class()(instance=self.job)
        self.assertEqual(
            formset.forms[-1].fields['role'].choices,
            self._role_choices(),
        )

    def test_empty_form_role_choices_from_parent(self):
        formset = self._formset_class()(instance=self.job)
        self.assertEqual(
            formset.empty_form.fields['role'].choices,
            self._role_choices(),
        )

    def test_new_assignment_validates_and_saves(self):
        data = {
            'assignments-TOTAL_FORMS': '1',
            'assignments-INITIAL_FORMS': '0',
            'assignments-MIN_NUM_FORMS': '0',
            'assignments-MAX_NUM_FORMS': '1000',
            'assignments-0-model': str(self.model.pk),
            'assignments-0-role': 'expensive',
            'assignments-0-priority': '0',
            'assignments-0-is_active': 'on',
        }
        formset = self._formset_class()(data, instance=self.job)
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()
        self.assertTrue(
            AIJobModel.objects.filter(
                job=self.job, role='expensive', model=self.model
            ).exists()
        )


class ReadOnlyAdminTests(TestCase):

    def setUp(self):
        self.site = AdminSite()
        self.request = RequestFactory().get('/admin/')

    def test_airequest_admin_is_read_only(self):
        model_admin = AIRequestAdmin(AIRequest, self.site)
        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(
            model_admin.has_change_permission(self.request)
        )
        self.assertFalse(
            model_admin.has_delete_permission(self.request)
        )

    def test_prompt_template_admin_is_read_only(self):
        model_admin = AIPromptTemplateAdmin(
            AIPromptTemplate, self.site
        )
        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(
            model_admin.has_change_permission(self.request)
        )
        self.assertFalse(
            model_admin.has_delete_permission(self.request)
        )

    def test_input_admin_is_read_only(self):
        model_admin = AIInputAdmin(AIInput, self.site)
        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(
            model_admin.has_change_permission(self.request)
        )
        self.assertFalse(
            model_admin.has_delete_permission(self.request)
        )

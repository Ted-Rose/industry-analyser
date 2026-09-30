from django import forms
from django.conf import settings
from django.forms.models import BaseInlineFormSet

from .models import AIJobModel, AIProvider


class AIProviderAdminForm(forms.ModelForm):
    """Renders `api_key_setting` as a dropdown built from
    settings.AI_API_KEY_SETTINGS (the allowlist of settings that may
    hold an API key)."""

    api_key_setting = forms.ChoiceField()

    class Meta:
        model = AIProvider
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['api_key_setting'].choices = [
            (name, name)
            for name in getattr(settings, 'AI_API_KEY_SETTINGS', ())
        ]


class AIJobModelInlineForm(forms.ModelForm):
    """Renders `role` as a dropdown populated from the parent job's
    `declared_roles`."""

    role = forms.ChoiceField()

    class Meta:
        model = AIJobModel
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Covers forms bound to an already-saved AIJobModel; extra and
        # empty (`__prefix__`) forms get their choices from
        # AIJobModelInlineFormSet.add_fields instead, because the
        # formset only stamps the parent FK on form.instance after
        # this __init__ has run.
        job = getattr(self.instance, 'job', None)
        roles = job.declared_roles if job else []
        self.fields['role'].choices = [(r, r) for r in roles]


class AIJobModelInlineFormSet(BaseInlineFormSet):
    """Populates `role` choices from the parent job's declared_roles.

    `self.instance` on the formset is the parent AIJob, available for
    every constructed form (including extras and the `__prefix__`
    template) — unlike `form.instance.job`, which the formset sets
    only after each form's __init__ has finished.
    """

    def add_fields(self, form, index):
        super().add_fields(form, index)
        roles = self.instance.declared_roles or []
        form.fields['role'].choices = [(r, r) for r in roles]

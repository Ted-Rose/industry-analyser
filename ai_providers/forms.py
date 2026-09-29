from django import forms
from django.conf import settings

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
        # The formset sets `job_id` on the inline instance when the
        # parent job already exists; jobs are created in code/shell
        # (declared_roles is read-only in admin), so an unsaved parent
        # simply yields an empty dropdown.
        job = getattr(self.instance, 'job', None)
        roles = job.declared_roles if job else []
        self.fields['role'].choices = [(r, r) for r in roles]

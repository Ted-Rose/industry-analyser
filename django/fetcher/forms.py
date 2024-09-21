from django import forms
from .models import Keyword

class KeywordForm(forms.ModelForm):
    class Meta:
        model = Keyword
        fields = ['name', 'only_filter']

    def clean_name(self):
        name = self.cleaned_data.get('name')
        return name.strip().lower()

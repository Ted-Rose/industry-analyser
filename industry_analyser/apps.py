from django.apps import AppConfig


class IndustryAnalyserConfig(AppConfig):
    name = 'industry_analyser'

    def ready(self):
        from . import checks  # noqa: F401

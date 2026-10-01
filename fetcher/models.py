from django.db import models
import uuid


class Vacancy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_name = models.CharField(null=True, max_length=255)
    job_portal_id = models.IntegerField(null=True)
    title = models.CharField(null=True, max_length=255)
    industries = models.ManyToManyField('Industry', through='VacancyIndustries')
    keywords = models.ManyToManyField('Keyword', through='VacancyContainsKeyword')
    salary_from = models.FloatField(null=True, )
    salary_to = models.FloatField(null=True)
    url = models.URLField(max_length=200)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField(null=True)
    days_open = models.IntegerField(null=True)
    vacancy_portal_id = models.IntegerField(
        null=True,
        unique=True,
        help_text="The ID of the vacancy on the job portal",
    )
    application_deadline = models.DateTimeField(null=True)
    detail_fetched_at = models.DateTimeField(
        null=True,
        help_text="When the public vacancy detail page was last "
                  "fetched (null for API-only rows)",
    )
    state = models.CharField(max_length=50)

    def __str__(self):
        return self.title


class VacancyFile(models.Model):
    """Text extracted from a vacancy's attached file (image/PDF ad).

    One row per files-service file_id — each file is OCR'd once and
    the text is reused for keyword matching on later scrapes.
    """
    vacancy = models.ForeignKey(
        'Vacancy', on_delete=models.CASCADE, related_name='files'
    )
    file_id = models.CharField(
        max_length=64,
        unique=True,
        help_text="files-service file UUID",
    )
    content_type = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64)
    extracted_text = models.TextField(null=True)
    ai_model = models.ForeignKey(
        'ai_providers.AIModel',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='vacancy_files',
        help_text="Served AI model that produced extracted_text",
    )
    ai_request = models.ForeignKey(
        'ai_providers.AIRequest',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='vacancy_files',
        help_text="AIRequest row that produced extracted_text",
    )
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'fetcher_vacancy_file'

    def __str__(self):
        return self.file_id


class Industry(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)


class VacancyIndustries(models.Model):
    vacancy = models.ForeignKey('Vacancy', on_delete=models.CASCADE)
    industry = models.ForeignKey('Industry', on_delete=models.CASCADE)

    class Meta:
        unique_together = (('vacancy', 'industry'),)
        db_table = 'fetcher_vacancy_industries'


class Keyword(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)
    only_filter = models.BooleanField(default=False)
    added = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.name = self.name.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class VacancyContainsKeyword(models.Model):
    id = models.AutoField(primary_key=True)
    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE)
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE)

    class Meta:
        unique_together = (('vacancy', 'keyword'),)
        db_table = 'fetcher_vacancy_contains_keyword'

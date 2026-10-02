from django.db import models
from django.db.models import Q
import uuid


class Company(models.Model):
    """Canonical real-world company — portal-agnostic.

    Vacancies point here via ``Vacancy.company``; portal-side
    employer ids live on ``CompanyIdentity`` rows so renames and
    account changes never break the link. ``merged_into`` is a
    soft-redirect left behind when two companies are merged —
    the dead row stays browsable.
    """
    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    name = models.CharField(max_length=255)
    reg_code = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="Normalized registration number — unique where "
                  "present (unique_company_reg_code)",
    )
    reg_code_country = models.CharField(
        max_length=2, null=True, blank=True,
        help_text="Best-effort ISO country of reg_code",
    )
    about = models.TextField(null=True, blank=True)
    webpage_url = models.URLField(null=True, blank=True)
    video_url = models.URLField(null=True, blank=True)
    logo_file_id = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="files-service file UUID",
    )
    cover_file_id = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="files-service file UUID",
    )
    gallery = models.JSONField(default=list, blank=True)
    contact_name = models.CharField(
        max_length=255, null=True, blank=True
    )
    contact_email = models.CharField(
        max_length=255, null=True, blank=True
    )
    contact_phone = models.CharField(
        max_length=64, null=True, blank=True
    )
    applying_url = models.URLField(null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    raw_employer = models.JSONField(
        null=True, blank=True,
        help_text="Last-seen raw employer object",
    )
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    detail_fetched_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When a vacancy detail page last enriched "
                  "this company",
    )
    needs_review = models.BooleanField(
        default=False,
        help_text="Set on reg-code conflicts / merge suggestions",
    )
    merged_into = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='merged_from',
    )

    class Meta:
        db_table = 'fetcher_company'
        constraints = [
            models.UniqueConstraint(
                fields=['reg_code'],
                condition=(
                    ~Q(reg_code='') & Q(reg_code__isnull=False)
                ),
                name='unique_company_reg_code',
            ),
        ]

    def save(self, *args, **kwargs):
        from .company_linking import normalize_reg_code
        self.reg_code = normalize_reg_code(self.reg_code)
        super().save(*args, **kwargs)

    def canonical(self):
        """Follow the ``merged_into`` chain to the surviving
        company; returns self when not merged."""
        company = self
        seen = {self.pk}
        while company.merged_into_id is not None:
            if company.merged_into_id in seen:
                break
            seen.add(company.merged_into_id)
            company = company.merged_into
        return company

    def __str__(self):
        return self.name


class CompanyIdentity(models.Model):
    """Portal-scoped employer identity — the stable join key.

    All cv.lv portals share one ``employerId`` namespace, so
    ``source`` is the portal site ('cv.lv'), not the config
    portal id.
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='identities'
    )
    source = models.CharField(max_length=32)
    employer_id = models.IntegerField()
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    class Meta:
        db_table = 'fetcher_company_identity'
        unique_together = (('source', 'employer_id'),)

    def __str__(self):
        return f'{self.source}:{self.employer_id}'


class CompanyAlias(models.Model):
    """Sighting-style history of observed names and reg codes."""
    KIND_NAME = 'name'
    KIND_REG_CODE = 'reg_code'

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='aliases'
    )
    kind = models.CharField(max_length=16)
    value = models.CharField(max_length=255)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    class Meta:
        db_table = 'fetcher_company_alias'
        unique_together = (('company', 'kind', 'value'),)

    def __str__(self):
        return f'{self.kind}:{self.value}'


class Vacancy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_name = models.CharField(null=True, max_length=255)
    company = models.ForeignKey(
        Company, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='vacancies',
    )
    job_portal_id = models.IntegerField(null=True)
    title = models.CharField(null=True, max_length=255)
    industries = models.ManyToManyField(
        'Industry', through='VacancyIndustries'
    )
    keywords = models.ManyToManyField(
        'Keyword', through='VacancyContainsKeyword'
    )
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

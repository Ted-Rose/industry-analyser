from django.db import models

from django.db import models
import uuid

class Vacancy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_name = models.CharField(null=True, max_length=255)
    job_portal_id = models.IntegerField(null=True)
    title = models.CharField(null=True, max_length=255)
    industries = models.ManyToManyField('Industry', through='VacancyIndustries')
    salary_from = models.FloatField(null=True, )
    salary_to = models.FloatField(null=True)
    url = models.URLField(max_length=200)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField(null=True)
    days_open = models.IntegerField(null=True)
    vacancy_portal_id = models.IntegerField(null=True)
    application_deadline = models.DateTimeField(null=True)
    state = models.CharField(max_length=50)

    def __str__(self):
        return self.title

class Industry(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, unique=True)

class VacancyIndustries(models.Model):
    vacancy = models.ForeignKey('Vacancy', on_delete=models.CASCADE)
    industry = models.ForeignKey('Industry', on_delete=models.CASCADE)

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
      db_table = 'fetcher_vacancy_contains_keyword'
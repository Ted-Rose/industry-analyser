from django.db import models

from django.db import models
import uuid

class Vacancy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.IntegerField(null=True)
    job_portal_id = models.IntegerField(null=True)
    title = models.CharField(null=True, max_length=255)
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

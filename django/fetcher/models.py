from django.db import models

from django.db import models
import uuid

class Vacancy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.IntegerField()
    job_portal_id = models.IntegerField()
    title = models.CharField(max_length=255)
    salary_from = models.FloatField()
    salary_to = models.FloatField()
    url = models.URLField(max_length=200)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    days_open = models.IntegerField()
    vacancy_portal_id = models.IntegerField()
    application_deadline = models.DateTimeField()
    state = models.CharField(max_length=50)

    def __str__(self):
        return self.title

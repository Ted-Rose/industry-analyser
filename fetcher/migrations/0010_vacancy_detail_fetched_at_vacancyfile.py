# Hand-written: Vacancy.detail_fetched_at + VacancyFile.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_providers', '0001_initial'),
        ('fetcher', '0009_alter_vacancy_vacancy_portal_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacancy',
            name='detail_fetched_at',
            field=models.DateTimeField(
                help_text='When the public vacancy detail page was '
                          'last fetched (null for API-only rows)',
                null=True,
            ),
        ),
        migrations.CreateModel(
            name='VacancyFile',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name='ID',
                )),
                ('file_id', models.CharField(
                    help_text='files-service file UUID',
                    max_length=64, unique=True,
                )),
                ('content_type', models.CharField(max_length=100)),
                ('sha256', models.CharField(max_length=64)),
                ('extracted_text', models.TextField(null=True)),
                ('fetched_at', models.DateTimeField(auto_now_add=True)),
                ('ai_model', models.ForeignKey(
                    blank=True,
                    help_text='Served AI model that produced '
                              'extracted_text',
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='vacancy_files',
                    to='ai_providers.aimodel',
                )),
                ('ai_request', models.ForeignKey(
                    blank=True,
                    help_text='AIRequest row that produced '
                              'extracted_text',
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='vacancy_files',
                    to='ai_providers.airequest',
                )),
                ('vacancy', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='files',
                    to='fetcher.vacancy',
                )),
            ],
            options={
                'db_table': 'fetcher_vacancy_file',
            },
        ),
    ]

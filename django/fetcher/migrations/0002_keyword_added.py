# Generated by Django 4.2.6 on 2024-09-07 03:04

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('fetcher', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='keyword',
            name='added',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]

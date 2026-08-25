# Generated manually on 2026-08-26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classified_ads', '0016_alter_project_raw_allow_blank'),
    ]

    operations = [
        migrations.AddField(
            model_name='apartmentforrent',
            name='apartment_no',
            field=models.CharField(
                blank=True,
                help_text='Apartment/unit number within the building',
                max_length=50
            ),
        ),
        migrations.AddField(
            model_name='apartmentforsale',
            name='apartment_no',
            field=models.CharField(
                blank=True,
                help_text='Apartment/unit number within the building',
                max_length=50
            ),
        ),
    ]

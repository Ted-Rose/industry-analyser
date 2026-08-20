# Generated manually on 2026-08-20

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('classified_ads', '0015_hide_entries_before_2026_08_11'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                'ALTER TABLE classified_ads_apartment_rent ALTER COLUMN project_raw DROP NOT NULL;',
                'ALTER TABLE classified_ads_apartment_sale ALTER COLUMN project_raw DROP NOT NULL;',
            ],
            reverse_sql=[
                'ALTER TABLE classified_ads_apartment_rent ALTER COLUMN project_raw SET NOT NULL;',
                'ALTER TABLE classified_ads_apartment_sale ALTER COLUMN project_raw SET NOT NULL;',
            ],
        ),
    ]

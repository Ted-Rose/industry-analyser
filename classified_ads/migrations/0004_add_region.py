from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classified_ads', '0003_add_phone_contact_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='Region',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('name', models.CharField(max_length=255)),
                ('url', models.URLField(max_length=500, unique=True)),
                (
                    'parent',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='sub_regions',
                        to='classified_ads.region',
                    ),
                ),
                ('scrape_enabled', models.BooleanField(default=False)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='classifiedad',
            name='region',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ads',
                to='classified_ads.region',
            ),
        ),
        migrations.AddField(
            model_name='classifiedad',
            name='region_name',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]

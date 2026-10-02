# Generated manually for docs/property_linking_plan.md

from django.db import migrations, models
import django.db.models.deletion


def _match_status_field():
    return models.CharField(
        choices=[
            ('unmatched', 'Unmatched'),
            ('auto', 'Auto-linked'),
            ('candidate', 'Pending review'),
            ('manual', 'Manually linked'),
        ],
        db_index=True,
        default='unmatched',
        max_length=20,
    )


def _property_fk(to, related_name, **kwargs):
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.SET_NULL,
        related_name=related_name,
        to='classified_ads.' + to,
        **kwargs,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('classified_ads', '0019_reconcile_project_schema'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApartmentProperty',
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
                ('district', models.CharField(max_length=255)),
                ('street_name', models.CharField(max_length=255)),
                ('street_no', models.CharField(blank=True, max_length=50)),
                ('first_seen', models.DateTimeField()),
                ('last_seen', models.DateTimeField()),
                (
                    'apartment_no',
                    models.CharField(
                        blank=True,
                        help_text=(
                            'Apartment/unit number within the building'
                        ),
                        max_length=50,
                    ),
                ),
                ('rooms', models.IntegerField()),
                (
                    'size',
                    models.FloatField(help_text='Square metres'),
                ),
                ('floor', models.IntegerField()),
                ('max_floor', models.IntegerField()),
                (
                    'project',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='apartment_properties',
                        to='classified_ads.project',
                    ),
                ),
                (
                    'region',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='%(class)s_properties',
                        to='classified_ads.region',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Apartment Property',
                'verbose_name_plural': 'Apartment Properties',
                'db_table': 'classified_ads_apartment_property',
                'indexes': [
                    models.Index(
                        fields=['district', 'street_no'],
                        name='ca_apt_prop_block_idx',
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name='HouseProperty',
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
                ('district', models.CharField(max_length=255)),
                ('street_name', models.CharField(max_length=255)),
                ('street_no', models.CharField(blank=True, max_length=50)),
                ('first_seen', models.DateTimeField()),
                ('last_seen', models.DateTimeField()),
                ('rooms', models.IntegerField()),
                (
                    'size',
                    models.FloatField(help_text='House floor area m²'),
                ),
                (
                    'floors',
                    models.IntegerField(
                        help_text='Total number of storeys'
                    ),
                ),
                (
                    'land_area_sqm',
                    models.FloatField(
                        blank=True,
                        help_text='Plot area in m²',
                        null=True,
                    ),
                ),
                (
                    'region',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='%(class)s_properties',
                        to='classified_ads.region',
                    ),
                ),
            ],
            options={
                'verbose_name': 'House Property',
                'verbose_name_plural': 'House Properties',
                'db_table': 'classified_ads_house_property',
                'indexes': [
                    models.Index(
                        fields=['district', 'street_no'],
                        name='ca_house_prop_block_idx',
                    ),
                ],
            },
        ),
        *[
            migrations.AddField(
                model_name=model_name,
                name='property_match_status',
                field=_match_status_field(),
            )
            for model_name in (
                'apartmentforrent',
                'apartmentforsale',
                'houseforrent',
                'houseforsale',
            )
        ],
        *[
            migrations.AddField(
                model_name=model_name,
                name='property_match_score',
                field=models.FloatField(blank=True, null=True),
            )
            for model_name in (
                'apartmentforrent',
                'apartmentforsale',
                'houseforrent',
                'houseforsale',
            )
        ],
        *[
            migrations.AddField(
                model_name=model_name,
                name='property',
                field=_property_fk(
                    prop_model,
                    'rent_ads' if 'rent' in model_name else 'sale_ads',
                    help_text='Canonical property this ad is linked to',
                ),
            )
            for model_name, prop_model in (
                ('apartmentforrent', 'apartmentproperty'),
                ('apartmentforsale', 'apartmentproperty'),
                ('houseforrent', 'houseproperty'),
                ('houseforsale', 'houseproperty'),
            )
        ],
        *[
            migrations.AddField(
                model_name=model_name,
                name='candidate_property',
                field=_property_fk(
                    prop_model,
                    '+',
                    help_text='Proposed property link awaiting review',
                ),
            )
            for model_name, prop_model in (
                ('apartmentforrent', 'apartmentproperty'),
                ('apartmentforsale', 'apartmentproperty'),
                ('houseforrent', 'houseproperty'),
                ('houseforsale', 'houseproperty'),
            )
        ],
    ]

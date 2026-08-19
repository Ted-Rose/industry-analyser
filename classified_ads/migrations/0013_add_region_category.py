from django.db import migrations, models


def set_category_based_on_url(apps, schema_editor):
    Region = apps.get_model('classified_ads', 'Region')
    
    regions_to_update = []
    for region in Region.objects.all():
        if '/flats/' in region.url:
            region.category = 'APARTMENT'
        elif '/homes-summer-residences/' in region.url:
            region.category = 'HOUSE'
        else:
            region.category = 'APARTMENT'
        regions_to_update.append(region)
    
    Region.objects.bulk_update(regions_to_update, ['category'])


class Migration(migrations.Migration):

    dependencies = [
        ('classified_ads', '0012_houseforrent_houseforrentsighting'),
    ]

    operations = [
        migrations.AddField(
            model_name='region',
            name='category',
            field=models.CharField(
                choices=[
                    ('APARTMENT', 'Apartment'),
                    ('HOUSE', 'House'),
                    ('PHONE', 'Phone'),
                    ('HOUSEHOLD', 'Household Items')
                ],
                default='APARTMENT',
                max_length=20
            ),
        ),
        migrations.RunPython(
            set_category_based_on_url,
            reverse_code=migrations.RunPython.noop
        ),
        migrations.AlterModelOptions(
            name='region',
            options={'ordering': ['category', 'name']},
        ),
    ]

# Generated manually on 2026-08-20
# Amended: project_raw is only created in 0018, so the raw ALTERs ran
# before the column existed on fresh databases. Guard by vendor and
# column existence; already applied on all existing databases.

from django.db import migrations

_TABLES = (
    'classified_ads_apartment_rent',
    'classified_ads_apartment_sale',
)


def _column_exists(schema_editor, table, column):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'SELECT 1 FROM information_schema.columns '
            'WHERE table_name = %s AND column_name = %s',
            [table, column],
        )
        return cursor.fetchone() is not None


def drop_not_null(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in _TABLES:
        if _column_exists(schema_editor, table, 'project_raw'):
            schema_editor.execute(
                f'ALTER TABLE {table} '
                'ALTER COLUMN project_raw DROP NOT NULL;'
            )


def set_not_null(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in _TABLES:
        if _column_exists(schema_editor, table, 'project_raw'):
            schema_editor.execute(
                f'ALTER TABLE {table} '
                'ALTER COLUMN project_raw SET NOT NULL;'
            )


class Migration(migrations.Migration):

    dependencies = [
        ('classified_ads', '0015_hide_entries_before_2026_08_11'),
    ]

    operations = [
        migrations.RunPython(drop_not_null, set_not_null),
    ]

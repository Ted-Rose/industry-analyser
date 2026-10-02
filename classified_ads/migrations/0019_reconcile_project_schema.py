# Generated manually to repair databases built before 0018's
# state-only ops were applied out-of-band.
#
# 0018 added the Project model, the project FK and project_raw via
# SeparateDatabaseAndState with empty database_operations — those
# objects exist in migration state but were never created by the
# migration runner (production was reconciled manually). Every step
# below is guarded, so this is a no-op on databases that already have
# the schema.

from django.db import migrations

_PROJECT_TABLE = 'classified_ads_project'
_AD_TABLES = (
    'classified_ads_apartment_rent',
    'classified_ads_apartment_sale',
)


def _pg_reconcile(schema_editor):
    statements = [
        # The Project table itself.
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = '{_PROJECT_TABLE}'
            ) THEN
                CREATE TABLE {_PROJECT_TABLE} (
                    id bigserial PRIMARY KEY,
                    name varchar(100) NOT NULL UNIQUE,
                    description text NOT NULL
                );
            END IF;
        END $$;
        """,
    ]
    for table in _AD_TABLES:
        short = table.replace('classified_ads_', 'ca_')
        statements.append(f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = '{table}' AND column_name = 'project'
            ) THEN
                ALTER TABLE {table} DROP COLUMN project;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = '{table}'
                AND column_name = 'project_id'
            ) THEN
                ALTER TABLE {table} ADD COLUMN project_id bigint NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = '{table}'
                AND column_name = 'project_raw'
            ) THEN
                ALTER TABLE {table}
                    ADD COLUMN project_raw varchar(255)
                    NOT NULL DEFAULT '';
            END IF;
        END $$;
        """)
        statements.append(
            f'CREATE INDEX IF NOT EXISTS {short}_project_idx '
            f'ON {table} (project_id);'
        )
        statements.append(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{short}_project_fk'
            ) THEN
                ALTER TABLE {table}
                    ADD CONSTRAINT {short}_project_fk
                    FOREIGN KEY (project_id)
                    REFERENCES {_PROJECT_TABLE}(id)
                    DEFERRABLE INITIALLY DEFERRED;
            END IF;
        END $$;
        """)
    for sql in statements:
        schema_editor.execute(sql)


def _sqlite_reconcile(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f'CREATE TABLE IF NOT EXISTS {_PROJECT_TABLE} ('
            'id integer NOT NULL PRIMARY KEY AUTOINCREMENT, '
            'name varchar(100) NOT NULL UNIQUE, '
            'description text NOT NULL)'
        )
        for table in _AD_TABLES:
            columns = {
                row[1]
                for row in cursor.execute(
                    f'PRAGMA table_info({table})'
                ).fetchall()
            }
            if 'project' in columns:
                cursor.execute(
                    f'ALTER TABLE {table} DROP COLUMN project'
                )
            if 'project_id' not in columns:
                cursor.execute(
                    f'ALTER TABLE {table} ADD COLUMN '
                    f'project_id bigint NULL '
                    f'REFERENCES {_PROJECT_TABLE}(id)'
                )
            if 'project_raw' not in columns:
                cursor.execute(
                    f'ALTER TABLE {table} ADD COLUMN '
                    "project_raw varchar(255) NOT NULL DEFAULT ''"
                )
            cursor.execute(
                f'CREATE INDEX IF NOT EXISTS {table}_project_idx '
                f'ON {table} (project_id)'
            )


def reconcile(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        _pg_reconcile(schema_editor)
    elif schema_editor.connection.vendor == 'sqlite':
        _sqlite_reconcile(schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ('classified_ads', '0018_add_order_id_to_region'),
    ]

    operations = [
        migrations.RunPython(reconcile, migrations.RunPython.noop),
    ]

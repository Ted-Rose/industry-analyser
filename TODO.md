# TODO: Safe Table Rename for Django App Refactor

## Goal
Preserve all existing data when renaming the Django app from `fetcher` to `vacancies` by renaming tables instead of creating new ones.

## Steps

1. **Backup**
   - Backup the database (local and production) before making any schema changes.

2. **Drop new tables**
   - Drop all newly created `vacancies_*` tables from the database:
     - `DROP TABLE vacancies_vacancy;`
     - `DROP TABLE vacancies_keyword;`
     - `DROP TABLE vacancies_industry;`
     - `DROP TABLE vacancies_vacancy_contains_keyword;`
     - `DROP TABLE vacancies_vacancy_industries;`

3. **Edit migrations**
   - Edit the initial `vacancies` migration(s) to use `migrations.RunSQL` with:
     - `ALTER TABLE fetcher_vacancy RENAME TO vacancies_vacancy;`
     - `ALTER TABLE fetcher_keyword RENAME TO vacancies_keyword;`
     - `ALTER TABLE fetcher_industry RENAME TO vacancies_industry;`
     - `ALTER TABLE fetcher_vacancy_contains_keyword RENAME TO vacancies_vacancy_contains_keyword;`
     - `ALTER TABLE fetcher_vacancy_industries RENAME TO vacancies_vacancy_industries;`
   - Optionally, update `django_content_type`:
     - `UPDATE django_content_type SET app_label = 'vacancies' WHERE app_label = 'fetcher';`

4. **Reset migration state**
   - Use `python manage.py migrate vacancies --fake` if needed to align migration history.

5. **Apply migrations**
   - Run `python manage.py migrate vacancies` to ensure Django’s migration history is correct.

6. **Test**
   - Verify all data is present and the app works as expected.

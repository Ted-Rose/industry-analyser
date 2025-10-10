SELECT
    fvc.keyword_id,
    fk.name,
    fv.id,
    fv.company_name,
    fv.job_portal_id,
    fv.title,
    fv.salary_from,
    fv.salary_to,
    fv.url,
    fv.first_seen,
    fv.last_seen,
    fv.days_open,
    fv.vacancy_portal_id,
    fv.application_deadline,
    fv.state
FROM
    fetcher_vacancy fv
    JOIN fetcher_vacancy_contains_keyword fvc ON fv.id = fvc.vacancy_id
    JOIN fetcher_keyword fk ON fvc.keyword_id = fk.id
WHERE
    fv.last_seen IS NOT NULL
ORDER BY
    fv.last_seen DESC;
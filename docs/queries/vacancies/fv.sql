SELECT
    id,
    company_name,
    job_portal_id,
    title,
    salary_from,
    salary_to,
    url,
    first_seen,
    last_seen,
    days_open,
    vacancy_portal_id,
    application_deadline,
    state
FROM
    vacancies_vacancy AS fv
WHERE
    fv.last_seen IS NOT NULL
ORDER BY
    fv.last_seen DESC;
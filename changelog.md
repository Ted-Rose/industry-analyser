# ToDoList

1. Hide and show filters
2. Sort for table
3. Input for adding keywords
  1. Search for only first 50 keywords, and raise exception at end of fetching if more than 50 keywords exist - IN ORDER TO PREVENT SOMEONE FROM OVERSPAMMING KEYWORDS TABLE ON PRODUCTION

# Changelog
1. Vacancies fetched
2. Vacancies table populated with fetched data
3. VACANCY_CONTAINS_KEYWORDS table populated
4. End point `/vacancies` shows vacancies filtered by keywords found in their contents
5. Handle `InvalidChunkLength` error on vacancy list fetching
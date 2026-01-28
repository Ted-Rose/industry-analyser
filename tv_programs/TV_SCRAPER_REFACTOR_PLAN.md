# Refactoring Plan for TVProgramScraper

This document outlines the plan to refactor `tv_programs/scraper.py` to align its design with other scrapers in the project. The goal is to centralize parsing logic, improve data flow by using structured dictionaries, and increase code clarity and maintainability.

## 1. Program HTML Structure Analysis

The scraping logic will be based on the following HTML structure for a single program item:

```html
<div class="show-expander-content tet-grid">
  <div class="expander-image tvprogram-module-nopad tet-grid__cell--sm-span-12 tet-grid__cell--xs-span-12 tet-grid__cell--span-12">
    <img alt="" loading="lazy" src="https://www.tet.lv/cache/mdsposters/9fdef819-b6f0-4729-a8aa-455ac3c8a726.webp">
  </div>
  <div class="expander-description tet-grid__cell--sm-span-12 tet-grid__cell--xs-span-12 tet-grid__cell--span-12">
    <h2 class="tet-font__headline--s">Maģiskais Maiks XXL</h2>
    <p class="subtitle tet-font__body--s">
      <span>01:25 - 03:35</span>
      <span>Trešdiena, 21.01.2026</span>
      <span>Filmzone HD</span>
    </p>
    <p class="text tet-font__body--s">Pagājuši jau trīs gadi kopš Maiks pielicis punktu savai veiksmīgajai striptīza dejotāja karjerai...</p>
  </div>
  <div class="clearfix"></div>
</div>
```

### Data Extraction Selectors:

- **Title:** `h2.tet-font__headline--s`
- **Time String:** First `span` inside `p.subtitle`
- **Description:** `p.text.tet-font__body--s`
- **Image URL:** `src` attribute of `div.expander-image img`

## 2. Refactoring Steps

### Step A: Refactor `parse_results`

- This method will become the primary parsing engine.
- It will iterate through each `program_html` block returned by `soup.find_all()`.
- Inside the loop, it will use the selectors defined above to extract the raw data for title, time, description, and image URL.
- It will parse the time string to create a `datetime` object for `start_time`.
- It will construct a dictionary for each program and append it to a list.
- It will return the final list of structured dictionaries.

### Step B: Update `remove_redundant_results`

- The method will be updated to accept a list of dictionaries.
- It will access program titles for filtering via the dictionary key (e.g., `program['title_lv']`).
- It will return a filtered list of dictionaries.

### Step C: Refactor `extract_resources`

- This method will replace the logic from the old `initiate_resource` method.
- It will accept the filtered list of dictionaries.
- For each dictionary, it will perform any final data transformations (like translation) and create an unsaved `Program` model instance.
- It will return a list of these `Program` instances.

### Step D: Clean Up Obsolete Code

- The following methods, which are made redundant by the new design, will be removed:
  - `get_resource_info_link`
  - `validate_and_return`
  - `initiate_resource`
  - `get_ratings`
  - `process_item`
  - `save_item`
  - `scrape_tv_programs`
  - `old_run` (its logic will be moved into the main `run` method).

## 3. Side Quest: Extract Program Duration

Once the main refactoring is successful, the scraper should be enhanced to extract and store the program's duration.

- **Goal:** Populate the `duration_minutes` field in the `Program` model.
- **Source:** The time string in the HTML, e.g., `<span>01:25 - 03:35</span>`.

### Implementation Steps:

1.  **Update `parse_results`:**
    -   In the parsing loop, extract the full time string (e.g., "01:25 - 03:35").
    -   Parse both the start and end times from this string.
    -   Calculate the difference in minutes. Handle cases where the program crosses midnight (e.g., end time is earlier than start time).
    -   Add the calculated `duration_minutes` to the dictionary being created for each program.
2.  **Update `extract_resources`:**
    -   When creating the `Program` model instance, use the `duration_minutes` value from the dictionary to populate the model field.

## 4. Verification and Testing

After the refactoring is complete, the changes must be verified by running the scraper to ensure it operates correctly.

### Command to Run

Based on the `launch.json` configuration, the test should be executed by running the following Django management command from the project's root directory. Ensure the virtual environment is active first.

```bash
# Activate the virtual environment
source venv/bin/activate

# Run the scraper command with a 15-second timeout
# Note: The `timeout` command is available on macOS and Linux.
# If it fails, you can manually stop the process (Ctrl+C).
timeout 15 python manage.py scrape_tv_programs --force
```

### Expected Outcome

- The command should execute without raising any `AttributeError`, `TypeError`, `KeyError`, or other exceptions related to the new data flow.
- The application logs should show that programs are being correctly parsed, filtered, and created in bulk.
- A final check of the database should confirm that new records are being added to the `tv_programs_program` table as expected.

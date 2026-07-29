# Behavioral Data

Reserved for behavioral assessments or questionnaire outputs to be joined with the physiological segments. **Currently empty for the TECH project** — no behavioral dataset has been added yet, and no notebook in the pipeline reads from here successfully.

The original project stored a participant-level workbook here (`filtered_data_v3 (with ASAs).xlsx`, containing demographics, ECR attachment scales, early-life unpredictability scores, and story metadata) and merged it with the physiological metrics in `004_reformat_final_datasets.ipynb`. That notebook still expects that file and fails without it; see `Analysis notebooks/README.md`.

When a TECH behavioral dataset is added:

- Document its columns in this README before wiring it into the pipeline.
- Note that the join key needs to account for the dyad split: physiological `subject_id` values are `{subject}_{role}` (e.g. `T001_child`), whereas a behavioral file will most likely be keyed on the dyad id (`T001`), possibly with separate child and parent measures per row.

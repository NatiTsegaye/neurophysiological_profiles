# Interim Signals

Signal tables written by `001_data_preparation.ipynb`, one per dyad member. Each file concatenates that subject's five event recordings (`Baseline`, `DCP`, `IDP`, `NDCP`, `Recovery`) in configuration order and carries the markers needed for segmentation.

## File Schema

Files are CSV exports named `{subject}_{role}_signal_events.csv` (e.g. `T001_child_signal_events.csv`).

| Column | Type | Description |
| --- | --- | --- |
| `time_seconds_original_file` | float | Timestamp in seconds from the source Mindware file. Restarts at 0 for every event, so it is **not** monotonic across the file. |
| `MWMOBILEJ_Bio` | float | ECG channel for this role, renamed from `TECH-CHILD_Bio` / `TECH-PARENT_Bio`. |
| `MWMOBILEJ_GSC` | float | Skin conductance channel for this role (µS), renamed from `TECH-CHILD_GSC` / `TECH-PARENT_GSC`. |
| `event_name` | string | Event label (`Baseline`, `DCP`, `IDP`, `NDCP`, `Recovery`). Populated **only** on the two marker rows of each event; null elsewhere. |
| `on_offset` | string | `onset` on the row of the `Start` marker, `offset` on the row that is `duration_seconds` later; null elsewhere. |
| `subject_id` | string | Dyad member identifier, `{subject}_{role}` (e.g. `T001_child`). |
| `role` | string | `child` or `parent`. |

Notes:

- The file is written with `index=False`, so segmentation relies on row position: `segment_df` looks up the `onset`/`offset` rows via the DataFrame's default `RangeIndex` after the CSV is read back.
- The offset marker is derived from the fixed per-event window in `src/ecg_utils/parameters.py`, not from the `End` marker in the raw event file. Where a recording was too short to cover the requested window, the offset falls on the last available sample and `reports/data_preparation_report.md` flags the segment as truncated.
- Because a 500 Hz recording of five events runs to well over a million rows, these files are large (tens of MB per subject) and are excluded from version control.

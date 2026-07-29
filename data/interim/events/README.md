# Interim Event Tables

The marker rows extracted from the interim signal tables, written by `001_data_preparation.ipynb` for quick inspection of segment boundaries without loading the full signal CSV.

## File Schema

Files are Excel workbooks named `{subject}_{role}_events.xlsx` (e.g. `T001_child_events.xlsx`). Each holds the rows of the corresponding `data/interim/signals` CSV where `event_name` is not null — normally ten rows, one onset and one offset per event — with identical columns:

| Column | Type | Description |
| --- | --- | --- |
| `time_seconds_original_file` | float | Timestamp of the marker in the source Mindware file (restarts at 0 for each event). |
| `MWMOBILEJ_Bio` | float | ECG sample value at the marker. |
| `MWMOBILEJ_GSC` | float | Skin conductance sample value at the marker (µS). |
| `event_name` | string | Event label (`Baseline`, `DCP`, `IDP`, `NDCP`, `Recovery`). |
| `on_offset` | string | Whether the row marks the event `onset` or `offset`. |
| `subject_id` | string | Dyad member identifier, `{subject}_{role}`. |
| `role` | string | `child` or `parent`. |

The onset row corresponds to the `Start` marker of the raw event file; the offset row is the fixed window length later, or the last sample of the recording if the recording was too short. An event that is missing here altogether had no raw or event file — cross-check `reports/data_preparation_report.md`, which lists both missing and truncated segments.

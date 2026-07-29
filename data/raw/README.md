# Raw Data

Reference for the unmodified Mindware exports that feed the pipeline. Preserve the original file names and timestamps; the notebooks only read from these files and never write back to them.

## Where the TECH exports live

The TECH project delivers signals and event markers **in the same folder**, so the raw files are not stored under this directory. They live in:

- `data/BioLab/` – the full delivery.
- `data/Sample TECH/` – a two-subject sample used while developing the pipeline; `001_data_preparation.ipynb` currently points here.

The `signals/` and `events/` subfolders of this directory are empty placeholders inherited from the original project, which exported signals and event logs separately. They are unused by the TECH pipeline.

## File naming

Each subject has one signal file and one event file **per event**:

```
{subject_id}_{event_name}_raw.txt
{subject_id}_{event_name}_event.txt
```

for example `T001_Baseline_raw.txt` and `T001_Baseline_event.txt`. Subject ids follow the pattern `T001`; the event names are `Baseline`, `DCP`, `IDP`, `NDCP`, and `Recovery`.

`001_data_preparation.ipynb` discovers subjects by globbing `*_raw.txt` and taking the first underscore-separated token, then builds every other path from the convention above. A file that deviates from it is never opened and the affected event is silently dropped, so run `python scripts/check_raw_data_consistency.py --data-dir "data/BioLab"` before processing a new delivery.

## Signal file schema (`*_raw.txt`)

Tab-delimited text with an inline metadata row:

- Line 1: `Sample Rate:\t{float}` (Hz; 500 for the TECH recordings).
- Line 2: the header row.
- Line 3 onward: samples.

| Column | Type | Description |
| --- | --- | --- |
| `Time (s)` | float | Elapsed recording time in seconds. Each event's file restarts at 0. |
| `TECH-CHILD_Bio` | float | Child ECG channel (voltage). |
| `TECH-CHILD_GSC` | float | Child galvanic skin conductance channel (µS). |
| `TECH-PARENT_Bio` | float | Parent ECG channel (voltage). |
| `TECH-PARENT_GSC` | float | Parent galvanic skin conductance channel (µS). |

Both members of the dyad are in the same file. Column order can differ between subjects, so the pipeline selects the channels by name and renames them to the canonical `MWMOBILEJ_Bio`/`MWMOBILEJ_GSC` when splitting the dyad into a child and a parent stream. Depending on the export, `Time (s)` may use a comma as decimal separator; `common.comma_str_2_float` handles that.

## Event file schema (`*_event.txt`)

Tab-delimited text with a single header row, rows in chronological order:

| Column | Type | Description |
| --- | --- | --- |
| `Event Type` | string | Mindware event source (e.g. `Acquisition PC:BioLab`, `Keyboard:F2`). |
| `Name` | string | Marker label. `Acquisition Start` is written by BioLab; `Start` and `End` are set by the experimenter. |
| `Time` | float | Marker time in seconds relative to the start of that event's recording. |

Only the `Start` marker is used: it defines the segment onset, and the segment then runs for the fixed duration configured in `src/ecg_utils/parameters.py` (`Baseline` 300 s, `DCP`/`IDP`/`NDCP` 600 s, `Recovery` 300 s). The `End` marker is retained for provenance but **ignored** by the pipeline.

# Data Directory

Central hub for all project datasets. Subdirectories reflect the data lifecycle: raw Mindware exports, interim cleaned assets, processed analysis outputs, final deliverables, and behavioral measures aligned to physiological segments. Treat raw files as read-only and promote derivatives through the structure as they are generated.

## Directory Overview

| Folder | Purpose | Key Schemas |
| --- | --- | --- |
| `BioLab/` | Mindware source exports for the TECH project (full delivery). | Paired `{subject}_{event}_raw.txt` / `{subject}_{event}_event.txt`; raw files carry `Time (s)` + `TECH-CHILD_*` / `TECH-PARENT_*` channels, event files carry `Event Type`, `Name`, `Time`. |
| `Sample TECH/` | Two-subject sample with the same layout, used while developing the pipeline. `001_data_preparation.ipynb` currently points here. | As above. |
| `interim/` | One signal table per subject **and role**, with the event onsets/offsets marked, ready for segmentation. | CSV/Excel with `time_seconds_original_file`, `MWMOBILEJ_Bio`, `MWMOBILEJ_GSC`, `event_name`, `on_offset`, `subject_id`, `role`. |
| `processed/` | Per-dyad-member cleaned ECG/EDA outputs under `{subject}_{role}/`. | `preprocessed_*` timeseries, `hrv_metrics.xlsx`, `rsa_metrics.xlsx`, `eda_features.xlsx`. |
| `final/` | Group-level, baseline-corrected datasets ready for further (statistical) analysis. | Aggregated ECG (`HRV_*`, `RSA_*`) and EDA (`EDA_*`, `SCR_*`) workbooks. |
| `behavioral/` | Reserved for questionnaire and demographic context. Currently empty for TECH. | To be defined. |
| `raw/` | Empty placeholders (`signals/`, `events/`) inherited from the original project, whose exports were split across two folders. Unused by the TECH pipeline. | — |

Signal and metric files are excluded from version control by `.gitignore` (`*.txt`, `*.csv`, `*.xlsx`), so only the READMEs and `.gitkeep` markers are tracked. Refer to each subdirectory README for detailed column definitions.

# TECH Project – Neurophysiological Data Analysis

This repository hosts the neurophysiological processing pipeline used to clean, segment, and analyze physiological recordings exported from Mindware for the **TECH** project. The code focuses on electrocardiogram (ECG) processing, in particular heart rate variability (HRV) metrics, and on the processing of electrodermal activity (EDA). In addition, the code contains functionality for event-based segmentation and generation of quality assurance (QA) outputs.

The pipeline was forked from the Neurophysiological Profiles project (a story-listening study) and adapted to the TECH data model. Notebooks `001`, `002`, `003`, and `005` have been adapted and run against TECH data; `004_reformat_final_datasets.ipynb` still contains the story-based reshaping logic of the original project and does **not** run against TECH data yet.

## Data Model
- Each recording is a **parent–child dyad**. A single raw file holds both members of the dyad: `TECH-CHILD_Bio`/`TECH-CHILD_GSC` (child ECG/EDA) and `TECH-PARENT_Bio`/`TECH-PARENT_GSC` (parent ECG/EDA). Column order can differ between subjects, so columns are always selected by name.
- Recordings are exported **one file pair per subject and per event**, following the naming convention `{subject_id}_{event_name}_{raw|event}.txt` (e.g. `T001_Baseline_raw.txt` and `T001_Baseline_event.txt`). Subject ids follow the pattern `T001`.
- There are five events per subject: `Baseline`, `DCP`, `IDP`, `NDCP`, `Recovery`.
- Every event's raw signal starts at `Time (s) = 0`. The analysis window runs from the `Start` marker in the event file for a fixed duration — `Baseline` 300 s, `DCP`/`IDP`/`NDCP` 600 s, `Recovery` 300 s. The `End` marker is present in the event files but is **ignored**.
- Data preparation splits every dyad into a `child` and a `parent` stream. All downstream stages therefore treat `T001_child` and `T001_parent` as separate subjects, and the dyad's Bio/GSC channels are renamed to the canonical `MWMOBILEJ_Bio`/`MWMOBILEJ_GSC` used by the rest of the pipeline.

## Repository Structure
- `src/ecg_utils/` – Core processing library with modules for cleaning (`nk_pipeline.py`), segmentation and validation (`data_utils.py`), shared helpers (`common.py`), parameter definitions (`parameters.py`), plotting utilities (`plot_utils.py`), and data quality flagging (`clean_impute.py`).
- `src/app/ecg_high_level_fnc.py` – High-level orchestration for computing windowed HRV metrics over segmented data, including export of metrics and preprocessed ECG traces.
- `Analysis notebooks/` – Jupyter notebooks (`001_data_preparation.ipynb`–`005_eda_preproc_plot.ipynb`) that document end-to-end workflows from raw data preparation to ECG/EDA analysis and final dataset formatting.
- `scripts/check_raw_data_consistency.py` – Standalone pre-flight check that validates a folder of Mindware exports (file naming, channel names, sample rate, event markers) against what `001_data_preparation.ipynb` expects.
- `data/` – Project datasets. The TECH raw exports live in `data/BioLab/` (full delivery) and `data/Sample TECH/` (two-subject sample); derivatives are tracked through `interim/`, `processed/`, and `final/`.
- `reports/` – Generated reports and QA artefacts: `data_preparation_report.md`, `raw_data_consistency_report.md`, per-subject ECG QA plots in `reports/QA/ecg/{subject}_{role}/`, and the EDA preprocessing figures written by notebook `005`.
- `docs/` – Reference materials and decision logs (e.g., `Mindware Missing Data Report.docx`, `Mindware event file modifications.docx`, `ECG Preprocess Data Quality Log.docx`).
- `environment.yml` – Conda environment specification for macOS (a full `conda env export`, so it will not solve on Windows or Linux).
- `environment-windows.yml` – Minimal cross-platform specification listing only the packages the pipeline actually imports. Use this on Windows.

## Getting Started
1. Create and activate the dedicated environment. On macOS:
   ```bash
   conda env create -f environment.yml
   conda activate neuroprofile
   ```
   On Windows (install [Miniforge](https://github.com/conda-forge/miniforge) first, e.g. `winget install --id=CondaForge.Miniforge3 -e`, then run from the Miniforge Prompt):
   ```bash
   conda env create -f environment-windows.yml
   conda activate neuroprofile
   ```
2. Register the environment as a Jupyter kernel so the notebooks can select it:
   ```bash
   python -m ipykernel install --user --name neuroprofile --display-name "Python (neuroprofile)"
   ```
3. Launch JupyterLab or the IDE of your choice once the environment is active:
   ```bash
   jupyter lab
   ```
   The notebooks resolve the library via `sys.path.append(Path().cwd().parent / "src")`, so the kernel's working directory must be `Analysis notebooks/`. Open them in place rather than copying them elsewhere.
4. Sanity-check the raw exports before running the pipeline, so that misnamed files or renamed channels are caught up front rather than silently dropped:
   ```bash
   python scripts/check_raw_data_consistency.py --data-dir "data/BioLab"
   ```
5. Review the study-specific configuration in `src/ecg_utils/parameters.py` (event names, per-event window durations, sampling frequency, powerline noise) and the raw-data folder that `001_data_preparation.ipynb` points at before running analyses.

## Data Organization
- `data/BioLab/`, `data/Sample TECH/` – Direct Mindware exports for the TECH project (paired `*_raw.txt` and `*_event.txt` files). Keep read-only for provenance. `data/Sample TECH/` holds a two-subject sample used while developing the pipeline.
- `data/interim/` – One signal file per subject **and role** (`signals/{subject}_{role}_signal_events.csv`) plus the corresponding marker rows (`events/{subject}_{role}_events.xlsx`).
- `data/processed/` – Per-subject cleaned traces and metrics under `ecg/{subject}_{role}/` and `eda/{subject}_{role}/`.
- `data/final/` – Group-level, baseline-corrected aggregates delivered to collaborators or downstream models.
- `data/behavioral/` – Reserved for behavioral/questionnaire datasets aligned with the physiological segments. Currently empty for the TECH project.
- `data/raw/signals/` and `data/raw/events/` – Empty placeholders inherited from the original project, which exported signals and events into separate folders. The TECH exports keep both in a single folder, so these are unused.

## Processing Workflow
- **Parameter configuration** – Start from `src/ecg_utils/parameters.py`. The `segmentation` block defines the five TECH events and their fixed window lengths; `configure_ecg_params` and `configure_segmentation_params` allow per-subject overrides (sampling frequency, powerline noise, event durations).
- **Load and segment data** – `src/ecg_utils/data_utils.py` offers helpers to preprocess event logs (`preprocess_event_data`, `add_event_start_stop_marker`), split continuous recordings into study-defined segments (`segment_df`), and validate the result (`check_segment_list`, which expects five segments by default).
- **ECG cleaning and HRV** – `src/ecg_utils/nk_pipeline.py` wraps NeuroKit2 primitives for cleaning (`clean_ecg`), R-peak detection (`find_peaks`), HRV/RSA metrics, and signal quality indices. `src/ecg_utils/clean_impute.py` adds quality flags for window-level QA.
- **Batch QA exports** – `src/app/ecg_high_level_fnc.py` exposes `compute_windowed_hrv_across_segments`, which iterates over segmented DataFrames, computes metrics, writes `hrv_metrics.xlsx` and `preprocessed_ecg.csv`, and optionally saves QA plots per segment.

### Example: Windowed HRV computation
```python
from pathlib import Path
import pandas as pd

from ecg_utils import data_utils, nk_pipeline, parameters
from app.ecg_high_level_fnc import compute_windowed_hrv_across_segments

params = parameters.base_params
subject_id = "T001_child"

signal_df = pd.read_csv(f"data/interim/signals/{subject_id}_signal_events.csv")
preproc_df = signal_df.merge(
    nk_pipeline.ecg_preprocess(signal_df["MWMOBILEJ_Bio"], params),
    left_index=True,
    right_index=True,
)

segments = data_utils.segment_df(preproc_df, params)
data_utils.check_segment_list(segments)
for segment in segments:
    segment.set_index("time_seconds_original_file", inplace=True)

hrv_metrics, preprocessed = compute_windowed_hrv_across_segments(
    segments_df_list=segments,
    parameters=params,
    figure_output_dir=Path("reports/QA/ecg") / subject_id,
    data_output_dir=Path("data/processed/ecg") / subject_id,
    subject_id=subject_id,
)
```
Adjust the paths to match your subject id and ensure the target directories exist. Set `create_qa_plots=False` to skip figure generation — with 500 Hz recordings and 30 s analysis windows, plotting dominates the runtime.

## Notebooks & Reporting
- Run the numbered notebooks sequentially to reproduce full analyses: raw import, dyad splitting and event marking (`001`), ECG/HRV pipeline (`002`), EDA analysis (`003`), final dataset reshaping (`004`), and EDA preprocessing visualizations (`005`).
- `001` writes `reports/data_preparation_report.md` (plus a per-segment CSV) listing the segmentation rules that were applied and any problems worth checking: missing files, missing `Start` markers, and segments truncated because the recording was shorter than the requested window.
- `scripts/check_raw_data_consistency.py` writes `reports/raw_data_consistency_report.md`, which covers the problems `001` cannot see because it never opens a misnamed file.
- ECG QA plots land in `reports/QA/ecg/{subject}_{role}/{segment}_{window}.png`, providing visual checks before aggregating across segments. Notebook `005` writes per-segment EDA preprocessing figures directly to `reports/`.
- `004_reformat_final_datasets.ipynb` is **not yet adapted**: it pivots on story names (`Story 1`–`Story 5`) and reads the original project's behavioral workbook, neither of which exist in the TECH dataset. It therefore fails at the first cell that loads behavioral data, and `data/final/neuro-behavioral_data.xlsx` is not produced.

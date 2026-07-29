# Mindware Data Analysis

This repository hosts the neurophysiological processing pipeline used to clean, segment, and analyze physiological recordings exported from Mindware. The code focuses on electrocardiogram (ECG) processing, in particular heart rate variability (HRV) metrics, and the processing of electrodermal activity (EDA). In addition, the code contains functionality for event-based segmentation, and generation of quality assurance (QA) outputs that support the broader Neurophysiological Profiles project.

## Repository Structure
- `src/ecg_utils/` – Core processing library with modules for cleaning (`nk_pipeline.py`), segmentation and validation (`data_utils.py`), shared helpers (`common.py`), parameter definitions (`parameters.py`), plotting utilities, and data quality flagging (`clean_impute.py`).
- `src/app/ecg_high_level_fnc.py` – High-level orchestration for computing windowed HRV metrics over segmented data, including export of metrics and preprocessed ECG traces.
- `Analysis notebooks/` – Jupyter notebooks (`001_data_preparation.ipynb`–`005_eda_preproc_plot.ipynb`) that document end-to-end workflows from raw data preparation to ECG/EDA analysis and final dataset formatting.
- `data/` – Project datasets organized into `raw/`, `interim/`, `processed/`, `final/`, and `behavioral/` subfolders to track data lineage.
- `reports/` – Generated figures and QA artefacts (e.g., `reports/QA/ecg/`, `reports/QA/eda/`, `2073_eda_segments.png`).
- `docs/` – Reference materials and decision logs (e.g., `Mindware Missing Data Report.docx`, `ECG Preprocess Data Quality Log.docx`).
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
4. Update the repository-specific configuration files (e.g., subject-specific overrides inside `src/ecg_utils/parameters.py`) before running analyses.

## Data Organization
- `data/raw/` – Direct exports from Mindware (ECG, event logs, EDA, etc.). Keep files read-only for provenance.
- `data/interim/` – Intermediate, cleaned datasets generated during notebooks or pipeline runs.
- `data/processed/` – Windowed metrics, QA-ready ECG segments, and other artefacts ready for review.
- `data/final/` – Final aggregates delivered to collaborators or downstream models.
- `data/behavioral/` – Behavioral datasets aligned with physiological segments for joint analyses.

## Processing Workflow
- **Parameter configuration** – Start from `src/ecg_utils/parameters.py`. Use `configure_ecg_params` and `configure_segmentation_params` to override defaults (sampling frequency, powerline noise, event durations) on a per-subject basis.
- **Load and segment data** – `src/ecg_utils/data_utils.py` offers helpers to preprocess event logs (`preprocess_event_data`) and split continuous recordings into study-defined segments (`segment_df`).
- **ECG cleaning and HRV** – `src/ecg_utils/nk_pipeline.py` wraps NeuroKit2 primitives for cleaning (`clean_ecg`), R-peak detection (`find_peaks`), HRV/RSA metrics, and signal quality indices. `src/ecg_utils/clean_impute.py` adds quality flags for window-level QA.
- **Batch QA exports** – `src/app/ecg_high_level_fnc.py` exposes `compute_windowed_hrv_across_segments`, which iterates over segmented DataFrames, computes metrics, writes `hrv_metrics.xlsx` and `preprocessed_ecg.csv`, and optionally saves QA plots per segment.

### Example: Windowed HRV computation
```python
from pathlib import Path
import pandas as pd

from ecg_utils import data_utils, parameters
from app.ecg_high_level_fnc import compute_windowed_hrv_across_segments

ecg_df = pd.read_csv("data/interim/example_subject_ecg.csv", index_col=0)
params = parameters.base_params
segments = data_utils.segment_df(ecg_df, params)

hrv_metrics, preprocessed = compute_windowed_hrv_across_segments(
    segments_df_list=segments,
    parameters=params,
    figure_output_dir=Path("reports/QA/ecg"),
    data_output_dir=Path("data/processed/example_subject"),
    subject_id="example_subject",
)
```
Adjust the paths to match your subject ID and ensure the target directories exist. Set `create_qa_plots=False` to skip figure generation.

## Notebooks & Reporting
- Run the numbered notebooks sequentially to reproduce full analyses: import/export cleanup (`001`), ECG pipeline walkthrough (`002`), EDA analysis (`003`), final dataset reshaping (`004`), and EDA preprocessing visualizations (`005`).
- QA plots and intermediate summaries land in `reports/QA/`, providing visual checks before aggregating across segments.

## Use of AI
Generative AI has only been used in assisting with documentation of this repository. This includes this and other readme files as well as some of the function docstrings. 
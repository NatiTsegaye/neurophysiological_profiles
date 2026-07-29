# App Layer

Orchestration built on top of the utilities in `ecg_utils`. Currently one module:

- `ecg_high_level_fnc.py` – `compute_windowed_hrv_across_segments` iterates over a list of segmented ECG DataFrames, computes HRV metrics per analysis window, optionally writes a QA plot per window, and exports `hrv_metrics.xlsx` and `preprocessed_ecg.csv` into the given output directory. It returns both tables as DataFrames as well.

The module has no CLI entry point; it is called from `Analysis notebooks/002_ecg_analysis.ipynb`. Pass `create_qa_plots=False` to skip figure generation, which otherwise dominates the runtime at 500 Hz with 30 s windows.

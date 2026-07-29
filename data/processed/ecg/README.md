# Processed ECG

Per-dyad-member ECG derivatives written by `002_ecg_analysis.ipynb`: the cleaned trace, windowed HRV metrics, and segment-level RSA metrics. One subfolder per subject and role (e.g. `T001_child/`).

## File Schemas

### `preprocessed_ecg.csv`

The cleaned ECG of all five segments, concatenated. Only samples inside a segment window are present.

| Column | Type | Description |
| --- | --- | --- |
| *(unnamed index)* | int | Zero-based row counter across the concatenated segments (written by `to_csv`). |
| `MWMOBILEJ_Bio` | float | Raw ECG samples as ingested from the interim file. |
| `MWMOBILEJ_GSC` | float | Raw skin conductance samples, retained for reference. |
| `event_name` | string | Event label, populated only on the segment's marker rows. |
| `on_offset` | string | Event boundary flag (`onset`/`offset`) on those marker rows. |
| `subject_id` | string | Dyad member identifier, `{subject}_{role}`. |
| `role` | string | `child` or `parent`. |
| `ECG_Clean` | float | Filtered ECG signal (NeuroKit-cleaned). |
| `ECG_Raw` | float | Raw ECG copy produced by the NeuroKit pipeline, for QA comparisons. |
| `ECG_R_Peaks` | int | Binary indicator (1 at detected R-peaks). |
| `segment_name` | string | Segment the sample belongs to, populated on every row. |

Note that `time_seconds_original_file` is **not** in this file: notebook `002` promotes it to the segment index before computing HRV, and the concatenation step then replaces the index with a row counter. Use `segment_name` plus the sampling frequency to reconstruct time within a segment.

### `hrv_metrics.xlsx`

Windowed HRV metrics exported by `compute_windowed_hrv_across_segments`, one row per 30 s non-overlapping analysis window (`analysis_window_seconds` in `parameters.base_params`).

| Column | Type | Description |
| --- | --- | --- |
| `HRV_*` | float | Time-domain HRV indices from NeuroKit2: `HRV_MeanNN`, `HRV_SDNN`, `HRV_SDANN1/2/5`, `HRV_SDNNI1/2/5`, `HRV_RMSSD`, `HRV_SDSD`, `HRV_CVNN`, `HRV_CVSD`, `HRV_MedianNN`, `HRV_MadNN`, `HRV_MCVNN`, `HRV_IQRNN`, `HRV_SDRMSSD`, `HRV_Prc20NN`, `HRV_Prc80NN`, `HRV_pNN50`, `HRV_pNN20`, `HRV_MinNN`, `HRV_MaxNN`, `HRV_HTI`, `HRV_TINN`. |
| `start_time` / `end_time` | float | Bounds of the analysis window, taken from the segment index. |
| `analysis_window` | int | Sequential window counter within the segment (0-based). |
| `heart_rate_bpm` | float | Average heart rate in beats per minute for the window. |
| `n_peaks_detected` | int | Count of R-peaks in the window. |
| `segment_name` | string | Segment the window belongs to. |
| `subject_id` | string | Dyad member identifier. |

Frequency-domain metrics are absent because `compute_hrv_frequency_metrics` is `False` by default; 30 s windows are too short for them. Windows where HRV computation failed (too few peaks) are reported in the notebook output and filtered out during aggregation via `clean_impute.flag_windows_insufficient_n_peaks`.

### `rsa_metrics.xlsx`

Segment-level respiratory sinus arrhythmia metrics from `calculate_rsa_per_segment`; one row per segment, since Porges-Bohrer RSA needs longer windows than HRV.

| Column | Type | Description |
| --- | --- | --- |
| `RSA_P2T_Mean`, `RSA_P2T_Mean_log`, `RSA_P2T_SD`, `RSA_P2T_NoRSA` | float | Peak-to-trough RSA indices. |
| `RSA_PorgesBohrer` | float | Porges-Bohrer RSA, the primary RSA measure used downstream. |
| `RSA_Gates_Mean`, `RSA_Gates_Mean_log`, `RSA_Gates_SD` | float | Gates method RSA indices. |
| `segment_name` | string | Segment label. |
| `start_time` / `end_time` | float | Segment bounds from the segment index. |
| `subject_id` | string | Dyad member identifier. |

# Final EDA Features

Group-level EDA features written by the aggregation cell of `003_eda_analyis.ipynb`.

## File Schema

`group_level_blc_eda_features.xlsx` concatenates the per-subject `eda_features.xlsx` files from `data/processed/eda/{subject}_{role}/` and adds baseline and baseline-corrected columns. One row per dyad member and segment; `Baseline` rows are excluded after being used as the reference.

| Column | Type | Description |
| --- | --- | --- |
| *(unnamed index)* | int | Row counter written by `to_excel`; notebook `004` drops it as `Unnamed: 0`. |
| `index` | int | Leftover index from the per-subject files, preserved by the `reset_index()` in `apply_baseline_correction`. Not meaningful. |
| `segment_name` | string | Segment identifier (`DCP`, `IDP`, `NDCP`, `Recovery`). |
| `subject_id` | string | Dyad member identifier, `{subject}_{role}` (e.g. `T001_child`). |
| `segment_length_seconds` | float | Duration of the segment in seconds. |
| `SCR_Peaks_N`, `SCR_Peaks_N_per_seconds` | float | Raw peak count and length-normalised peak rate. |
| `SCR_Peaks_Amplitude_Mean` | float | Mean SCR amplitude for the segment (µS). |
| `EDA_Tonic_Mean`, `EDA_Tonic_SD` | float | Mean and standard deviation of tonic conductance. |
| `EDA_Sympathetic`, `EDA_SympatheticN`, `EDA_Autocorrelation` | float | NeuroKit-derived sympathetic and autocorrelation indices. |
| `*_baseline` columns | float | The subject's `Baseline` value for each of the eight features above. |
| `*_blc` columns | float | Baseline-corrected values (segment minus baseline). |

Unlike the ECG table, every feature here gets both a `_baseline` and a `_blc` counterpart. Since segment lengths differ by design, compare `SCR_Peaks_N_per_seconds_blc` rather than `SCR_Peaks_N_blc` across segments.

Refer to `Analysis notebooks/003_eda_analyis.ipynb` (function `apply_baseline_correction`) for the transformation logic that produces this schema.

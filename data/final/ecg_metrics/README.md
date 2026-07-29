# Final ECG Metrics

Group-level ECG metrics written by the aggregation cells of `002_ecg_analysis.ipynb`.

## File Schema

`group_level_blc_ecg_metrics.xlsx` merges the windowed HRV outputs with the segment-level RSA summaries from `data/processed/ecg/{subject}_{role}/`, averages the HRV windows within each segment, and applies baseline correction. One row per dyad member and segment; `Baseline` rows are excluded after being used as the reference.

| Column | Type | Description |
| --- | --- | --- |
| *(unnamed index)* | int | Row counter written by `to_excel`; notebook `004` drops it as `Unnamed: 0`. |
| `segment_name` | string | Segment identifier (`DCP`, `IDP`, `NDCP`, `Recovery`). |
| `subject_id` | string | Dyad member identifier, `{subject}_{role}` (e.g. `T001_child`). |
| `HRV_*` columns | float | Time-domain HRV metrics averaged over the usable 30 s analysis windows of the segment (`HRV_MeanNN`, `HRV_SDNN`, `HRV_RMSSD`, `HRV_pNN20`/`HRV_pNN50`, and the rest of the NeuroKit time-domain set). |
| `heart_rate_bpm` | float | Mean heart rate for the segment. |
| `RSA_*` columns | float | RSA metrics carried over unaggregated from `rsa_metrics.xlsx` (Porges-Bohrer, peak-to-trough, and Gates variants). |
| `usable_analysis_windows_in_segment` | float | Number of analysis windows that passed the peak-count and outlier checks and therefore contributed to the HRV averages. |
| `RSA_PorgesBohrer_baseline`, `HRV_SDNN_baseline`, `heart_rate_bpm_baseline` | float | The subject's `Baseline` values for the three primary measures. |
| `RSA_PorgesBohrer_corrected`, `HRV_SDNN_corrected`, `heart_rate_bpm_corrected` | float | Baseline-corrected values (segment minus baseline). |

Notes:

- Baseline correction is applied only to the three primary measures above, not to the full `HRV_*`/`RSA_*` set.
- Windows are excluded from the averages when they contain fewer than 20 R-peaks (`clean_impute.flag_windows_insufficient_n_peaks`) or when `HRV_SDNN` is an outlier at |z| > 2.56 (`clean_impute.flag_outliers_based_on_zscore`). Check `usable_analysis_windows_in_segment` before interpreting a row: a low count means the segment was largely unusable.

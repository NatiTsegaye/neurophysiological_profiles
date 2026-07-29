# ECG Utilities

Reusable components for signal cleaning, segmentation, HRV/RSA computation, parameter management, plotting, and QA flagging. Import these modules into notebooks or scripts to build analysis workflows.

Despite the package name, the EDA analyses also depend on it: `data_utils.segment_df` and `parameters.base_params` drive segmentation for both modalities.

| Module | Contents |
| --- | --- |
| `parameters.py` | `base_params` (sampling frequency, cleaning and peak-detection settings, HRV frequency bands, and the five TECH segments with their fixed durations) plus `configure_ecg_params` / `configure_segmentation_params` for per-subject overrides. |
| `data_utils.py` | Event-log preparation (`preprocess_event_data`, `add_event_start_stop_marker`), segmentation (`segment_df`, `get_event_time_from_dataframe_index`), and validation (`check_segment_list`, which warns when the segment count differs from the expected five). |
| `nk_pipeline.py` | NeuroKit2 wrappers: `ecg_preprocess`, `clean_ecg`, `find_peaks`, `calculate_heartrate`, `calculate_signal_quality`, `calculate_hrv_indices`, `calculate_windowed_HRV_metrics`, `calculate_RSA_metrics`, `calculate_rsa_per_segment`. |
| `clean_impute.py` | Window-level QA flags: `flag_windows_insufficient_n_peaks`, `flag_outliers_based_on_zscore`, `flag_usable_aggregation_windows`. |
| `plot_utils.py` | `plot_ecg_segment` for the per-window ECG QA figures. |
| `common.py` | Shared helpers: `comma_str_2_float` (Mindware decimal commas), YAML import/export, and a logger. |

Note on segmentation: `segment_df` looks up the onset and offset rows of each event from the DataFrame's index, so the caller must pass a frame whose index matches the row positions used when the markers were written (which is what reading `data/interim/signals/*.csv` gives you). It only falls back to `default_duration_seconds` when a `Baseline` offset marker is missing; for any other segment a missing offset raises.

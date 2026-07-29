# Processed EDA

Per-dyad-member electrodermal activity outputs written by `003_eda_analyis.ipynb` after NeuroKit2 preprocessing, SCR artefact filtering, and segmentation. One subfolder per subject and role (e.g. `T001_child/`).

## File Schemas

### `preprocessed_eda.csv`

The preprocessed EDA signal for the whole recording (all five events concatenated, before segmentation).

| Column | Type | Description |
| --- | --- | --- |
| `time_seconds_original_file` | float | Timestamp in seconds from the source Mindware file; restarts at 0 for each event. |
| `event_name` | string | Event label, populated only on the marker rows. |
| `on_offset` | string | Event boundary flag (`onset`/`offset`) on those marker rows. |
| `subject_id` | string | Dyad member identifier, `{subject}_{role}`. |
| `role` | string | `child` or `parent`. |
| `EDA_Raw` | float | Unprocessed skin conductance signal (µS), the interim `MWMOBILEJ_GSC` channel. |
| `EDA_Clean` | float | Cleaned signal returned by `nk.eda_process`. |
| `EDA_Tonic` | float | Slow-varying tonic component. |
| `EDA_Phasic` | float | Phasic component isolated by NeuroKit. |
| `SCR_Onsets` | int | Binary indicator of detected SCR onsets. |
| `SCR_Peaks` | int | Binary indicator of SCR peaks **after** artefact filtering (see below). |
| `SCR_Height` | float | Peak height in the phasic signal. |
| `SCR_Amplitude` | float | Skin conductance response amplitude (µS). |
| `SCR_RiseTime` | float | Response rise time in seconds. |
| `SCR_Recovery` | float | Recovery value per sample. |
| `SCR_RecoveryTime` | float | Recovery duration in seconds. |

Two amplitude filters are applied to `SCR_Peaks` before segmentation: peaks with `SCR_Amplitude` above 1 µS are treated as artefacts (Dawson, Schell & Filion, 2017) and peaks below 0.01 µS are treated as noise. Both are set to 0 rather than removed, so the raw NeuroKit amplitudes remain inspectable.

### `eda_features.xlsx`

Interval-related features from `nk.eda_analyze`, one row per segment.

| Column | Type | Description |
| --- | --- | --- |
| `SCR_Peaks_N` | int | Count of SCR peaks within the segment. |
| `SCR_Peaks_Amplitude_Mean` | float | Mean SCR amplitude (µS). |
| `EDA_Tonic_SD` | float | Standard deviation of the tonic component. |
| `EDA_Sympathetic` / `EDA_SympatheticN` | float | Sympathetic activation indices from NeuroKit. |
| `EDA_Autocorrelation` | float | Autocorrelation of the cleaned signal. |
| `segment_name` | string | Segment identifier (`Baseline`, `DCP`, `IDP`, `NDCP`, `Recovery`). |
| `subject_id` | string | Dyad member identifier. |
| `segment_length_seconds` | float | Segment duration derived from the sample count. |
| `SCR_Peaks_N_per_seconds` | float | Peak rate (count per second), the length-normalised version of `SCR_Peaks_N`. |
| `EDA_Tonic_Mean` | float | Mean tonic conductance over the segment (µS). |

Because segment lengths differ by design (300 s for `Baseline`/`Recovery`, 600 s for the task events) and can be shorter still when a recording was truncated, prefer the rate-normalised `SCR_Peaks_N_per_seconds` over the raw count when comparing segments.

# Interim Data

Holds the intermediate datasets produced by `001_data_preparation.ipynb`. Files here are mutable checkpoints: re-running the notebook overwrites them.

This is the stage where the parent–child dyad is split. Each subject's five event recordings are concatenated into a single table per role, so one raw subject (`T001`) becomes two interim subjects (`T001_child` and `T001_parent`) that every downstream notebook processes independently.

## Subdirectory Schemas

- `signals/`: CSV exports combining the signal samples of all five events with the event onset/offset markers. One file per subject and role.
- `events/`: Excel workbooks holding only the marker rows of the corresponding signal CSV, for quick inspection of segment boundaries.

Both share the same columns; see the subdirectory READMEs for details. These files are fed directly into the segmentation and feature-extraction steps in `002_ecg_analysis.ipynb`, `003_eda_analyis.ipynb`, and `005_eda_preproc_plot.ipynb`.

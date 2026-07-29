# Processed Data

Outputs from the notebooks after segmentation, cleaning, and windowed analysis. Use this directory for QA-ready tables and metrics that precede the final group-level deliverables.

## Subdirectory Schemas

- `ecg/{subject}_{role}/`: Contains `preprocessed_ecg.csv`, `hrv_metrics.xlsx`, and `rsa_metrics.xlsx`, written by `002_ecg_analysis.ipynb`. See `data/processed/ecg/README.md` for full column definitions.
- `eda/{subject}_{role}/`: Contains `preprocessed_eda.csv` and `eda_features.xlsx`, written by `003_eda_analyis.ipynb`, with the schema documented in `data/processed/eda/README.md`.

Folder names are dyad members, e.g. `T001_child` and `T001_parent`. Only the five configured segments are present in these files — samples that fall outside a segment window are dropped during segmentation. The aggregation cells at the end of notebooks `002` and `003` read every subfolder here to populate `data/final`.

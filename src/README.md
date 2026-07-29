# Source Code

Python modules that implement the ECG/EDA processing pipeline. Reference `ecg_utils` for reusable utilities and `app` for high-level orchestration.

The notebooks add this directory to `sys.path` (`sys.path.append(Path().cwd().parent / "src")`) and import the packages as `ecg_utils.*` and `app.*`; there is no installable package.

Study-specific configuration lives in `ecg_utils/parameters.py`. `base_params['segmentation']` defines the five TECH events (`Baseline`, `DCP`, `IDP`, `NDCP`, `Recovery`) and their fixed window lengths, and is the single place where notebooks and the raw-data consistency check read the event list from — change it there rather than in the notebooks.

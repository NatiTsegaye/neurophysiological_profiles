# Scripts

Standalone utilities that support the notebook pipeline but are not part of an analysis.

## `check_raw_data_consistency.py`

Pre-flight check for a folder of Mindware exports. `001_data_preparation.ipynb` discovers subjects by globbing `*_raw.txt` and then builds every path it needs as `{subject_id}_{event_name}_{raw|event}.txt`; a file that deviates from that convention is never opened and the affected event is silently dropped. This script simulates that discovery and also validates the file structure itself: channel names (`TECH-CHILD_*` / `TECH-PARENT_*`), the declared sample rate, the time axis, and the event markers.

```bash
python scripts/check_raw_data_consistency.py                          # checks data/BioLab
python scripts/check_raw_data_consistency.py --data-dir "data/Sample TECH"
python scripts/check_raw_data_consistency.py --strict                 # exit code 1 if any error was found
```

Outputs `reports/raw_data_consistency_report.md` plus a CSV of all findings alongside it (override with `--report-path`).

Only the first few lines of each file are read, so the check runs in seconds even on multi-GB exports. The flip side is that problems which depend on the full recording — for example a recording too short for the requested analysis window — are out of scope; those are covered by `reports/data_preparation_report.md`, which `001` writes.

The expected event names and sampling frequency are imported from `src/ecg_utils/parameters.py` so the check stays in sync with the pipeline, with hard-coded fallbacks so it still runs outside the project environment. It has no third-party dependencies.

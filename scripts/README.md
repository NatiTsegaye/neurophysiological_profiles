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

## `fix_raw_data_consistency.py`

Applies the subset of the findings above whose correct outcome is unambiguous, so that what remains in the check report is what actually needs a decision. It imports the checker's own filename, channel, and marker logic, so the two cannot drift apart.

Three classes of fix, selectable with `--fix` (default: all three):

| `--fix` | What it repairs |
| --- | --- |
| `names` | The separator (`T067 Baseline_raw.txt` → `T067_Baseline_raw.txt`), the file-type suffix (`..._RAW.txt` → `..._raw.txt`), the event name capitalisation (`T082_recovery_raw.txt` → `T082_Recovery_raw.txt`), and the subject token. |
| `columns` | A misspelled channel whose role (child/parent) and signal type (Bio/GSC) can be read off the name, in either capitalisation: `CHILD2_Bio` → `TECH-CHILD_Bio`, `tech-parentt_gsc` → `TECH-PARENT_GSC`. A trailing channel index is kept, so `TECH-PARENTT_Bio 2` becomes `TECH-PARENT_Bio 2` rather than colliding with the primary channel. |
| `markers` | An event file with more than one `Start` marker: all but one are removed, since the notebook silently uses the first marker it finds. The later marker is normally the real onset, so the last one is kept — unless the recording after it is too short for the event's analysis window, in which case that marker is an `End` pressed with the wrong key and the last marker that does fit is kept instead. |

```bash
python scripts/fix_raw_data_consistency.py                          # dry run on data/BioLab
python scripts/fix_raw_data_consistency.py --apply
python scripts/fix_raw_data_consistency.py --fix markers --apply     # one class of fix only
python scripts/fix_raw_data_consistency.py --apply --backup-dir data/_biolab_backup
```

Outputs `reports/raw_data_fixes_report.md` plus a CSV of every change (override with `--report-path`).

Safeguards, because this is the one script that writes to the raw exports:

- **Nothing is written without `--apply`.** The default is a dry run that produces the same report with every change marked `planned`.
- **Every change is reversible from the CSV**, which records the previous filename, the complete previous header line, and the removed marker rows verbatim. `--backup-dir` additionally keeps a copy of each file whose contents change.
- **Rewrites are byte-preserving.** Files are edited as bytes and only the one line that changes is replaced, so line endings, decimal separators, and every data row survive untouched. A signal file is streamed rather than loaded, so a 30 MB export costs no memory.
- **Idempotent**: a second run finds nothing to do.
- A rename is skipped if it would collide with a different file, and a channel rename is skipped if the standard name is already present in that file.

Deliberately *not* fixed, and listed under 'Needs manual attention' in the report: a missing `Start` marker, a set of `Start` markers none of which leaves room for a full analysis window, a missing file, a file whose contents contradict its name (several `*_event.txt` files actually hold signal data), an event name that could only be guessed (`DCPP` → `DCP`, available via `--include-guessed-events` once the contents are confirmed), and a channel whose role or signal type is unrecognisable.

For every marker fix the report shows how much recording follows the marker that was kept and how much the event's window needs, and it says so explicitly when the last marker was passed over. That column is worth reading rather than skimming: it is the only place where the script's choice of onset is visible.

The recording length behind that comparison is read by seeking to the end of the signal file, and the window durations come from `parameters.base_params["segmentation"]`. If either is unavailable — an event file with no matching signal file, or the parameters failing to import outside the project environment — the script falls back to keeping the last marker and says so in the report.


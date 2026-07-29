# Analysis Notebooks

Numbered Jupyter notebooks that document the end-to-end TECH processing workflow, from raw Mindware exports through ECG and EDA analyses to final dataset formatting. Execute them sequentially within the project conda environment (see the repository root README) to reproduce the analyses or to iterate on the pipeline.

The notebooks resolve the library via `sys.path.append(Path().cwd().parent / "src")`, so the kernel's working directory must be this folder.

| Notebook | Purpose | Input | Output |
| --- | --- | --- | --- |
| `001_data_preparation.ipynb` | Discover subjects, read each event's raw and event file, split every parent–child dyad into a child and a parent stream, mark event onset/offset, and export one file per subject and role. | `data/Sample TECH` (switch to `data/BioLab` for the full delivery) | `data/interim/signals`, `data/interim/events`, `reports/data_preparation_report.md` + `.csv` |
| `002_ecg_analysis.ipynb` | Clean the ECG, segment it, compute HRV per 30 s analysis window and RSA per segment, flag unusable windows, aggregate to segment level, and baseline-correct. | `data/interim/signals` | `data/processed/ecg/{subject}_{role}/`, `data/final/ecg_metrics/`, `reports/QA/ecg/` |
| `003_eda_analyis.ipynb` | Preprocess the EDA signal with NeuroKit2, filter SCR artefacts, segment, extract interval-related features, and baseline-correct. | `data/interim/signals` | `data/processed/eda/{subject}_{role}/`, `data/final/eda_features/` |
| `004_reformat_final_datasets.ipynb` | Reshape the final ECG and EDA datasets from long to wide format and merge them with behavioral data. **Not yet adapted to TECH** — see the note below. | `data/final/*`, `data/behavioral/` | `data/final/neuro-behavioral_data.xlsx` |
| `005_eda_preproc_plot.ipynb` | Craft per-segment visualizations of the EDA preprocessing (raw/cleaned, phasic with SCR peaks, tonic) for the subjects listed in `SUBJECT_ID`. | `data/interim/signals` | `reports/{subject_id}_{segment}_eda.png` |

## Conventions
- Event names and per-event window durations are read from `parameters.base_params['segmentation']`, so the notebooks stay in sync with the pipeline configuration rather than hard-coding the five TECH events.
- After `001`, a "subject" is a dyad member: `subject_id` is `{subject}_{role}`, e.g. `T001_child` and `T001_parent`. Every later notebook loops over those files independently.
- Segments run from the `Start` marker for a fixed duration; the `End` marker in the event files is ignored.
- Notebook `002` writes ECG QA plots only when `create_qa_plots=True`. It is currently set to `False` because plotting every 30 s window dominates the runtime.

## Status of `004_reformat_final_datasets.ipynb`
This notebook was carried over unchanged from the original story-listening project. It pivots on story names (`Story 1`–`Story 5`, later recoded to story codes such as `AC`/`BH`) and reads `data/behavioral/filtered_data_v3 (with ASAs).xlsx`. Neither the story segments nor that workbook exist for TECH, so the notebook fails on the first behavioral-data cell and produces no output. Adapting it requires deciding how the TECH segments (`DCP`, `IDP`, `NDCP`, `Recovery`) and the child/parent roles should be laid out in the wide format, and which behavioral dataset to merge.

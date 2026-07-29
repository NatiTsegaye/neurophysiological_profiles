"""
Check a folder of Mindware exports against what `001_data_preparation.ipynb` expects.

The data-preparation notebook discovers subjects by globbing `*_raw.txt`, takes the subject
id as the first underscore-separated token of the filename, and then builds the path of every
file it needs as `{subject_id}_{event_name}_{raw|event}.txt`. Anything that does not match that
convention exactly is never opened, and the affected event is silently dropped from the analysis.
The notebook also selects the signal columns by name (`TECH-CHILD_*` / `TECH-PARENT_*`), so a
renamed channel makes the read fail even when the filename is perfect.

This script therefore checks two things and writes a report:

1. Naming convention - simulates the notebook's own file discovery to find files it would never
   read and (subject, event) combinations it would consider missing.
2. Column names and file structure - reads the header of every file and validates the columns,
   the declared sample rate, the time axis, and the event markers.

Only the first few lines of each file are read, so the check runs in seconds even on multi-GB
exports. Consequently, problems that depend on the full recording (e.g. a recording too short for
the requested analysis window) are out of scope here - the notebook's own report covers those.

Usage:
    python scripts/check_raw_data_consistency.py                        # checks data/BioLab
    python scripts/check_raw_data_consistency.py --data-dir "data/Sample TECH"
    python scripts/check_raw_data_consistency.py --strict               # exit code 1 on errors
"""

from __future__ import annotations

# fmt: off
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
# fmt: on


# --------------------------------------------------------------------------------------
# What the notebook expects
# --------------------------------------------------------------------------------------

# Mirrors the ROLES mapping in 001_data_preparation.ipynb: the raw file holds both members of
# the dyad and each role is selected by these column names.
ROLE_COLUMNS: Dict[str, List[str]] = {
    "child": ["TECH-CHILD_Bio", "TECH-CHILD_GSC"],
    "parent": ["TECH-PARENT_Bio", "TECH-PARENT_GSC"],
}
TIME_COLUMN = "Time (s)"
REQUIRED_RAW_COLUMNS = [TIME_COLUMN] + [col for cols in ROLE_COLUMNS.values() for col in cols]

# The notebook reads the event file with a plain header row and uses the 'Name' and 'Time' columns.
REQUIRED_EVENT_COLUMNS = ["Name", "Time"]
OPTIONAL_EVENT_COLUMNS = ["Event Type"]

ONSET_MARKER = "Start"   # used as the event onset
OFFSET_MARKER = "End"    # present by convention, but ignored by the notebook
KINDS = ("raw", "event")

FALLBACK_EXPECTED_EVENTS = ["Baseline", "DCP", "IDP", "NDCP", "Recovery"]
FALLBACK_SAMPLING_FREQUENCY = 500

SUBJECT_PATTERN = re.compile(r"^T\d{3}$")
# Deliberately tolerant: spaces or underscores as separators and any casing, so that misnamed
# files can still be attributed to a subject and event and a corrected name can be suggested.
FILENAME_PATTERN = re.compile(
    r"^(?P<subject>[A-Za-z]+[ _]?\d+)[ _]+(?P<event>[A-Za-z0-9]+)[ _]+(?P<kind>raw|event)$",
    re.IGNORECASE,
)

# An event file holds a handful of marker rows; anything larger is almost certainly signal data.
MAX_PLAUSIBLE_EVENT_FILE_BYTES = 100_000

SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_ORDER = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1}


def load_pipeline_expectations(repo_root: Path) -> Tuple[List[str], float, List[str]]:
    """Read the expected event names and sampling frequency from the pipeline parameters.

    Importing them (rather than hard-coding) keeps this check in sync with the notebook, which
    also derives its event list from `parameters.base_params['segmentation']`.
    """
    notes: List[str] = []
    sys.path.insert(0, str(repo_root / "src"))
    try:
        import ecg_utils.parameters as parameters  # noqa: PLC0415 - optional, resolved at runtime

        segmentation = parameters.base_params["segmentation"]
        expected_events = [seg["event_name"] for seg in segmentation.values()]
        sampling_frequency = parameters.base_params["general"]["sampling_frequency"]
    except Exception as exc:  # the check must still run outside the project environment
        notes.append(
            f"Could not import `src/ecg_utils/parameters.py` ({exc}); "
            f"fell back to the built-in defaults."
        )
        expected_events = list(FALLBACK_EXPECTED_EVENTS)
        sampling_frequency = FALLBACK_SAMPLING_FREQUENCY
    finally:
        sys.path.pop(0)
    return expected_events, float(sampling_frequency), notes


# --------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------


@dataclass
class Finding:
    """One problem worth reporting, always tied to a file or a (subject, event) pair."""

    severity: str
    category: str
    subject_id: str
    event_name: str
    file_name: str
    message: str
    suggestion: str = ""

    def sort_key(self) -> Tuple:
        return (SEVERITY_ORDER.get(self.severity, 9), self.category, self.subject_id, self.file_name)


@dataclass
class FileRecord:
    """Everything learned about a single file on disk."""

    path: Path
    name: str
    size_bytes: int
    # Filename interpretation (best effort, tolerant of misnaming)
    subject_id: Optional[str] = None
    event_name: Optional[str] = None
    kind: Optional[str] = None
    canonical_name: Optional[str] = None
    naming_issues: List[str] = field(default_factory=list)
    # The subject id the notebook would infer from this filename, which differs from `subject_id`
    # whenever the separators are wrong.
    notebook_subject_token: str = ""
    # Content
    content_kind: Optional[str] = None  # what the file actually looks like inside
    validated_as: Optional[str] = None  # the structure its columns were checked against
    columns: List[str] = field(default_factory=list)
    declared_sample_rate: Optional[float] = None
    marker_names: List[str] = field(default_factory=list)
    column_issues: List[str] = field(default_factory=list)

    @property
    def naming_ok(self) -> bool:
        return not self.naming_issues

    @property
    def columns_ok(self) -> bool:
        return not self.column_issues


# --------------------------------------------------------------------------------------
# Filename checks
# --------------------------------------------------------------------------------------


def resolve_event_token(token: str, expected_events: Sequence[str]) -> Tuple[Optional[str], str]:
    """Map an event token from a filename onto an expected event name.

    Returns the resolved event name and how it was resolved: 'exact', 'case', 'similar' (a likely
    typo, e.g. 'DCPP' for 'DCP') or 'unknown'.
    """
    for event in expected_events:
        if token == event:
            return event, "exact"
    for event in expected_events:
        if token.lower() == event.lower():
            return event, "case"
    # Prefix match in either direction catches doubled or truncated letters. Prefer the longest
    # candidate so that a token is not attributed to an unnecessarily short event name.
    candidates = [
        event
        for event in expected_events
        if token.lower().startswith(event.lower()) or event.lower().startswith(token.lower())
    ]
    if candidates:
        return max(candidates, key=len), "similar"
    return None, "unknown"


def analyse_filename(record: FileRecord, expected_events: Sequence[str]) -> None:
    """Fill in the subject/event/kind of a file and record any deviation from the convention."""
    stem = record.path.stem
    record.notebook_subject_token = stem.split("_")[0]

    match = FILENAME_PATTERN.match(stem)
    if not match:
        record.naming_issues.append("does not match `{subject_id}_{event_name}_{raw|event}.txt`")
        return

    subject_token = match.group("subject")
    event_token = match.group("event")
    kind_token = match.group("kind")

    subject_id = subject_token.replace(" ", "").replace("_", "").upper()
    if not SUBJECT_PATTERN.match(subject_id):
        record.naming_issues.append(
            f"subject id '{subject_token}' is not of the form T### (e.g. T001)"
        )
    if subject_token != subject_id:
        record.naming_issues.append(
            f"subject id is written as '{subject_token}' instead of '{subject_id}'"
        )

    event_name, how = resolve_event_token(event_token, expected_events)
    if how == "case":
        record.naming_issues.append(
            f"event name '{event_token}' has the wrong capitalisation (expected '{event_name}')"
        )
    elif how == "similar":
        record.naming_issues.append(
            f"event name '{event_token}' is not a known event; it looks like '{event_name}'"
        )
    elif how == "unknown":
        record.naming_issues.append(
            f"event name '{event_token}' is not one of the expected events "
            f"({', '.join(expected_events)})"
        )

    kind = kind_token.lower()
    if kind_token != kind:
        record.naming_issues.append(
            f"file-type suffix is written as '{kind_token}' instead of '{kind}'"
        )

    # The separator between the three tokens must be a single underscore.
    if " " in stem:
        record.naming_issues.append("uses a space instead of an underscore as separator")

    record.subject_id = subject_id
    record.event_name = event_name
    record.kind = kind
    if event_name:
        record.canonical_name = f"{subject_id}_{event_name}_{kind}.txt"


# --------------------------------------------------------------------------------------
# Content checks
# --------------------------------------------------------------------------------------


def read_lines(path: Path, max_lines: int) -> List[str]:
    """Read at most `max_lines` lines, tolerating the CRLF endings and stray bytes of the exports."""
    lines: List[str] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for _ in range(max_lines):
            line = handle.readline()
            if not line:
                break
            lines.append(line.rstrip("\r\n"))
    return lines


def parse_sample_rate(line: str) -> Optional[float]:
    """Extract the numeric sample rate from the `Sample Rate:<tab>500.000000` first line."""
    for token in reversed(re.split(r"[\t:]+", line)):
        token = token.strip()
        if not token:
            continue
        try:
            return float(token.replace(",", "."))
        except ValueError:
            continue
    return None


def to_float(value: str) -> Optional[float]:
    """Parse a number that may use a comma as the decimal separator, as `common.comma_str_2_float`."""
    try:
        return float(value.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None


def looks_like_raw(first_line: str) -> bool:
    return first_line.lower().startswith("sample rate")


def looks_like_event(first_line: str) -> bool:
    fields = [f.strip() for f in first_line.split("\t")]
    return "Name" in fields and "Time" in fields


def inspect_raw_file(record: FileRecord, sampling_frequency: float) -> None:
    """Validate the header, sample rate and time axis of a signal file."""
    lines = read_lines(record.path, 5)
    if not lines:
        record.column_issues.append("file is empty")
        return

    record.declared_sample_rate = parse_sample_rate(lines[0])
    if len(lines) < 2:
        record.column_issues.append("file has no header row")
        return

    record.columns = [col.strip() for col in lines[1].split("\t")]
    columns = record.columns

    missing = [col for col in REQUIRED_RAW_COLUMNS if col not in columns]
    if missing:
        record.column_issues.append(f"missing required column(s): {', '.join(missing)}")

    unexpected = [col for col in columns if col not in REQUIRED_RAW_COLUMNS]
    if unexpected:
        record.column_issues.append(f"unexpected column(s): {', '.join(unexpected)}")

    duplicates = sorted({col for col, count in Counter(columns).items() if count > 1})
    if duplicates:
        record.column_issues.append(f"duplicated column name(s): {', '.join(duplicates)}")

    if record.declared_sample_rate is None:
        record.column_issues.append("could not read the sample rate from the first line")
    elif abs(record.declared_sample_rate - sampling_frequency) > 1e-6:
        record.column_issues.append(
            f"declared sample rate is {record.declared_sample_rate:g} Hz but the pipeline "
            f"assumes {sampling_frequency:g} Hz"
        )

    data_rows = [line.split("\t") for line in lines[2:] if line.strip()]
    if not data_rows:
        record.column_issues.append("file has a header but no data rows")
        return

    for row_number, row in enumerate(data_rows, start=1):
        if len(row) != len(columns):
            record.column_issues.append(
                f"data row {row_number} has {len(row)} value(s) but the header has {len(columns)}"
            )
            break

    if TIME_COLUMN in columns:
        time_index = columns.index(TIME_COLUMN)
        times = [to_float(row[time_index]) for row in data_rows if time_index < len(row)]
        times = [t for t in times if t is not None]
        if not times:
            record.column_issues.append(f"could not parse the '{TIME_COLUMN}' values")
        else:
            # The notebook converts marker times to row positions assuming t=0 at the first sample.
            if abs(times[0]) > 1e-6:
                record.column_issues.append(
                    f"the time axis starts at {times[0]:g}s instead of 0s, so marker times will "
                    f"not map onto the right rows"
                )
            if len(times) > 1 and record.declared_sample_rate:
                expected_step = 1.0 / record.declared_sample_rate
                actual_step = times[1] - times[0]
                if abs(actual_step - expected_step) > expected_step * 0.05:
                    record.column_issues.append(
                        f"the time step between the first samples is {actual_step:g}s but the "
                        f"declared sample rate implies {expected_step:g}s"
                    )


def inspect_event_file(record: FileRecord) -> None:
    """Validate the header and markers of an event file."""
    if record.size_bytes > MAX_PLAUSIBLE_EVENT_FILE_BYTES:
        record.column_issues.append(
            f"file is {record.size_bytes / 1e6:.1f} MB, far larger than a marker list should be"
        )

    lines = read_lines(record.path, 200)
    if not lines:
        record.column_issues.append("file is empty")
        return

    record.columns = [col.strip() for col in lines[0].split("\t")]
    columns = record.columns

    missing = [col for col in REQUIRED_EVENT_COLUMNS if col not in columns]
    if missing:
        record.column_issues.append(f"missing required column(s): {', '.join(missing)}")
        return

    missing_optional = [col for col in OPTIONAL_EVENT_COLUMNS if col not in columns]
    if missing_optional:
        record.column_issues.append(f"missing expected column(s): {', '.join(missing_optional)}")

    name_index = columns.index("Name")
    time_index = columns.index("Time")

    unparsable_times: List[str] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split("\t")
        if name_index >= len(fields) or time_index >= len(fields):
            record.column_issues.append("at least one marker row has fewer columns than the header")
            continue
        marker = fields[name_index].strip()
        record.marker_names.append(marker)
        if to_float(fields[time_index]) is None:
            unparsable_times.append(marker or "<unnamed>")

    if unparsable_times:
        record.column_issues.append(
            f"non-numeric 'Time' value(s) for marker(s): {', '.join(unparsable_times[:5])}"
        )


def inspect_content(record: FileRecord, sampling_frequency: float) -> None:
    """Decide what a file actually contains and validate it against that structure."""
    lines = read_lines(record.path, 1)
    first_line = lines[0] if lines else ""

    if looks_like_raw(first_line):
        record.content_kind = "raw"
    elif looks_like_event(first_line):
        record.content_kind = "event"
    else:
        record.content_kind = "unknown"

    if record.kind and record.content_kind not in (None, "unknown") and record.content_kind != record.kind:
        record.column_issues.append(
            f"named as a '{record.kind}' file but the contents are a '{record.content_kind}' file"
        )
    elif record.content_kind == "unknown":
        record.column_issues.append("the first line matches neither a signal nor an event file header")

    # Validate against the structure the file actually has, so that a mix-up is reported once
    # instead of also producing a list of columns 'missing' from a schema that never applied.
    record.validated_as = record.content_kind if record.content_kind != "unknown" else record.kind
    if record.validated_as == "event":
        inspect_event_file(record)
    else:
        inspect_raw_file(record, sampling_frequency)


# --------------------------------------------------------------------------------------
# Notebook simulation
# --------------------------------------------------------------------------------------


def simulate_notebook(
    file_names: Sequence[str],
    expected_events: Sequence[str],
    case_sensitive: bool,
    extra_subject_ids: Sequence[str] = (),
) -> Tuple[List[str], Dict[Tuple[str, str], Dict[str, str]], List[str]]:
    """Reproduce the notebook's file discovery to see exactly which data it would pick up.

    `case_sensitive=False` reflects Windows, where `Path.glob` and `Path.exists` ignore case;
    `case_sensitive=True` reflects macOS/Linux. Returns the discovered subject ids, the files
    resolved per (subject, event), and the names of the files that are never read.

    `extra_subject_ids` are resolved as well but not treated as discovered, which shows what the
    notebook would find for a subject whose files exist yet whose id it never picks up.
    """

    def normalise(name: str) -> str:
        return name if case_sensitive else name.lower()

    lookup: Dict[str, str] = {}
    for name in file_names:
        lookup.setdefault(normalise(name), name)

    discovered_raw = [name for name in file_names if normalise(name).endswith(normalise("_raw.txt"))]
    subject_ids = sorted({Path(name).stem.split("_")[0] for name in discovered_raw})

    resolved: Dict[Tuple[str, str], Dict[str, str]] = {}
    used: set = set()
    discovered = set(subject_ids)
    for subject_id in sorted(discovered | set(extra_subject_ids)):
        for event_name in expected_events:
            found: Dict[str, str] = {}
            for kind in KINDS:
                actual = lookup.get(normalise(f"{subject_id}_{event_name}_{kind}.txt"))
                if actual is not None:
                    found[kind] = actual
                    # Only files reached through a discovered subject are actually read.
                    if subject_id in discovered:
                        used.add(actual)
            resolved[(subject_id, event_name)] = found

    unused = sorted(name for name in file_names if name not in used)
    return subject_ids, resolved, unused


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def classify_channel(column: str) -> Tuple[Optional[str], str, bool]:
    """Guess which standard signal column a non-standard channel name corresponds to.

    Mindware exports name a channel after the recording site, so the role (`CHILD`/`PARENT`) and
    the signal type (`_Bio`/`_GSC`) can be recovered even from a misspelled name. A trailing number
    marks an additional channel of the same signal rather than a renamed one.

    Returns the standard column name it corresponds to (or None), a human-readable interpretation,
    and whether it is an additional channel rather than a renamed one.
    """
    stripped = column.strip()
    is_secondary = bool(re.search(r"\s\d+$", stripped))
    base = re.sub(r"\s\d+$", "", stripped).upper()

    if "CHILD" in base:
        role = "CHILD"
    elif "PARENT" in base or "MOTHER" in base:
        role = "PARENT"
    else:
        return None, "role cannot be recognised from the name", is_secondary

    if base.endswith("_BIO"):
        signal = "Bio"
    elif base.endswith("_GSC"):
        signal = "GSC"
    else:
        return None, "signal type cannot be recognised from the name", is_secondary

    note = (
        "an extra channel of the same signal"
        if is_secondary
        else "a misspelling of the standard channel name"
    )
    return f"TECH-{role}_{signal}", note, is_secondary


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[object]], empty: str) -> str:
    """Render a Markdown table without requiring the optional 'tabulate' dependency."""
    if not rows:
        return empty
    lines = [
        "| " + " | ".join(str(h) for h in headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines += ["| " + " | ".join(str(value) for value in row) + " |" for row in rows]
    return "\n".join(lines)


def build_report(
    data_dir: Path,
    records: List[FileRecord],
    findings: List[Finding],
    expected_events: Sequence[str],
    sampling_frequency: float,
    subject_ids: Sequence[str],
    all_subject_ids: Sequence[str],
    resolved: Dict[Tuple[str, str], Dict[str, str]],
    unused_windows: Sequence[str],
    unused_posix: Sequence[str],
    notes: Sequence[str],
) -> str:
    n_errors = sum(1 for f in findings if f.severity == SEVERITY_ERROR)
    n_warnings = sum(1 for f in findings if f.severity == SEVERITY_WARNING)
    # Subjects that have data in the folder, whether or not the notebook can see them.
    valid_subjects = [s for s in all_subject_ids if SUBJECT_PATTERN.match(s)]
    discovered_valid = [s for s in subject_ids if SUBJECT_PATTERN.match(s)]
    invented_subjects = [s for s in subject_ids if not SUBJECT_PATTERN.match(s)]
    unreachable_subjects = [s for s in valid_subjects if s not in set(subject_ids)]
    expected_pairs = [(s, e) for s in valid_subjects for e in expected_events]
    complete_pairs = [key for key in expected_pairs if len(resolved.get(key, {})) == len(KINDS)]
    signal_files = [r for r in records if r.validated_as == "raw" and r.columns]
    n_signal_files = len(signal_files)
    n_usable_signal_files = sum(
        1 for r in signal_files if all(col in r.columns for col in REQUIRED_RAW_COLUMNS)
    )

    lines: List[str] = [
        "# Raw Data Consistency Report",
        "",
        f"_Generated: {datetime.now():%Y-%m-%d %H:%M:%S}_",
        "",
        f"Folder checked: `{data_dir}`",
        "",
        "## What was checked",
        "",
        "The data-preparation notebook (`001_data_preparation.ipynb`) discovers subjects by globbing",
        "`*_raw.txt`, takes the subject id as the first underscore-separated token of the filename, and",
        "then opens each file it needs by building the path `{subject_id}_{event_name}_{raw|event}.txt`.",
        "Files that deviate from that convention are never opened and the affected event drops out of",
        "the analysis without an error. The notebook also selects the signal columns by name, so a",
        "renamed channel breaks the read even when the filename is correct. This report checks:",
        "",
        "1. **Naming convention** - by reproducing the notebook's own file discovery, so the findings",
        "   reflect what the pipeline would actually load rather than a stylistic preference.",
        f"2. **Column names and structure** - required signal columns "
        f"(`{'`, `'.join(REQUIRED_RAW_COLUMNS)}`), required event columns "
        f"(`{'`, `'.join(REQUIRED_EVENT_COLUMNS + OPTIONAL_EVENT_COLUMNS)}`), the declared sample rate",
        f"   (expected {sampling_frequency:g} Hz), the time axis, and the presence of the "
        f"`{ONSET_MARKER}` marker.",
        "",
        f"Expected events per subject: {', '.join(f'`{e}`' for e in expected_events)}.",
        "",
        "Only the first lines of each file are read, so anything that depends on the full recording",
        "(such as a recording being too short for its analysis window) is out of scope; the notebook's",
        "own `data_preparation_report.md` covers that.",
        "",
        "## Summary",
        "",
        f"- Files inspected: **{len(records)}**",
        f"- Subjects with data in the folder: **{len(valid_subjects)}**",
        f"- Subjects the notebook would actually process: **{len(discovered_valid)}**"
        + (f" ({len(unreachable_subjects)} unreachable: {', '.join(unreachable_subjects)})" if unreachable_subjects else ""),
        f"- Complete event pairs (raw + event file both found): "
        f"**{len(complete_pairs)} / {len(expected_pairs)}**",
        f"- Files the notebook would never read: **{len(unused_windows)}**",
        f"- Spurious subject ids invented from misnamed files: **{len(invented_subjects)}**"
        + (f" ({', '.join(repr(s) for s in invented_subjects)})" if invented_subjects else ""),
        f"- Files with naming issues: **{sum(1 for r in records if not r.naming_ok)}**",
        f"- Signal files holding all required columns: **{n_usable_signal_files} / {n_signal_files}**",
        f"- Files with column or structure issues: **{sum(1 for r in records if not r.columns_ok)}**",
        f"- Findings: **{n_errors} error(s)**, **{n_warnings} warning(s)**",
        "",
    ]

    if n_errors == 0 and n_warnings == 0:
        lines += ["**Verdict: everything is consistent with what the notebook expects.**", ""]
    else:
        lines += [
            f"**Verdict: {n_errors} issue(s) need fixing before the folder is safe to process.**",
            "",
        ]

    if notes:
        lines += ["> " + note for note in notes] + [""]

    # ---- Findings by category -------------------------------------------------------
    lines += ["## Findings", ""]
    by_category: Dict[str, List[Finding]] = defaultdict(list)
    for finding in findings:
        by_category[finding.category].append(finding)

    if not findings:
        lines += ["No problems found.", ""]
    for category in sorted(by_category, key=lambda c: min(SEVERITY_ORDER.get(f.severity, 9) for f in by_category[c])):
        group = sorted(by_category[category], key=Finding.sort_key)
        lines += [f"### {category} ({len(group)})", ""]
        lines += [
            markdown_table(
                ["Severity", "Subject", "Event", "File", "Problem", "Suggested fix"],
                [
                    [f.severity, f.subject_id or "-", f.event_name or "-", f"`{f.file_name}`" if f.file_name else "-",
                     f.message, f.suggestion or "-"]
                    for f in group
                ],
                "None.",
            ),
            "",
        ]

    # ---- Rename suggestions ---------------------------------------------------------
    renames = [
        (r.name, r.canonical_name)
        for r in records
        if r.canonical_name and r.name != r.canonical_name
    ]
    lines += ["## Suggested renames", ""]
    if renames:
        lines += [
            "Renaming these files makes them visible to the notebook. Check the contents before",
            "renaming a file whose event name was only guessed from a similar spelling.",
            "",
            markdown_table(
                ["Current name", "Expected name"],
                [[f"`{current}`", f"`{expected}`"] for current, expected in sorted(renames)],
                "None.",
            ),
            "",
        ]
    else:
        lines += ["No renames needed.", ""]

    # ---- Column signatures ----------------------------------------------------------
    lines += [
        "## Column names found",
        "",
        "Files are grouped by the structure they actually contain, so a file that was saved under the",
        "wrong name still appears next to the files it resembles.",
        "",
    ]
    for kind, label, required in (
        ("raw", "Signal files", REQUIRED_RAW_COLUMNS),
        ("event", "Event marker files", REQUIRED_EVENT_COLUMNS),
    ):
        signatures: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
        for record in records:
            if record.validated_as == kind and record.columns:
                signatures[tuple(record.columns)].append(record.name)
        rows = []
        for signature, names in sorted(signatures.items(), key=lambda item: -len(item[1])):
            missing = [col for col in required if col not in signature]
            status = "usable" if not missing else f"missing {', '.join(missing)}"
            example = names[0] if len(names) == 1 else f"{names[0]} (+{len(names) - 1} more)"
            rows.append([len(names), status, ", ".join(f"`{c}`" for c in signature), f"`{example}`"])
        lines += [
            f"### {label} (`*_{kind}.txt`)",
            "",
            markdown_table(["Files", "Status", "Columns (in file order)", "Example"], rows, "No files inspected."),
            "",
        ]
    lines += [
        "The notebook selects columns by name, so a differing column *order* is handled",
        "automatically and is only listed above for reference.",
        "",
    ]

    # ---- Non-standard channel names --------------------------------------------------
    signal_records = [r for r in records if r.validated_as == "raw" and r.columns]
    variant_files: Dict[str, List[FileRecord]] = defaultdict(list)
    for record in signal_records:
        for column in record.columns:
            if column not in REQUIRED_RAW_COLUMNS:
                variant_files[column].append(record)

    lines += ["### Non-standard channel names", ""]
    if variant_files:
        rows = []
        for column, affected in sorted(variant_files.items(), key=lambda item: (-len(item[1]), item[0])):
            standard, note, is_secondary = classify_channel(column)
            with_standard = sum(1 for r in affected if standard in r.columns) if standard else 0
            if standard is None:
                consequence = "cannot be mapped automatically"
            elif is_secondary:
                # Whether the required column is present depends on the primary channel, which has
                # its own row; an extra channel is never selected by the notebook.
                consequence = "harmless: never selected by the pipeline"
            elif with_standard == len(affected):
                consequence = "harmless: the standard column is also present"
            elif with_standard == 0:
                consequence = f"**replaces `{standard}`, which is absent**"
            else:
                consequence = f"replaces `{standard}` in {len(affected) - with_standard} of these files"
            rows.append([f"`{column}`", len(affected), f"`{standard}`" if standard else "-", note, consequence])
        lines += [
            "Every channel name that is not one of the standard columns, and what it appears to be:",
            "",
            markdown_table(["Channel", "Files", "Looks like", "Interpretation", "Consequence"], rows, "None."),
            "",
            "A channel that replaces a required column makes the notebook fail with a `KeyError` when it",
            "selects that subject's columns, so these must be renamed (in the file or in the `ROLES`",
            "mapping) before the folder can be processed.",
            "",
        ]
    else:
        lines += ["All channels use the standard names.", ""]

    # ---- Completeness matrix --------------------------------------------------------
    lines += [
        "## Data completeness per subject",
        "",
        "As the notebook would see it: `ok` = both the raw and the event file were found, otherwise the",
        "missing part is named. Subjects marked *not discovered* have data in the folder that the",
        "notebook never reaches because no filename yields their subject id.",
        "",
    ]
    matrix_rows = []
    for subject_id in valid_subjects:
        label = f"`{subject_id}`"
        if subject_id in unreachable_subjects:
            label += " **(not discovered)**"
        row: List[object] = [label]
        for event_name in expected_events:
            found = resolved.get((subject_id, event_name), {})
            if len(found) == len(KINDS):
                row.append("ok")
            elif not found:
                row.append("**both missing**")
            else:
                row.append(f"**no {[k for k in KINDS if k not in found][0]}**")
        matrix_rows.append(row)
    lines += [
        markdown_table(["Subject"] + list(expected_events), matrix_rows, "No subjects discovered."),
        "",
    ]

    # ---- Ignored files --------------------------------------------------------------
    lines += ["## Files the notebook would not read", ""]
    if unused_windows:
        lines += [
            "These files are on disk but are never opened, so their data is silently excluded:",
            "",
        ]
        lines += [f"- `{name}`" for name in unused_windows]
        lines += [""]
    else:
        lines += ["Every file is picked up by the notebook.", ""]

    windows_only = sorted(set(unused_posix) - set(unused_windows))
    if windows_only:
        lines += [
            "### Only readable on Windows",
            "",
            "Windows matches filenames case-insensitively, so these files are found on Windows but",
            "would be skipped on macOS or Linux. Rename them to make the analysis reproducible:",
            "",
        ]
        lines += [f"- `{name}`" for name in windows_only]
        lines += [""]

    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def collect_findings(
    records: List[FileRecord],
    subject_ids: Sequence[str],
    resolved: Dict[Tuple[str, str], Dict[str, str]],
    unused_windows: Sequence[str],
) -> List[Finding]:
    findings: List[Finding] = []
    records_by_name = {record.name: record for record in records}
    unused = set(unused_windows)

    for record in records:
        # A misnamed file is only an error if the notebook actually loses it; a file that is still
        # picked up (e.g. thanks to case-insensitive matching on Windows) is a portability warning.
        severity = SEVERITY_ERROR if record.name in unused else SEVERITY_WARNING
        for issue in record.naming_issues:
            findings.append(
                Finding(
                    severity=severity,
                    category="Filename convention",
                    subject_id=record.subject_id or "",
                    event_name=record.event_name or "",
                    file_name=record.name,
                    message=issue,
                    suggestion=f"rename to `{record.canonical_name}`" if record.canonical_name else "",
                )
            )
        for issue in record.column_issues:
            findings.append(
                Finding(
                    severity=SEVERITY_ERROR,
                    category="File contents",
                    subject_id=record.subject_id or "",
                    event_name=record.event_name or "",
                    file_name=record.name,
                    message=issue,
                )
            )

    # A filename with a wrong separator makes the notebook invent a subject id such as
    # 'T067 Baseline'. Report that once per real subject rather than once per invented id, and
    # skip the per-event rows those ids would otherwise generate.
    discovered = set(subject_ids)
    invented_ids = {sid for sid in discovered if not SUBJECT_PATTERN.match(sid)}
    affected_files: Dict[str, List[str]] = defaultdict(list)
    affected_ids: Dict[str, set] = defaultdict(set)
    for record in records:
        if record.notebook_subject_token in invented_ids:
            true_subject = record.subject_id or record.notebook_subject_token
            affected_files[true_subject].append(record.name)
            affected_ids[true_subject].add(record.notebook_subject_token)

    for subject_id, names in sorted(affected_files.items()):
        invented = ", ".join(f"'{sid}'" for sid in sorted(affected_ids[subject_id]))
        consequence = (
            "those files are excluded from the analysis"
            if subject_id in discovered
            else f"'{subject_id}' is never discovered at all, so none of its data is processed"
        )
        findings.append(
            Finding(
                severity=SEVERITY_ERROR,
                category="Data completeness",
                subject_id=subject_id,
                event_name="",
                file_name="",
                message=(
                    f"{len(names)} file(s) make the notebook read the subject id as {invented} "
                    f"instead of '{subject_id}'; {consequence}"
                ),
                suggestion="rename the file(s) listed under 'Suggested renames'",
            )
        )

    for (subject_id, event_name), found in sorted(resolved.items()):
        if len(found) == len(KINDS):
            continue
        # Only meaningful for subjects the notebook actually iterates over; unreachable subjects are
        # already reported above and would otherwise repeat the same problem for every event.
        if subject_id not in discovered or not SUBJECT_PATTERN.match(subject_id):
            continue
        missing = [kind for kind in KINDS if kind not in found]
        findings.append(
            Finding(
                severity=SEVERITY_ERROR,
                category="Data completeness",
                subject_id=subject_id,
                event_name=event_name,
                file_name="",
                message=f"no {' and no '.join(f'{kind} file' for kind in missing)} found",
                suggestion="check whether the recording exists under a different name",
            )
        )

    # Marker checks only make sense for event files the notebook will actually read.
    for (subject_id, event_name), found in sorted(resolved.items()):
        event_file = found.get("event")
        record = records_by_name.get(event_file) if event_file else None
        if record is None or not record.marker_names:
            continue
        onset_count = record.marker_names.count(ONSET_MARKER)
        if onset_count == 0:
            findings.append(
                Finding(
                    severity=SEVERITY_ERROR,
                    category="Event markers",
                    subject_id=subject_id,
                    event_name=event_name,
                    file_name=record.name,
                    message=(
                        f"no '{ONSET_MARKER}' marker; the notebook falls back to t=0 as the onset, "
                        f"so the segment would not correspond to the task"
                    ),
                    suggestion="add the missing marker or exclude this event",
                )
            )
        elif onset_count > 1:
            findings.append(
                Finding(
                    severity=SEVERITY_WARNING,
                    category="Event markers",
                    subject_id=subject_id,
                    event_name=event_name,
                    file_name=record.name,
                    message=(
                        f"{onset_count} '{ONSET_MARKER}' markers; the notebook silently uses the "
                        f"first one"
                    ),
                    suggestion="confirm which marker is the real onset",
                )
            )
        if ONSET_MARKER in record.marker_names and OFFSET_MARKER not in record.marker_names:
            findings.append(
                Finding(
                    severity=SEVERITY_WARNING,
                    category="Event markers",
                    subject_id=subject_id,
                    event_name=event_name,
                    file_name=record.name,
                    message=f"no '{OFFSET_MARKER}' marker (not used by the notebook, but unusual)",
                )
            )

    return sorted(findings, key=Finding.sort_key)


def main(argv: Optional[Sequence[str]] = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Check raw Mindware exports against the conventions of 001_data_preparation.ipynb.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=repo_root / "data" / "BioLab",
        help="folder holding the raw and event files (default: data/BioLab)",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=repo_root / "reports" / "raw_data_consistency_report.md",
        help="where to write the Markdown report (a .csv of all findings is written alongside it)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit with a non-zero status if any error was found",
    )
    args = parser.parse_args(argv)

    data_dir: Path = args.data_dir if args.data_dir.is_absolute() else repo_root / args.data_dir
    if not data_dir.is_dir():
        parser.error(f"data folder not found: {data_dir}")

    expected_events, sampling_frequency, notes = load_pipeline_expectations(repo_root)

    paths = sorted(p for p in data_dir.iterdir() if p.is_file())
    non_txt = [p.name for p in paths if p.suffix.lower() != ".txt"]
    txt_paths = [p for p in paths if p.suffix.lower() == ".txt"]
    if non_txt:
        notes.append(f"Ignored {len(non_txt)} non-.txt file(s): {', '.join(non_txt[:5])}.")

    print(f"Checking {len(txt_paths)} file(s) in {data_dir}")
    records: List[FileRecord] = []
    for index, path in enumerate(txt_paths, start=1):
        if index % 100 == 0 or index == len(txt_paths):
            print(f"  inspected {index}/{len(txt_paths)}")
        record = FileRecord(path=path, name=path.name, size_bytes=path.stat().st_size)
        analyse_filename(record, expected_events)
        inspect_content(record, sampling_frequency)
        records.append(record)

    file_names = [record.name for record in records]
    # Subjects that plainly have data in the folder, even if the notebook cannot see them.
    inferred_subject_ids = sorted(
        {r.subject_id for r in records if r.subject_id and SUBJECT_PATTERN.match(r.subject_id)}
    )
    subject_ids, resolved, unused_windows = simulate_notebook(
        file_names, expected_events, case_sensitive=False, extra_subject_ids=inferred_subject_ids
    )
    _, _, unused_posix = simulate_notebook(
        file_names, expected_events, case_sensitive=True, extra_subject_ids=inferred_subject_ids
    )

    findings = collect_findings(records, subject_ids, resolved, unused_windows)
    all_subject_ids = sorted(set(subject_ids) | set(inferred_subject_ids))

    report_path: Path = args.report_path if args.report_path.is_absolute() else repo_root / args.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = build_report(
        data_dir=data_dir,
        records=records,
        findings=findings,
        expected_events=expected_events,
        sampling_frequency=sampling_frequency,
        subject_ids=subject_ids,
        all_subject_ids=all_subject_ids,
        resolved=resolved,
        unused_windows=unused_windows,
        unused_posix=unused_posix,
        notes=notes,
    )
    report_path.write_text(report_text, encoding="utf-8")

    findings_csv_path = report_path.with_suffix(".csv")
    with findings_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["severity", "category", "subject_id", "event_name", "file_name", "message", "suggestion"],
        )
        writer.writeheader()
        for finding in findings:
            writer.writerow(asdict(finding))

    n_errors = sum(1 for f in findings if f.severity == SEVERITY_ERROR)
    n_warnings = sum(1 for f in findings if f.severity == SEVERITY_WARNING)
    print(f"\n{n_errors} error(s) and {n_warnings} warning(s) found.")
    print(f"Report written to {report_path}")
    print(f"Findings written to {findings_csv_path}")

    return 1 if (args.strict and n_errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())

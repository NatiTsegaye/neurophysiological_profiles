"""
Apply the mechanical fixes that `check_raw_data_consistency.py` reports.

That script explains what is wrong with a folder of Mindware exports; this one repairs the
subset of problems whose correct outcome is unambiguous, so that the remaining findings are
the ones a researcher actually has to look at:

1. Filenames  - normalise the separator (`T067 Baseline_raw.txt` -> `T067_Baseline_raw.txt`),
                the file-type suffix (`..._RAW.txt` -> `..._raw.txt`), the event name
                (`T082_recovery_raw.txt` -> `T082_Recovery_raw.txt`) and the subject token,
                so the notebook stops silently dropping the file.
2. Channels   - rename a misspelled channel back to the standard name whenever the role
                (child/parent) and the signal type (Bio/GSC) can be read off the name, in
                either capitalisation: `CHILD2_Bio` -> `TECH-CHILD_Bio`,
                `TECH-PARENTT_GSC` -> `TECH-PARENT_GSC`. A trailing index is kept, so the
                extra channel `TECH-PARENTT_Bio 2` becomes `TECH-PARENT_Bio 2` and does not
                collide with the primary channel.
3. Markers    - when an event file holds more than one `Start` marker, keep one and drop the
                rest, because the notebook silently uses the first marker it finds. The later
                marker is normally the real onset, so the last one is kept - unless it falls so
                close to the end of the recording that the analysis window would not fit, which
                means it is an `End` pressed with the wrong key rather than a second onset.

Everything else is left alone and listed under 'Needs manual attention' in the report: a
missing `Start` marker, a set of markers none of which leaves room for a full window, a missing
file, a file whose contents do not match its name, an event name that could only be guessed
(`DCPP`), and channels whose role or signal type cannot be recognised. Those need a decision,
not a rule.

Nothing is written without `--apply`; the default is a dry run that reports what it would do.
Every applied change is written to the report's CSV with enough detail to undo it by hand
(the previous filename, the previous header line, the removed marker rows). Pass a
`--backup-dir` to also keep a copy of every file whose contents are modified.

Usage:
    python scripts/fix_raw_data_consistency.py                          # dry run on data/BioLab
    python scripts/fix_raw_data_consistency.py --apply
    python scripts/fix_raw_data_consistency.py --data-dir "data/Sample TECH" --apply
    python scripts/fix_raw_data_consistency.py --fix markers --apply    # only one class of fix
    python scripts/fix_raw_data_consistency.py --apply --backup-dir data/_biolab_backup
"""

from __future__ import annotations

# fmt: off
import argparse
import csv
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_raw_data_consistency import (  # noqa: E402 - resolved via the line above
    FILENAME_PATTERN,
    MAX_PLAUSIBLE_EVENT_FILE_BYTES,
    ONSET_MARKER,
    REQUIRED_EVENT_COLUMNS,
    REQUIRED_RAW_COLUMNS,
    SUBJECT_PATTERN,
    classify_channel,
    load_pipeline_expectations,
    looks_like_event,
    looks_like_raw,
    markdown_table,
    resolve_event_token,
)
# fmt: on


FIX_NAMES = "names"
FIX_COLUMNS = "columns"
FIX_MARKERS = "markers"
ALL_FIXES = (FIX_NAMES, FIX_COLUMNS, FIX_MARKERS)

# A trailing ' 2' marks an additional channel of the same signal rather than a renamed one, so it
# has to survive the rename.
SECONDARY_SUFFIX_PATTERN = re.compile(r"(\s\d+)$")

# Big enough to keep the copy fast, small enough to stay out of the way in memory.
COPY_CHUNK_BYTES = 4 * 1024 * 1024

STATUS_PLANNED = "planned"
STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"


# --------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------


@dataclass
class Change:
    """One fix for one file, before or after it was applied."""

    fix: str
    file_name: str
    rule: str
    detail: str
    # Context that makes the fix reviewable rather than something to take on trust.
    note: str = ""
    # Enough information to reverse the change by hand.
    previous_value: str = ""
    new_value: str = ""
    status: str = STATUS_PLANNED
    error: str = ""

    def sort_key(self) -> Tuple:
        return (self.fix, self.file_name, self.rule)


@dataclass
class ManualIssue:
    """A problem this script refuses to guess at, so that it shows up in the report anyway."""

    file_name: str
    problem: str
    reason: str

    def sort_key(self) -> Tuple:
        return (self.file_name, self.problem)


@dataclass
class Plan:
    """Everything to be done to the folder."""

    changes: List[Change] = field(default_factory=list)
    manual: List[ManualIssue] = field(default_factory=list)
    # Filled in while planning so that the apply step knows what to do per file.
    renames: Dict[str, str] = field(default_factory=dict)          # current name -> new name
    header_rewrites: Dict[str, str] = field(default_factory=dict)  # name -> new header line
    marker_rewrites: Dict[str, List[int]] = field(default_factory=dict)  # name -> line numbers to drop


# --------------------------------------------------------------------------------------
# Reading files without corrupting them
# --------------------------------------------------------------------------------------
#
# The exports are read as bytes throughout. Decoding them for inspection is fine, but a
# rewrite has to preserve the original bytes of everything it does not deliberately change:
# the line endings, the decimal separators, and any stray non-UTF-8 byte in the file.


def split_terminator(line: bytes) -> Tuple[bytes, bytes]:
    """Split a raw line into its content and its line terminator."""
    for terminator in (b"\r\n", b"\n", b"\r"):
        if line.endswith(terminator):
            return line[: -len(terminator)], terminator
    return line, b""


def decode(raw: bytes) -> str:
    """Decode a header or marker line. latin-1 round-trips any byte, so this never raises."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read_first_lines(path: Path, count: int) -> List[bytes]:
    """Read at most `count` raw lines, terminators included."""
    lines: List[bytes] = []
    with path.open("rb") as handle:
        for _ in range(count):
            line = handle.readline()
            if not line:
                break
            lines.append(line)
    return lines


def recording_length_seconds(path: Path) -> Optional[float]:
    """Read the last timestamp of a signal file by seeking to its end.

    Only the tail of the file is touched, so this stays fast on the multi-MB exports. Iterating
    the tail backwards means the (possibly incomplete) first line of the chunk is reached last.
    """
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(size - 8192, 0))
            tail = handle.read()
    except OSError:
        return None
    for raw_line in reversed(tail.splitlines()):
        fields = decode(raw_line).split("\t")
        try:
            return float(fields[0].strip().replace(",", "."))
        except (ValueError, IndexError):
            continue
    return None


# --------------------------------------------------------------------------------------
# Planning: filenames
# --------------------------------------------------------------------------------------


def plan_filename(
    name: str,
    expected_events: Sequence[str],
    include_guessed_events: bool,
) -> Tuple[Optional[str], List[str], Optional[str]]:
    """Work out the canonical filename for a file.

    Returns the new name (None when nothing should change), the rules that fired, and a reason
    the file was left alone when it deviates from the convention but cannot be fixed safely.
    """
    stem = Path(name).stem
    suffix = Path(name).suffix
    rules: List[str] = []

    match = FILENAME_PATTERN.match(stem)
    if not match:
        return None, [], "filename does not match `{subject_id}_{event_name}_{raw|event}.txt`"

    subject_token = match.group("subject")
    event_token = match.group("event")
    kind_token = match.group("kind")

    subject_id = subject_token.replace(" ", "").replace("_", "").upper()
    if not SUBJECT_PATTERN.match(subject_id):
        return None, [], f"subject id '{subject_token}' is not of the form T### (e.g. T001)"
    if subject_token != subject_id:
        rules.append("subject id formatting")

    event_name, how = resolve_event_token(event_token, expected_events)
    if how == "unknown":
        return None, [], (
            f"event name '{event_token}' is not one of the expected events "
            f"({', '.join(expected_events)})"
        )
    if how == "similar" and not include_guessed_events:
        return None, [], (
            f"event name '{event_token}' only looks like '{event_name}'; check the contents, then "
            f"re-run with --include-guessed-events"
        )
    if how == "case":
        rules.append("event name capitalisation")
    elif how == "similar":
        rules.append(f"event name guessed from '{event_token}'")

    kind = kind_token.lower()
    if kind_token != kind:
        rules.append("file-type suffix capitalisation")

    # The separator between the three tokens must be a single underscore.
    if " " in stem:
        rules.append("space instead of underscore separator")

    if suffix != ".txt":
        rules.append("file extension capitalisation")

    new_name = f"{subject_id}_{event_name}_{kind}.txt"
    if new_name == name:
        return None, [], None
    return new_name, rules, None


# --------------------------------------------------------------------------------------
# Planning: channel names
# --------------------------------------------------------------------------------------


def canonical_channel_name(column: str) -> Tuple[Optional[str], str]:
    """Return the standard name for a channel, keeping any trailing channel index.

    `classify_channel` recovers the role and signal type from a misspelled name; the trailing
    index has to be re-attached so that an extra channel stays an extra channel.
    """
    standard, note, _is_secondary = classify_channel(column)
    if standard is None:
        return None, note
    match = SECONDARY_SUFFIX_PATTERN.search(column.strip())
    return standard + (match.group(1) if match else ""), note


def plan_raw_header(path: Path) -> Tuple[Optional[str], List[str], List[ManualIssue]]:
    """Plan the channel renames for one signal file.

    Returns the new header line (None when nothing should change), a description of each
    rename, and the problems that a rename cannot solve.
    """
    name = path.name
    manual: List[ManualIssue] = []
    lines = read_first_lines(path, 2)
    if len(lines) < 2:
        return None, [], [ManualIssue(name, "file has no header row", "nothing to rename")]

    header_content, _ = split_terminator(lines[1])
    columns = decode(header_content).split("\t")
    stripped = [column.strip() for column in columns]

    new_columns = list(columns)
    renames: List[str] = []
    # Renaming into a name that is already taken would create a duplicate column, so the target
    # set has to be checked against the whole header, not just the column being renamed.
    taken = set(stripped)

    for index, column in enumerate(stripped):
        if column in REQUIRED_RAW_COLUMNS:
            continue
        target, note = canonical_channel_name(column)
        if target is None:
            manual.append(
                ManualIssue(name, f"channel `{column}` cannot be mapped to a standard name", note)
            )
            continue
        if target == column:
            continue
        if target in taken:
            manual.append(
                ManualIssue(
                    name,
                    f"channel `{column}` looks like `{target}`",
                    f"`{target}` is already present in this file, so renaming would duplicate it",
                )
            )
            continue
        new_columns[index] = target
        taken.discard(column)
        taken.add(target)
        renames.append(f"`{column}` -> `{target}`")

    if not renames:
        return None, [], manual

    # Renaming cannot invent a channel that was never recorded; say so rather than leaving the
    # impression that the file is now usable.
    still_missing = [col for col in REQUIRED_RAW_COLUMNS if col not in taken]
    if still_missing:
        manual.append(
            ManualIssue(
                name,
                f"still missing after renaming: {', '.join(still_missing)}",
                "the channel is absent from the file, not misnamed",
            )
        )

    return "\t".join(new_columns), renames, manual


# --------------------------------------------------------------------------------------
# Planning: event markers
# --------------------------------------------------------------------------------------


def marker_seconds(time_text: str) -> Optional[float]:
    try:
        return float(time_text.strip().replace(",", "."))
    except ValueError:
        return None


def choose_onset(
    onset_times: Sequence[Optional[float]],
    length_seconds: Optional[float],
    window_seconds: Optional[float],
) -> Tuple[Optional[int], str]:
    """Pick which of several `Start` markers is the real onset.

    The later marker is normally the real one, because the earlier press was a false start. But a
    marker so late that the rest of the recording cannot hold the analysis window is far more
    likely to be an `End` pressed with the wrong key, so the last marker that does leave room for
    a full window is preferred. When no marker leaves room, the event is left alone: the choice
    then changes which incomplete segment is analysed, which is not a decision to automate.

    Returns the index of the marker to keep (None to leave the file alone) and, when the last
    marker was passed over, the reason why.
    """
    last = len(onset_times) - 1
    if length_seconds is None or window_seconds is None:
        return last, "the recording length or the analysis window is unknown, so the last marker was kept"

    def fits(onset: Optional[float]) -> bool:
        return onset is not None and length_seconds - onset + 1e-6 >= window_seconds

    if fits(onset_times[last]):
        return last, ""
    for index in range(last - 1, -1, -1):
        if fits(onset_times[index]):
            shortfall = (
                f"{length_seconds - onset_times[last]:.0f}s"
                if onset_times[last] is not None
                else "nothing"
            )
            return index, (
                f"**the last marker left only {shortfall} of the {window_seconds:.0f}s window, so "
                f"the last marker that does fit was kept instead**"
            )
    return None, ""


def describe_room_after_onset(
    onset_seconds: Optional[float],
    length_seconds: Optional[float],
    window_seconds: Optional[float],
) -> str:
    """Say how much recording is left after the marker that was kept.

    Shown next to every marker fix so the choice can be checked at a glance rather than
    rediscovered later in `data_preparation_report.md`.
    """
    if onset_seconds is None or length_seconds is None:
        return ""
    remaining = length_seconds - onset_seconds
    if remaining < 0:
        return (
            f"**the kept marker is {abs(remaining):.0f}s past the end of the "
            f"{length_seconds:.0f}s recording**"
        )
    text = f"{remaining:.0f}s of {length_seconds:.0f}s left after the kept marker"
    if window_seconds is None:
        return text
    if remaining + 1e-6 < window_seconds:
        return f"**{text}, short of the {window_seconds:.0f}s window**"
    return f"{text} ({window_seconds:.0f}s needed)"


def plan_event_markers(
    path: Path,
    signal_path: Optional[Path] = None,
    window_seconds: Optional[float] = None,
) -> Tuple[List[int], List[str], str, List[ManualIssue]]:
    """Plan which duplicate `Start` rows to drop from one event file.

    Returns the 0-based line numbers to drop, a description of each dropped row, a note on how
    much recording follows the marker that was kept, and the problems that need a human.
    """
    name = path.name
    manual: List[ManualIssue] = []
    raw_lines = path.read_bytes().splitlines(keepends=True)
    if not raw_lines:
        return [], [], "", [ManualIssue(name, "file is empty", "nothing to fix")]

    header = [field.strip() for field in decode(split_terminator(raw_lines[0])[0]).split("\t")]
    missing = [column for column in REQUIRED_EVENT_COLUMNS if column not in header]
    if missing:
        return [], [], "", [
            ManualIssue(name, f"missing required column(s): {', '.join(missing)}", "cannot read the markers")
        ]

    name_index = header.index("Name")
    time_index = header.index("Time")

    onset_rows: List[Tuple[int, str]] = []
    for line_number, raw_line in enumerate(raw_lines[1:], start=1):
        content = decode(split_terminator(raw_line)[0])
        if not content.strip():
            continue
        fields = content.split("\t")
        if name_index >= len(fields):
            continue
        if fields[name_index].strip() != ONSET_MARKER:
            continue
        time_value = fields[time_index].strip() if time_index < len(fields) else "?"
        onset_rows.append((line_number, time_value))

    if not onset_rows:
        return [], [], "", [
            ManualIssue(
                name,
                f"no '{ONSET_MARKER}' marker",
                "the onset has to be recovered from the recording notes; the notebook would fall "
                "back to t=0",
            )
        ]
    if len(onset_rows) == 1:
        return [], [], "", manual

    onset_times = [marker_seconds(time_value) for _, time_value in onset_rows]
    length_seconds = recording_length_seconds(signal_path) if signal_path else None
    kept_index, reason = choose_onset(onset_times, length_seconds, window_seconds)

    if kept_index is None:
        return [], [], "", [
            ManualIssue(
                name,
                f"{len(onset_rows)} '{ONSET_MARKER}' markers, none of which leaves room for the "
                f"{window_seconds:.0f}s window",
                f"the recording is only {length_seconds:.0f}s long, so no marker yields a complete "
                f"segment; which onset to use, and whether to keep the event at all, is a decision",
            )
        ]

    drop_lines = [line_number for index, (line_number, _) in enumerate(onset_rows) if index != kept_index]
    described = [
        f"{'kept' if index == kept_index else 'dropped'} '{ONSET_MARKER}' at t={time_value}s "
        f"(line {line_number + 1})"
        for index, (line_number, time_value) in enumerate(onset_rows)
    ]
    room = describe_room_after_onset(onset_times[kept_index], length_seconds, window_seconds)
    note = f"{reason}; {room}" if reason and room else reason or room
    return drop_lines, described, note, manual


# --------------------------------------------------------------------------------------
# Planning: the whole folder
# --------------------------------------------------------------------------------------


def load_segment_durations(repo_root: Path) -> Dict[str, float]:
    """Read the per-event analysis window from the pipeline parameters.

    Used only to annotate the marker fixes, so an import failure is not fatal: without the
    durations the report simply omits the comparison.
    """
    sys.path.insert(0, str(repo_root / "src"))
    try:
        import ecg_utils.parameters as parameters  # noqa: PLC0415 - optional, resolved at runtime

        return {
            segment["event_name"]: float(segment["duration_seconds"])
            for segment in parameters.base_params["segmentation"].values()
            if "duration_seconds" in segment
        }
    except Exception:
        return {}
    finally:
        sys.path.pop(0)


def event_name_from_filename(name: str, expected_events: Sequence[str]) -> Optional[str]:
    """The expected event a filename refers to, tolerating a misspelled or miscased token."""
    match = FILENAME_PATTERN.match(Path(name).stem)
    if not match:
        return None
    event_name, _how = resolve_event_token(match.group("event"), expected_events)
    return event_name


def signal_sibling(event_path: Path) -> Optional[Path]:
    """The signal file that belongs to an event file, whatever the state of its name."""
    name = event_path.name
    if not name.lower().endswith("_event.txt"):
        return None
    candidate = event_path.with_name(name[: -len("_event.txt")] + "_raw.txt")
    return candidate if candidate.exists() else None


def build_plan(
    data_dir: Path,
    expected_events: Sequence[str],
    fixes: Sequence[str],
    include_guessed_events: bool,
    segment_durations: Optional[Dict[str, float]] = None,
) -> Plan:
    plan = Plan()
    paths = sorted(p for p in data_dir.iterdir() if p.is_file())

    # The names already on disk and the names a planned rename has taken, so that two files can
    # never be renamed onto each other.
    existing = {p.name.lower() for p in paths}
    claimed: Dict[str, str] = {}

    for path in paths:
        name = path.name
        first_line = decode(split_terminator(read_first_lines(path, 1)[0])[0]) if path.stat().st_size else ""
        content_kind = "raw" if looks_like_raw(first_line) else "event" if looks_like_event(first_line) else "unknown"
        named_kind = "raw" if name.lower().endswith("_raw.txt") else "event" if name.lower().endswith("_event.txt") else None

        # A file whose contents contradict its name is the one case where a mechanical fix would
        # make things worse: renaming it tidies the folder while hiding a mix-up, and editing its
        # header edits the wrong schema.
        if content_kind != "unknown" and named_kind is not None and content_kind != named_kind:
            plan.manual.append(
                ManualIssue(
                    name,
                    f"named as a '{named_kind}' file but the contents are a '{content_kind}' file",
                    "the file has to be re-exported or renamed by hand; fixing the name would hide "
                    "the mix-up",
                )
            )
            continue

        if content_kind == "unknown":
            plan.manual.append(
                ManualIssue(
                    name,
                    "the first line matches neither a signal nor an event file header",
                    "the contents are not recognised, so only the filename was considered",
                )
            )

        if FIX_COLUMNS in fixes and content_kind == "raw":
            new_header, renames, manual = plan_raw_header(path)
            plan.manual.extend(manual)
            if new_header is not None:
                plan.header_rewrites[name] = new_header
                plan.changes.append(
                    Change(
                        fix=FIX_COLUMNS,
                        file_name=name,
                        rule="channel name",
                        detail="; ".join(renames),
                        previous_value=decode(split_terminator(read_first_lines(path, 2)[1])[0]),
                        new_value=new_header,
                    )
                )

        if FIX_MARKERS in fixes and content_kind == "event":
            if path.stat().st_size > MAX_PLAUSIBLE_EVENT_FILE_BYTES:
                plan.manual.append(
                    ManualIssue(
                        name,
                        f"event file is {path.stat().st_size / 1e6:.1f} MB",
                        "far larger than a marker list should be; not edited",
                    )
                )
            else:
                event_name = event_name_from_filename(name, expected_events)
                drop_lines, dropped, note, manual = plan_event_markers(
                    path,
                    signal_sibling(path),
                    (segment_durations or {}).get(event_name or ""),
                )
                plan.manual.extend(manual)
                if drop_lines:
                    plan.marker_rewrites[name] = drop_lines
                    plan.changes.append(
                        Change(
                            fix=FIX_MARKERS,
                            file_name=name,
                            rule=f"duplicate '{ONSET_MARKER}' marker",
                            detail="; ".join(dropped),
                            note=note,
                            previous_value=" | ".join(
                                decode(split_terminator(path.read_bytes().splitlines(keepends=True)[i])[0])
                                for i in drop_lines
                            ),
                            new_value="removed",
                        )
                    )

        if FIX_NAMES in fixes:
            new_name, rules, reason = plan_filename(name, expected_events, include_guessed_events)
            if reason:
                plan.manual.append(ManualIssue(name, reason, "the correct name cannot be derived"))
            elif new_name:
                conflict = _rename_conflict(name, new_name, existing, claimed)
                if conflict:
                    plan.manual.append(ManualIssue(name, f"cannot be renamed to `{new_name}`", conflict))
                else:
                    claimed[new_name.lower()] = name
                    plan.renames[name] = new_name
                    plan.changes.append(
                        Change(
                            fix=FIX_NAMES,
                            file_name=name,
                            rule=", ".join(rules),
                            detail=f"`{name}` -> `{new_name}`",
                            previous_value=name,
                            new_value=new_name,
                        )
                    )

    plan.changes.sort(key=Change.sort_key)
    plan.manual.sort(key=ManualIssue.sort_key)
    return plan


def _rename_conflict(
    name: str,
    new_name: str,
    existing: Sequence[str],
    claimed: Dict[str, str],
) -> Optional[str]:
    """Explain why a rename cannot go ahead, if it cannot.

    Comparison is case-insensitive because the exports are processed on Windows, where a file
    that differs only in case is the same file.
    """
    key = new_name.lower()
    if key in claimed:
        return f"`{claimed[key]}` is already being renamed to that name"
    # A rename that only changes case targets the file itself, which is fine.
    if key in set(existing) and key != name.lower():
        return "a different file of that name already exists"
    return None


# --------------------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------------------


def backup(path: Path, backup_dir: Optional[Path]) -> None:
    if backup_dir is None:
        return
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / path.name)


def rewrite_header(path: Path, new_header: str, backup_dir: Optional[Path]) -> None:
    """Replace the header line of a signal file, copying the rest of the file byte for byte."""
    backup(path, backup_dir)
    temp_path = path.with_name(path.name + ".fixtmp")
    with path.open("rb") as source, temp_path.open("wb") as target:
        sample_rate_line = source.readline()
        header_line = source.readline()
        _, terminator = split_terminator(header_line)
        target.write(sample_rate_line)
        target.write(new_header.encode("utf-8") + terminator)
        shutil.copyfileobj(source, target, COPY_CHUNK_BYTES)
    temp_path.replace(path)


def rewrite_markers(path: Path, drop_lines: Sequence[int], backup_dir: Optional[Path]) -> None:
    """Drop the given 0-based lines from an event file, leaving every other byte untouched."""
    backup(path, backup_dir)
    raw_lines = path.read_bytes().splitlines(keepends=True)
    drop = set(drop_lines)
    kept = [line for index, line in enumerate(raw_lines) if index not in drop]
    temp_path = path.with_name(path.name + ".fixtmp")
    temp_path.write_bytes(b"".join(kept))
    temp_path.replace(path)


def rename(path: Path, new_name: str) -> Path:
    """Rename a file, via a temporary name when only the capitalisation changes.

    On Windows the source and the target of a case-only rename are the same path, which some
    filesystems refuse to rename directly; going through a third name always works.
    """
    target = path.with_name(new_name)
    if path.name.lower() == new_name.lower():
        staging = path.with_name(path.name + ".fixtmp")
        path.rename(staging)
        staging.rename(target)
    else:
        path.rename(target)
    return target


def apply_plan(data_dir: Path, plan: Plan, backup_dir: Optional[Path]) -> None:
    """Apply the plan.

    Content is edited before any renaming, so that a file needing both fixes is still found
    under the name the plan was built from.
    """
    apply_order = (FIX_COLUMNS, FIX_MARKERS, FIX_NAMES)
    for change in sorted(plan.changes, key=lambda c: apply_order.index(c.fix)):
        path = data_dir / change.file_name
        try:
            if change.fix == FIX_COLUMNS:
                rewrite_header(path, plan.header_rewrites[change.file_name], backup_dir)
            elif change.fix == FIX_MARKERS:
                rewrite_markers(path, plan.marker_rewrites[change.file_name], backup_dir)
            elif change.fix == FIX_NAMES:
                rename(path, plan.renames[change.file_name])
            change.status = STATUS_APPLIED
        except Exception as exc:  # a single unwritable file must not abort the rest
            change.status = STATUS_FAILED
            change.error = str(exc)


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def build_report(
    data_dir: Path,
    plan: Plan,
    fixes: Sequence[str],
    applied: bool,
    backup_dir: Optional[Path],
    notes: Sequence[str],
) -> str:
    by_fix: Dict[str, List[Change]] = {fix: [] for fix in ALL_FIXES}
    for change in plan.changes:
        by_fix[change.fix].append(change)
    n_failed = sum(1 for change in plan.changes if change.status == STATUS_FAILED)

    lines: List[str] = [
        "# Raw Data Fixes Report",
        "",
        f"_Generated: {datetime.now():%Y-%m-%d %H:%M:%S}_",
        "",
        f"Folder: `{data_dir}`",
        "",
        (
            "**Mode: changes were applied.**"
            if applied
            else "**Mode: dry run - nothing was written. Re-run with `--apply` to make these changes.**"
        ),
        "",
        f"Fixes enabled: {', '.join(f'`{fix}`' for fix in fixes)}.",
        "",
    ]
    if backup_dir is not None:
        lines += [f"Originals of every file whose contents changed were copied to `{backup_dir}`.", ""]

    lines += [
        "## Summary",
        "",
        f"- Files renamed: **{len(by_fix[FIX_NAMES])}**",
        f"- Signal files with renamed channels: **{len(by_fix[FIX_COLUMNS])}**",
        f"- Event files with duplicate `{ONSET_MARKER}` markers resolved: **{len(by_fix[FIX_MARKERS])}**",
        f"- Problems left for manual attention: **{len(plan.manual)}**",
    ]
    if n_failed:
        lines.append(f"- **Failed: {n_failed}** (see the status column below)")
    lines += [""]

    if notes:
        lines += ["> " + note for note in notes] + [""]

    lines += ["## Changes", ""]
    if not plan.changes:
        lines += ["Nothing to fix.", ""]

    for fix, heading, columns, row_of in (
        (
            FIX_NAMES,
            "Filenames",
            ["Current name", "New name", "Reason", "Status"],
            lambda c: [f"`{c.previous_value}`", f"`{c.new_value}`", c.rule, _status(c)],
        ),
        (
            FIX_COLUMNS,
            "Channel names",
            ["File", "Renamed channels", "Status"],
            lambda c: [f"`{c.file_name}`", escape_cell(c.detail), _status(c)],
        ),
        (
            FIX_MARKERS,
            f"Duplicate '{ONSET_MARKER}' markers",
            ["File", "Markers", "Recording after the kept marker", "Status"],
            lambda c: [f"`{c.file_name}`", escape_cell(c.detail), c.note or "-", _status(c)],
        ),
    ):
        group = by_fix[fix]
        if not group:
            continue
        lines += [f"### {heading} ({len(group)})", ""]
        if fix == FIX_MARKERS:
            lines += [
                f"The notebook uses the first `{ONSET_MARKER}` marker it finds, so all but one "
                f"marker is removed. The later marker is normally the real onset, so the last one "
                f"is kept unless the recording after it is too short for the event's analysis "
                f"window - a marker that late is an `End` pressed with the wrong key rather than a "
                f"second onset. The last column shows how much recording follows the marker that "
                f"was kept, so the choice can be checked against the recording notes.",
                "",
            ]
        lines += [markdown_table(columns, [row_of(change) for change in group], "None."), ""]

    lines += [
        "## Needs manual attention",
        "",
        "These findings are deliberately not fixed automatically, because the correct outcome "
        "depends on information that is not in the file.",
        "",
        markdown_table(
            ["File", "Problem", "Why it is not fixed here"],
            [
                [f"`{issue.file_name}`", escape_cell(issue.problem), escape_cell(issue.reason)]
                for issue in plan.manual
            ],
            "Nothing outstanding.",
        ),
        "",
        "Re-run `python scripts/check_raw_data_consistency.py` afterwards to confirm what is left.",
        "",
    ]
    return "\n".join(lines)


def _status(change: Change) -> str:
    if change.status == STATUS_FAILED:
        return f"**failed**: {escape_cell(change.error)}"
    return change.status


def escape_cell(text: str) -> str:
    """Keep a value containing a pipe (a channel name, a filename pattern) inside its table cell."""
    return text.replace("|", "\\|")


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(
        description="Apply the mechanical fixes reported by check_raw_data_consistency.py.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=repo_root / "data" / "BioLab",
        help="folder holding the raw and event files (default: data/BioLab)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually modify the folder; without this flag the script only reports what it would do",
    )
    parser.add_argument(
        "--fix",
        action="append",
        choices=ALL_FIXES,
        help=f"limit the fixes to apply; repeatable (default: all of {', '.join(ALL_FIXES)})",
    )
    parser.add_argument(
        "--include-guessed-events",
        action="store_true",
        help=(
            "also rename files whose event name only resembles an expected one (e.g. 'DCPP' -> "
            "'DCP'); check the contents of those files first"
        ),
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="copy every file whose contents are modified into this folder before changing it",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=repo_root / "reports" / "raw_data_fixes_report.md",
        help="where to write the Markdown report (a .csv of all changes is written alongside it)",
    )
    args = parser.parse_args(argv)

    data_dir: Path = args.data_dir if args.data_dir.is_absolute() else repo_root / args.data_dir
    if not data_dir.is_dir():
        print(f"Not a folder: {data_dir}")
        return 2

    fixes = tuple(dict.fromkeys(args.fix)) if args.fix else ALL_FIXES
    backup_dir: Optional[Path] = None
    if args.backup_dir is not None:
        backup_dir = args.backup_dir if args.backup_dir.is_absolute() else repo_root / args.backup_dir

    expected_events, _sampling_frequency, notes = load_pipeline_expectations(repo_root)
    segment_durations = load_segment_durations(repo_root)

    print(f"Planning fixes for {data_dir}")
    plan = build_plan(
        data_dir, expected_events, fixes, args.include_guessed_events, segment_durations
    )
    print(
        f"Planned: {len(plan.renames)} rename(s), {len(plan.header_rewrites)} header rewrite(s), "
        f"{len(plan.marker_rewrites)} marker fix(es); {len(plan.manual)} issue(s) left for manual attention."
    )

    if args.apply and plan.changes:
        print("Applying...")
        apply_plan(data_dir, plan, backup_dir)
    elif not args.apply:
        notes = list(notes) + ["Dry run: re-run with `--apply` to write these changes."]

    report_path: Path = args.report_path if args.report_path.is_absolute() else repo_root / args.report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        build_report(data_dir, plan, fixes, args.apply, backup_dir, notes), encoding="utf-8"
    )

    changes_csv_path = report_path.with_suffix(".csv")
    with changes_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(Change(fix="", file_name="", rule="", detail="")).keys()))
        writer.writeheader()
        for change in plan.changes:
            writer.writerow(asdict(change))

    n_applied = sum(1 for change in plan.changes if change.status == STATUS_APPLIED)
    n_failed = sum(1 for change in plan.changes if change.status == STATUS_FAILED)
    print(f"\n{n_applied} change(s) applied, {n_failed} failed.")
    print(f"Report written to {report_path}")
    print(f"Changes written to {changes_csv_path}")
    return 1 if n_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

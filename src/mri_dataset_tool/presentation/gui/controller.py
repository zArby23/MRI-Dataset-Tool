"""Wizard state, validation and navigation, without Tk (tested without a display).

The views only draw and delegate here. Each step is unlocked when the previous one was validated
(``complete``); the mapping step applies only to DICOM and loose NIfTI inputs. Validation uses the
same ``application`` functions as ``mri-dataset dataset build``, before anything is created. The state
holds only what the user chose (paths, format, options), never ids, paths or values read from the data.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mri_dataset_tool.application.pipeline.runner import Pipeline
from mri_dataset_tool.application.services.dataset_build import (
    InvalidBuildInput,
    build_dataset,
    check_build_args,
    load_build_pipeline,
)
from mri_dataset_tool.application.services.dataset_ingest import MappingRow, load_mapping, plan_ingest
from mri_dataset_tool.application.services.disk_space import check_free_space, estimate_input_bytes
from mri_dataset_tool.application.services import labels as label_service
from mri_dataset_tool.application.services.dataset import write_ml_exports
from mri_dataset_tool.application.services.dataset_build import is_new_or_empty_dir
from mri_dataset_tool.application.services.dataset_outputs import ml_exports_exist, write_report
from mri_dataset_tool.application.services.ingest_preview import PreviewRow, apply_edit, preview_ingest, write_mapping
from mri_dataset_tool.application.services.labels_table import (
    LabelRow,
    apply_label_edits,
    read_label_corrections,
    read_label_sheet,
)
from mri_dataset_tool.application.services.inputs import (
    DEFAULT_RATIOS,
    DEFAULT_SEED,
    check_input_paths,
    check_split_params,
    is_valid_folder_name,
    new_folders_valid,
    project_config_dir,
    with_memory_consent,
)
from mri_dataset_tool.presentation.gui import messages
from mri_dataset_tool.presentation.gui.worker import Done, Event, Failed, Reporter, Status, Worker, failure

STEPS = ("input", "config", "mapping", "run", "labels", "export")
FORMATS = ("bids", "dicom", "nifti")
PRESET_NAME = "stage3_bids.yaml"  # in the project's config/ (design decision), not the working directory


@dataclass
class WizardState:
    key_defined: bool = True  # False: the key was generated for this session
    input_dir: Path | None = None
    input_format: str = "bids"
    output_dir: Path | None = None
    config_path: Path = field(default_factory=lambda: project_config_dir() / PRESET_NAME)
    allow_insufficient_memory: bool = False
    classes: dict[str, str] | None = None  # None = no labels
    ratios: tuple[float, ...] = DEFAULT_RATIOS
    seed: int = DEFAULT_SEED
    config: dict[str, Any] | None = None
    pipeline: Pipeline | None = None
    # Step 3 (DICOM / loose NIfTI). Rows hold paths relative to the input: only in memory, out of repr.
    preview: list[PreviewRow] = field(default_factory=list, repr=False)
    mapping: list[MappingRow] = field(default_factory=list, repr=False)
    # Step 4.
    dataset_root: Path | None = None  # <output>/dataset once the run succeeded
    # Step 5. Dataset ids are pseudonyms; still kept out of repr (shown only in the table).
    label_rows: list[LabelRow] = field(default_factory=list, repr=False)
    label_edits: dict[tuple[str, str | None], str] = field(default_factory=dict, repr=False)
    label_classes: list[str] = field(default_factory=list)
    labels_closed: bool = False
    labels_available: bool = False  # False: no classes were given (no label files)
    label_counts: dict[str, int] = field(default_factory=dict)  # pairs, labeled, foreign, invalid
    label_filter: str = "all"  # all | unlabeled | defect
    label_version: int = 0  # bumped on every change of the rows, edits or filter: the table redraws only then
    # Step 6: what this session wrote (file names are fixed by the tool, never read from the data).
    ml_dirs: list[Path] = field(default_factory=list)  # where this session wrote ML exports (dataset or ml_exports_N)
    report_dirs: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class Check:
    """A validation result: ``code`` ``None`` = valid; else a ``messages`` code and its values."""

    code: str | None = None
    values: dict[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code is None


def _check(validate: Callable[[], object]) -> tuple[Check, object]:
    """Run a service validation; its exceptions become codes (never their messages)."""
    try:
        return Check(), validate()
    except InvalidBuildInput as error:
        code, values = messages.invalid_input(error)
        return Check(code, values), None
    except FileExistsError:
        return Check("OUTPUT_EXISTS"), None


class Controller:
    def __init__(self, worker: Worker | None = None, language: str = messages.DEFAULT_LANGUAGE) -> None:
        self.worker = worker or Worker()
        self.state = WizardState()
        self.language = language
        self.step = STEPS[0]
        self._complete: set[str] = set()
        self._new_preview: list[PreviewRow] = []  # set by the preview task (worker thread), read on its Done
        self._new_sheet = None  # set by a labels task, read on its Done
        self._new_corrections: dict = {}  # set by a corrections task, read on its Done
        self._export_kind = ""  # "ml" or "report": which exports task runs
        self._new_ml: tuple[Path, list[str]] | None = None
        self._new_report: tuple[Path, list[str], dict[str, int]] | None = None

    # --- texts ------------------------------------------------------------------------------------

    def set_language(self, language: str) -> None:
        if language not in messages.LANGUAGES:
            raise ValueError("Unsupported language.")
        self.language = language

    def text(self, code: str, **values: object) -> str:
        return messages.text(code, self.language, **values)

    def check_text(self, check: Check, ok_code: str) -> str:
        return self.text(ok_code) if check.ok else self.text(check.code, **check.values)

    def failure_text(self, event: Failed) -> str:
        return self.text(event.code, **{"error_type": event.error_type, "stage": event.stage, **event.values})

    def step_header(self) -> str:
        steps = self.steps()
        return self.text("STEP_HEADER", number=steps.index(self.step) + 1, total=len(steps),
                         title=self.text(f"STEP_{self.step}"))

    def key_text(self) -> str:
        return self.text("KEY_DEFINED" if self.state.key_defined else "KEY_GENERATED")

    # --- step 1: input ----------------------------------------------------------------------------

    def set_input(self, input_dir: str, input_format: str, output_dir: str, new_folder: str = "") -> Check:
        """Validate the input folder, its format and the output (as the CLI): a new or empty folder outside
        the input. A folder with content is never used: ``OUTPUT_NOT_EMPTY`` asks for *new_folder*, a new
        folder created inside it."""
        self.reopen("input")
        if not input_dir.strip():
            return Check("INPUT_REQUIRED")
        if not output_dir.strip():
            return Check("OUTPUT_REQUIRED")
        if input_format not in FORMATS:
            return Check("INVALID_FORMAT")
        source, output = Path(input_dir), Path(output_dir)  # not stripped: the same paths the CLI would get
        if new_folder:
            if not is_valid_folder_name(new_folder):
                return Check("INVALID_FOLDER_NAME")
            output = output / new_folder
            if output.exists():
                return Check("FOLDER_NAME_EXISTS")
        if not new_folders_valid(output):
            return Check("INVALID_OUTPUT_PATH")
        check, _ = _check(lambda: check_input_paths(source, output))
        if check.code == "OUTPUT_EXISTS" and not new_folder:
            return Check("OUTPUT_NOT_EMPTY")
        if check.ok:
            if (source, input_format) != (self.state.input_dir, self.state.input_format):
                self.state.preview, self.state.mapping = [], []  # they belong to the previous input
            self.state.input_dir, self.state.input_format, self.state.output_dir = source, input_format, output
            self.complete("input")
        return check

    def start_task(
        self, task: Callable[[Reporter], dict[str, int] | None], classify: Callable[[Exception], Failed] = failure
    ) -> bool:
        """Start *task* in the worker; ``False`` (nothing started) while another task runs."""
        if self.worker.busy:
            return False
        self.worker.start(task, classify)
        return True

    def disk_space_task(self) -> Callable[[Reporter], dict[str, int]]:
        """A worker task: estimated output (input size) against the free space of the output drive."""
        source, output = self.state.input_dir, self.state.output_dir

        def task(reporter: Reporter) -> dict[str, int]:
            check = check_free_space(output, estimate_input_bytes(source))
            return {"required": check.required, "free": -1 if check.free is None else check.free,
                    "insufficient": int(check.insufficient)}

        return task

    def disk_space_text(self, summary: dict[str, int]) -> str:
        if not summary.get("insufficient"):
            return self.text("DISK_SPACE_OK")
        return self.text("LOW_DISK_SPACE", required=f"{summary['required'] / 2**30:.1f}",
                         free=f"{summary['free'] / 2**30:.1f}")

    # --- step 2: configuration --------------------------------------------------------------------

    def set_config(
        self,
        config_path: str,
        allow_insufficient_memory: bool,
        classes_text: str,
        ratios: Sequence[str] = tuple(str(r) for r in DEFAULT_RATIOS),
        seed: str = str(DEFAULT_SEED),
    ) -> Check:
        """Validate the run config (with ``anonymize``) and the classes (as the CLI). The window does not ask for
        ratios and seed: the build writes the ML exports with the standard ones (70/15/15, seed 0; other values
        are regenerated in step 6). Tests may still pass them."""
        self.reopen("config")
        if "input" not in self._complete:
            return Check("INPUT_REQUIRED")
        try:
            ratio_values = [float(value) for value in ratios]
        except ValueError:
            return Check("INVALID_RATIOS")
        try:
            seed_value = int(seed.strip())
        except ValueError:
            return Check("INVALID_SEED")
        class_items = [line.strip() for line in classes_text.splitlines() if line.strip()]
        path = Path(config_path)
        check, classes = _check(lambda: check_build_args(
            self.state.input_dir, self.state.output_dir, path, class_items or None, None, ratio_values, seed_value
        ))
        if not check.ok:
            return check
        check, loaded = _check(lambda: load_build_pipeline(path, project_config_dir()))
        if not check.ok:
            return check
        config, pipeline = with_memory_consent(loaded[0]) if allow_insufficient_memory else loaded
        self.state.config_path, self.state.allow_insufficient_memory = path, allow_insufficient_memory
        self.state.classes, self.state.ratios, self.state.seed = classes, tuple(ratio_values), seed_value
        self.state.config, self.state.pipeline = config, pipeline
        self.complete("config")
        return check

    def pipeline_summary(self) -> list[str]:
        """One line per pipeline step: its name and parameters (from the user's config file)."""
        if self.state.pipeline is None:
            return []
        return [f"{step.name} {json.dumps(step.params, sort_keys=True)}" for step in self.state.pipeline.steps]

    # --- step 3: mapping (DICOM / loose NIfTI) -----------------------------------------------------

    def preview_task(self) -> Callable[[Reporter], dict[str, int]]:
        """A worker task: the ingest decisions with the current mapping (headers only). Its rows are kept
        for ``preview_finished``; the event carries only counts."""
        self.reopen("mapping")
        state = self.state
        fmt, root, mapping, classes = state.input_format, state.input_dir, list(state.mapping), state.classes

        def task(reporter: Reporter) -> dict[str, int]:
            rows = preview_ingest(fmt, root, mapping, classes, reporter.on_skipped)
            self._new_preview = rows
            return {"series": len(rows), "skipped": sum(row.suffix is None for row in rows)}

        return task

    def preview_finished(self) -> None:
        """Main thread, on the ``Done`` of ``preview_task``: show its rows; the step is valid."""
        self.state.preview, self._new_preview = self._new_preview, []
        self.complete("mapping")

    def edit_mapping(self, index: int, column: str, value: str) -> Check:
        """Edit a cell of the preview table; valid edits are kept as mapping rows until the next preview."""
        check, mapping = _check(lambda: apply_edit(
            self.state.mapping, self.state.preview, self.state.input_format, index, column, value, self.state.classes
        ))
        if check.ok:
            self.state.mapping = mapping
            self.reopen("mapping")
        return check

    def assign_mapping_label(self, indices: Sequence[int], value: str) -> Check:
        """The same label for the studies of every selected row (``""`` clears it); all or nothing."""
        if not indices:
            return Check("NOTHING_SELECTED")
        mapping = list(self.state.mapping)
        for index in indices:
            check, mapping = _check(lambda: apply_edit(
                mapping, self.state.preview, self.state.input_format, index, "label", value, self.state.classes
            ))
            if not check.ok:
                return check
        self.state.mapping = mapping
        self.reopen("mapping")
        return Check(values={"count": len(indices)})

    def load_mapping_file(self, path: str) -> Check:
        check, mapping = _check(lambda: load_mapping(Path(path), self.state.input_dir, self.state.classes))
        if check.ok:
            self.state.mapping = mapping
            self.reopen("mapping")
        return check

    def save_mapping_file(self, path: str) -> Check:
        try:
            write_mapping(self.state.mapping, Path(path), self.state.input_dir, self.state.classes)
        except FileExistsError:
            return Check("MAPPING_FILE_EXISTS")
        except OSError:  # a folder, a missing parent, a read-only drive
            return Check("MAPPING_FILE_UNWRITABLE")
        except InvalidBuildInput as error:
            code, values = messages.invalid_input(error)
            return Check(code, values)
        return Check()

    # --- step 4: run ------------------------------------------------------------------------------

    def run_task(self) -> Callable[[Reporter], dict[str, int]]:
        """A worker task: ``build_dataset`` as ``mri-dataset dataset build`` (output checked again, DICOM and
        loose NIfTI planned with the mapping of step 3). Events carry only stage names, counts and types."""
        self.reopen("run")
        state = self.state
        # Taken now, not in the thread: the window may change the state while the task runs.
        source, output, fmt, mapping = state.input_dir, state.output_dir, state.input_format, list(state.mapping)
        pipeline, config, classes, ratios, seed = state.pipeline, state.config, state.classes, state.ratios, state.seed

        def task(reporter: Reporter) -> dict[str, int]:
            check_input_paths(source, output)  # the output may have changed since step 1
            ingest = None if fmt == "bids" else plan_ingest(fmt, source, mapping=mapping, on_skipped=reporter.on_skipped)
            result = build_dataset(
                source, output, pipeline, config, classes=classes, ratios=ratios,
                seed=seed, on_skipped=reporter.on_skipped, on_error=reporter.on_error,
                on_report_error=reporter.on_report_error, on_status=reporter.on_status, ingest=ingest,
            )
            exported = result.exported
            return {"studies": exported.studies_written, "series": exported.series_written,
                    "participants": exported.participants, "errors": exported.errors,
                    "report_files": len(result.report_files)}

        return task

    def run_finished(self) -> None:
        """Main thread, on the ``Done`` of ``run_task``: the dataset exists; the labels step opens."""
        self.state.dataset_root = self.state.output_dir / "dataset"
        self.complete("run")

    def status_lines(self, event: Status) -> list[str]:
        """The texts of a ``build_dataset`` status event, with the fixed warnings of the CLI."""
        counts = event.counts
        if event.stage == "ingested":
            unmapped = {code: n for code, n in counts.items()
                        if code not in ("MAPPING_UNUSED", "NOT_4D_DWI", "MISSING_PATIENT_ID") and n}
            lines = [self.text("WARN_UNMAPPED_SERIES", codes=self.counts_text(unmapped))] if unmapped else []
            for code in ("NOT_4D_DWI", "MAPPING_UNUSED", "MISSING_PATIENT_ID"):
                if counts.get(code):
                    lines.append(self.text(f"WARN_{code}", count=counts[code]))
            return lines
        if event.stage == "labels_incomplete":
            return [self.text("WARN_LABELS_INCOMPLETE", codes=self.counts_text(counts))]
        code = f"EV_{event.stage}"
        return [self.text(code, **counts)] if code in messages.CATALOG[self.language] else []

    def counts_text(self, counts: dict[str, int]) -> str:
        """``CODE n, CODE n`` (codes or exception type names and counts only), or "none"."""
        return ", ".join(f"{name} {n}" for name, n in sorted(counts.items())) or self.text("NONE")

    # --- step 5: labels ---------------------------------------------------------------------------

    def _labels(self, call: Callable[[], object]) -> tuple[Check, object]:
        try:
            return Check(), call()
        except (ValueError, OSError) as error:  # fixed texts of the label services
            code, values = messages.label_error(error)
            return Check(code, values), None

    def labels_task(self, action: str) -> tuple[Check, Callable[[Reporter], dict[str, int]] | None]:
        """The worker task of a labels *action* (load | apply | finalize | reopen): the service call, then
        the table read again. Thousands of pairs take seconds (the dataset tree is walked), so the view runs
        it in the worker; ``labels_finished`` shows the result. A finalize with pending edits is refused."""
        if action == "finalize" and self.state.label_edits:
            return Check("LABELS_EDITS_PENDING"), None
        root, edits = self.state.dataset_root, dict(self.state.label_edits)
        calls = {
            "load": lambda: 0,
            "apply": lambda: apply_label_edits(root, edits),
            "finalize": lambda: label_service.finalize_labels(root) and 0,
            "reopen": lambda: label_service.reopen_labels(root) or 0,
        }

        def task(reporter: Reporter | None) -> dict[str, int]:
            count = calls[action]()
            try:
                self._new_sheet = read_label_sheet(root)
            except FileNotFoundError as error:
                if messages.label_error(error)[0] != "NO_LABELS":
                    raise
                self._new_sheet = None  # no classes were given: no label files
            return {"count": count}

        return Check(), task

    @staticmethod
    def labels_failure(error: Exception) -> Failed:
        code, values = messages.label_error(error)
        return Failed(code, type(error).__name__, values=values)

    def labels_finished(self, event: Done) -> Check:
        """Main thread, on the ``Done`` of ``labels_task``: show the table read again (pending edits are
        dropped: applied or reloaded). The step is valid once the labels are finalized, or without labels."""
        state, sheet = self.state, self._new_sheet
        state.label_edits = {}
        state.label_version += 1
        if sheet is None:
            state.labels_available, state.label_rows, state.label_classes = False, [], []
            self.complete("labels")
            return Check("NO_LABELS")
        review = sheet.review
        state.labels_available, state.label_rows, state.label_classes = True, sheet.rows, sheet.classes
        state.labels_closed = sheet.finalized
        state.label_counts = {"pairs": review.dataset_pairs, "labeled": review.labeled,
                              "foreign": review.not_in_dataset, "invalid": review.invalid_ids}
        if state.labels_closed:
            self.complete("labels")
        else:
            self.reopen("labels")
        return Check(values=event.summary)

    def _labels_now(self, action: str) -> Check:
        """``labels_task`` run in the calling thread (tests and scripts; the view uses the worker)."""
        check, task = self.labels_task(action)
        if not check.ok:
            return check
        try:
            summary = task(None)
        except Exception as error:
            failed = self.labels_failure(error)
            return Check(failed.code, failed.values)
        return self.labels_finished(Done(summary))

    def load_labels(self) -> Check:
        return self._labels_now("load")

    def edit_label(self, index: int, value: str) -> Check:
        """Keep an edit of the class of row *index* (``""`` = unlabeled) until ``apply_labels``."""
        return self.assign_labels([index], value)

    def assign_labels(self, indices: Sequence[int], value: str) -> Check:
        """The same class (``""`` = unlabeled) for every row in *indices*, kept until ``apply_labels``."""
        if self.worker.busy:  # a labels task is reading or writing the table
            return Check("TASK_RUNNING")
        if self.state.labels_closed:
            return Check("LABELS_FINALIZED")
        if not indices:
            return Check("NOTHING_SELECTED")
        if value and value not in self.state.label_classes:
            return Check("LABEL_UNKNOWN_CLASS")
        for index in indices:
            row = self.state.label_rows[index]
            self.state.label_edits[(row.participant, row.session)] = value
        self.state.label_version += 1
        return Check(values={"count": len(indices)})

    def effective_label(self, index: int) -> tuple[str, str | None]:
        """The class shown for row *index* (its pending edit, if any) and its defect (none once edited
        to a class; ``UNLABELED`` once edited to empty)."""
        row = self.state.label_rows[index]
        edited = self.state.label_edits.get((row.participant, row.session))
        if edited is None:
            return row.label or "", row.defect
        return edited, None if edited else "UNLABELED"

    def unlabeled_rows(self) -> list[int]:
        return [i for i in range(len(self.state.label_rows)) if not self.effective_label(i)[0]]

    def visible_label_rows(self) -> list[int]:
        """The rows the table shows under the current filter."""
        rows = range(len(self.state.label_rows))
        if self.state.label_filter == "unlabeled":
            return self.unlabeled_rows()
        if self.state.label_filter == "defect":
            return [i for i in rows if self.effective_label(i)[1] is not None]
        return list(rows)

    def set_label_filter(self, name: str) -> None:
        if name not in ("all", "unlabeled", "defect"):
            raise ValueError("Unsupported label filter.")
        self.state.label_filter = name
        self.state.label_version += 1

    def corrections_task(self, path: str) -> tuple[Check, Callable[[Reporter], dict[str, int]] | None]:
        """The worker task reading a ``--corrections`` TSV chosen by the user as pending edits (validated;
        applied by «Apply»). It walks the dataset tree (seconds with thousands of pairs)."""
        if self.worker.busy:
            return Check("TASK_RUNNING"), None
        if self.state.labels_closed:
            return Check("LABELS_FINALIZED"), None
        root = self.state.dataset_root

        def task(reporter: Reporter | None) -> dict[str, int]:
            self._new_corrections = read_label_corrections(root, Path(path))
            return {"count": len(self._new_corrections)}

        return Check(), task

    def corrections_finished(self, event: Done) -> Check:
        """Main thread, on the ``Done`` of ``corrections_task``: the corrections join the pending edits."""
        self.state.label_edits.update(self._new_corrections)
        self.state.label_version += 1
        return Check(values=event.summary)

    def load_label_corrections(self, path: str) -> Check:
        """``corrections_task`` run in the calling thread (tests and scripts; the view uses the worker)."""
        check, task = self.corrections_task(path)
        if not check.ok:
            return check
        try:
            summary = task(None)
        except Exception as error:
            failed = self.labels_failure(error)
            return Check(failed.code, failed.values)
        return self.corrections_finished(Done(summary))

    def apply_labels(self) -> Check:
        """Apply the pending edits (all or nothing, logged); ``values["count"]`` = changes."""
        return self._labels_now("apply")

    def finalize_labels(self) -> Check:
        return self._labels_now("finalize")

    def reopen_labels(self) -> Check:
        return self._labels_now("reopen")

    def labels_status_lines(self) -> list[str]:
        state = self.state
        if not state.labels_available:
            return []
        counts = state.label_counts
        lines = [self.text("LABELS_CLOSED" if state.labels_closed else "LABELS_OPEN", **counts)]
        if counts.get("foreign") or counts.get("invalid"):
            lines.append(self.text("LABELS_FOREIGN", **counts))
        if state.label_edits:
            lines.append(self.text("LABELS_PENDING", count=len(state.label_edits)))
        return lines

    # --- step 6: exports and report --------------------------------------------------------------

    def ml_exports_present(self) -> bool:
        return self.state.dataset_root is not None and ml_exports_exist(self.state.dataset_root)

    def next_ml_exports_dir(self) -> Path:
        """The next free (new or empty) ``<output>/ml_exports_N`` for a regenerated set, from 2 (the set in the
        dataset is the first)."""
        output = self.state.output_dir
        return next(output / f"ml_exports_{n}" for n in range(2, 10_000) if is_new_or_empty_dir(output / f"ml_exports_{n}"))

    def default_report_dir(self) -> Path:
        """``<output>/report`` while it is new or empty (build_dataset fills it), else ``report_2``, ``_3``..."""
        output = self.state.output_dir
        names = ("report", *(f"report_{n}" for n in range(2, 1000)))
        return next((output / name for name in names if is_new_or_empty_dir(output / name)), output / "report")

    def ml_exports_task(
        self, ratios: Sequence[str], seed: str
    ) -> tuple[Check, Callable[[Reporter], dict[str, int]] | None]:
        """Validate the split parameters (as ``dataset export-ml``) and return the task writing the ML exports:
        into the dataset if it has none yet (as ``dataset export-ml``), else a regenerated set into the next free
        ``<output>/ml_exports_N``; nothing is ever overwritten. The labels must be finalized: unlike the
        CLI (``--allow-unfinalized``), the GUI never exports open labels (design decision)."""
        try:
            ratio_values = [float(value) for value in ratios]
        except ValueError:
            return Check("INVALID_RATIOS"), None
        try:
            seed_value = int(seed.strip())
        except ValueError:
            return Check("INVALID_SEED"), None
        try:
            check_split_params(ratio_values, seed_value)
        except ValueError:
            return Check("INVALID_RATIOS"), None
        root = self.state.dataset_root
        folder = self.next_ml_exports_dir() if self.ml_exports_present() else None  # None = the dataset root

        def task(reporter: Reporter) -> dict[str, int]:
            self._export_kind = "ml"  # set by the task that started, read on its Done
            written = write_ml_exports(root, ratio_values, seed_value, output_dir=folder)
            self._new_ml = (folder or root, [path.name for path in written])
            return {"files": len(written)}

        return Check(), task

    def report_task(self, report_dir: str) -> tuple[Check, Callable[[Reporter], dict[str, int]] | None]:
        """The task writing the four report files into a new or empty folder outside the dataset."""
        if not report_dir.strip():
            return Check("REPORT_DIR_REQUIRED"), None
        folder, root = Path(report_dir), self.state.dataset_root
        if not is_new_or_empty_dir(folder):
            return Check("REPORT_DIR_NOT_EMPTY"), None
        if folder.resolve().is_relative_to(root.resolve()):
            return Check("REPORT_INSIDE_DATASET"), None

        def task(reporter: Reporter) -> dict[str, int]:
            self._export_kind = "report"
            names, warnings = write_report(root, folder, reporter.on_report_error)
            self._new_report = (folder, names, warnings)
            return {"files": len(names)}

        return Check(), task

    @staticmethod
    def export_failure(error: Exception) -> Failed:
        """The ``Failed`` of an exports task: its fixed message looked up (``FileExistsError`` here means
        an export or report file, not the build output)."""
        code, values = messages.export_error(error)
        return Failed(code, type(error).__name__, values=values)

    def export_finished(self, event: Done) -> list[tuple[str, dict]]:
        """Main thread, on the ``Done`` of an exports task: the lines to show (codes and values)."""
        if self._export_kind == "ml":
            folder, names = self._new_ml
            self.state.ml_dirs.append(folder)
            return [("ML_WRITTEN_IN", {"folder": folder.name, **event.summary}),
                    *(("FILE_NAME", {"name": name}) for name in names)]
        folder, names, warnings = self._new_report
        self.state.report_dirs.append(folder)
        lines = [("REPORT_WRITTEN", event.summary), *(("FILE_NAME", {"name": name}) for name in names)]
        for code, count in sorted(warnings.items()):
            specific = f"REPORT_WARNING_{code}"
            lines.append((specific, {"count": count}) if specific in messages.CATALOG[self.language]
                         else ("REPORT_WARNING", {"code": code, "count": count}))
        return lines

    def export_status_lines(self) -> list[str]:
        if self.state.dataset_root is None:
            return []
        return [self.text("ML_PRESENT" if self.ml_exports_present() else "ML_ABSENT")]

    # --- navigation -------------------------------------------------------------------------------

    def steps(self) -> list[str]:
        """The steps of the current input format, in order."""
        return [step for step in STEPS if step != "mapping" or self.state.input_format != "bids"]

    def complete(self, step: str) -> None:
        """Mark *step* as validated: the next one is unlocked."""
        self._complete.add(step)

    def reopen(self, step: str) -> None:
        """A change in *step* invalidates it and every later step."""
        self._complete -= set(STEPS[STEPS.index(step):])
        if STEPS.index(step) <= STEPS.index("run"):
            self.state.dataset_root = None  # a change before the run needs a new run

    def can_go_next(self) -> bool:
        steps = self.steps()
        return self.step in self._complete and self.step != steps[-1] and not self.worker.busy

    def can_go_back(self) -> bool:
        return self.step != self.steps()[0] and not self.worker.busy

    def go_next(self) -> str:
        if self.can_go_next():
            steps = self.steps()
            self.step = steps[steps.index(self.step) + 1]
        return self.step

    def go_back(self) -> str:
        if self.can_go_back():
            steps = self.steps()
            self.step = steps[steps.index(self.step) - 1]
        return self.step

    # --- events and closing -----------------------------------------------------------------------

    def poll(self) -> list[Event]:
        """The worker events published since the last call (never blocks; main thread only)."""
        return self.worker.drain()

    def close_warning(self) -> str | None:
        """The text to confirm before closing while a task runs; ``None`` = close right away."""
        return self.text("CLOSE_WHILE_RUNNING") if self.worker.busy else None

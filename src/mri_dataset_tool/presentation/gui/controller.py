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
    check_build_args,
    load_build_pipeline,
)
from mri_dataset_tool.application.services.disk_space import check_free_space, estimate_input_bytes
from mri_dataset_tool.application.services.inputs import (
    DEFAULT_RATIOS,
    DEFAULT_SEED,
    check_input_paths,
    is_valid_folder_name,
    project_config_dir,
    with_memory_consent,
)
from mri_dataset_tool.presentation.gui import messages
from mri_dataset_tool.presentation.gui.worker import Event, Reporter, Worker

STEPS = ("input", "config", "mapping", "run", "labels", "export")
FORMATS = ("bids", "dicom", "nifti")
PRESET_NAME = "stage3_bids.yaml"  # in the project's config/ (decision of the human), not the working directory


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

    # --- texts ------------------------------------------------------------------------------------

    def set_language(self, language: str) -> None:
        if language not in messages.LANGUAGES:
            raise ValueError("Unsupported language.")
        self.language = language

    def text(self, code: str, **values: object) -> str:
        return messages.text(code, self.language, **values)

    def check_text(self, check: Check, ok_code: str) -> str:
        return self.text(ok_code) if check.ok else self.text(check.code, **check.values)

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
        check, _ = _check(lambda: check_input_paths(source, output))
        if check.code == "OUTPUT_EXISTS" and not new_folder:
            return Check("OUTPUT_NOT_EMPTY")
        if check.ok:
            self.state.input_dir, self.state.input_format, self.state.output_dir = source, input_format, output
            self.complete("input")
        return check

    def start_task(self, task: Callable[[Reporter], dict[str, int] | None]) -> bool:
        """Start *task* in the worker; ``False`` (nothing started) while another task runs."""
        if self.worker.busy:
            return False
        self.worker.start(task)
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
        self, config_path: str, allow_insufficient_memory: bool, classes_text: str, ratios: Sequence[str], seed: str
    ) -> Check:
        """Validate the run config (with ``anonymize``), the classes, ratios and seed (as the CLI)."""
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

"""Integration: the whole flow through the CLI over a synthetic BIDS batch with planted PHI.

``process`` → ``dataset build`` (labels in one go, and labels step by step) → ``dataset export-ml`` →
``dataset report``; exit codes per stage, PHI sweep over console, DEBUG logs, ``--json``, output tree and
manifests, ``python -m`` and ``mri-dataset`` executables, no overwrite, and CLI = services.
"""

import contextlib
import io
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config
from mri_dataset_tool.application.services.dataset import write_ml_exports
from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.application.services.labels import apply_label_corrections, finalize_labels, write_label_template
from mri_dataset_tool.application.services.pipeline_run import run_pipeline
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main
from test_stage4_dataset_integration import KEY, PLANTED, _config, _contents, _corrections, _export, _input

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config" / "stage3_bids.yaml"
CLASSES = ["AD=Alzheimer", "CN=Control"]


class _Transcript:
    """Runs ``main`` in-process with ``--verbose`` and keeps every stdout, stderr and DEBUG log line."""

    def __init__(self) -> None:
        self.out, self.err, self.logs = io.StringIO(), io.StringIO(), io.StringIO()

    def __call__(self, *argv: object) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(self.logs)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        level = root.level
        root.addHandler(handler)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["--verbose", *map(str, argv)])
        finally:
            root.removeHandler(handler)
            root.setLevel(level)
            _common.configure_output()  # clears the quiet flag
        self.out.write(out.getvalue())
        self.err.write(err.getvalue())
        return code, out.getvalue()

    @property
    def text(self) -> str:
        return self.out.getvalue() + self.err.getvalue() + self.logs.getvalue()


def _tree(root: Path) -> list[tuple[str, int, int]]:
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*"))


@pytest.fixture(scope="module")
def flow(tmp_path_factory: pytest.TempPathFactory):
    """The whole CLI flow once (module scope: it runs the stage 3 pipeline several times)."""
    tmp_path = tmp_path_factory.mktemp("e5")
    cli = _Transcript()
    codes: dict[str, int] = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MRI_ANON_KEY", KEY)
        patch.chdir(REPO)  # config/default.yaml is read from the current directory
        source = _input(tmp_path)
        corrections = _corrections(tmp_path)
        out = tmp_path / "out"

        codes["inspect"], inspect_json = cli("inspect", source, "--format", "bids", "--json")
        codes["process"], process_out = cli(
            "process", source, "--format", "bids", "--config", CONFIG,
            "--output-dir", out / "processed", "--manifest-path", out / "manifest" / "run.json", "--verify",
        )
        # A: labels in one go
        codes["build_a"], build_a_out = cli(
            "dataset", "build", source, "--output-dir", out / "a", "--config", CONFIG,
            "--classes", *CLASSES, "--corrections", corrections,
        )
        # B: labels step by step (incomplete at build time: ML exports skipped)
        dataset_b = out / "b" / "dataset"
        steps = [
            ("build_b", ["dataset", "build", source, "--output-dir", out / "b", "--config", CONFIG, "--classes", *CLASSES]),
            ("template_again", ["labels", "template", dataset_b, "--classes", *CLASSES]),
            ("review_incomplete", ["labels", "review", dataset_b, "--json"]),
            ("apply", ["labels", "apply", dataset_b, "--corrections", corrections]),
            ("review_complete", ["labels", "review", dataset_b, "--json"]),
            ("finalize", ["labels", "finalize", dataset_b]),
            ("finalize_again", ["labels", "finalize", dataset_b]),
            ("reopen", ["labels", "reopen", dataset_b]),
            ("export_ml_reopened", ["dataset", "export-ml", dataset_b]),
            ("finalize_after_reopen", ["labels", "finalize", dataset_b]),
            ("export_ml", ["dataset", "export-ml", dataset_b]),
            ("report", ["dataset", "report", dataset_b, out / "b" / "report_cli"]),
            ("inspect_output", ["inspect", dataset_b, "--format", "bids", "--json"]),
        ]
        outputs = {}
        for name, argv in steps:
            codes[name], outputs[name] = cli(*argv)
        snapshot = _tree(out)
        rerun = {
            "process": ["process", source, "--format", "bids", "--config", CONFIG, "--output-dir", out / "processed",
                        "--manifest-path", out / "manifest" / "run.json"],
            "build": ["dataset", "build", source, "--output-dir", out / "a", "--config", CONFIG],
            "export_ml": ["dataset", "export-ml", dataset_b],
            "report": ["dataset", "report", dataset_b, out / "b" / "report_cli"],
            "template": ["labels", "template", out / "a" / "dataset", "--classes", *CLASSES],
        }
        rerun_codes = {name: cli(*argv)[0] for name, argv in rerun.items()}
        rerun_tree = _tree(out)
    return {
        "tmp": tmp_path, "source": source, "out": out, "corrections": corrections, "cli": cli, "codes": codes,
        "inspect": inspect_json, "process": process_out, "build_a": build_a_out, "outputs": outputs,
        "snapshot": snapshot, "rerun_codes": rerun_codes, "rerun_tree": rerun_tree,
    }


def test_exit_codes_per_stage(flow) -> None:
    assert flow["codes"] == {
        "inspect": 0, "process": 0, "build_a": 0, "build_b": 0,
        "template_again": 1,  # never overwritten
        "review_incomplete": 0, "apply": 0, "review_complete": 0, "finalize": 0,
        "finalize_again": 1, "reopen": 0,
        "export_ml_reopened": 1,  # labels not finalized
        "finalize_after_reopen": 0, "export_ml": 0, "report": 0, "inspect_output": 0,
    }


def test_process_counts_manifest_and_replay(flow) -> None:
    out = flow["process"]
    assert "Studies: 4  ok: 3  failed in a step: 1  files written: 5" in out  # the NaN study fails at validate
    assert "Errors by type: {'ValueError': 1}" in out
    assert "Manifest without source paths: yes" in out and "Reproduced from manifest: yes" in out
    manifest = RunManifest.from_json((flow["out"] / "manifest" / "run.json").read_text(encoding="utf-8"))
    assert all(report.source_path is None for report in manifest.reports)
    assert sorted(p.name for p in (flow["out"] / "processed").iterdir()) == [
        f"study-{i:03d}_series-{s:03d}.nii.gz" for i, s in [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1)]
    ]


def test_build_with_corrections_finalizes_and_exports(flow) -> None:
    out, dataset = flow["build_a"], flow["out"] / "a" / "dataset"
    assert "Studies written: 3  series: 5  participants: 3  errors: 1" in out
    assert "Label corrections applied: 3" in out and "Labels finalized (3 labels)." in out
    assert "ML export files written: 4" in out and "Report files written: 4" in out
    assert (dataset / "labels_final.json").is_file() and (dataset / "splits.json").is_file()


def test_labels_step_by_step(flow) -> None:
    outputs = flow["outputs"]
    assert "WARNING LABELS_INCOMPLETE: {'UNLABELED': 3}" in outputs["build_b"]
    assert "ML exports: skipped" in outputs["build_b"]
    incomplete, complete = json.loads(outputs["review_incomplete"]), json.loads(outputs["review_complete"])
    assert incomplete == {"class_counts": {"AD": 0, "CN": 0}, "complete": False, "dataset_pairs": 3, "defects": {"UNLABELED": 3},
                          "labeled": 0}
    assert complete == {"class_counts": {"AD": 2, "CN": 1}, "complete": True, "dataset_pairs": 3, "defects": {},
                        "labeled": 3}
    assert "ML exports failed: ValueError" in outputs["export_ml_reopened"]
    assert "ML export files written: 4" in outputs["export_ml"]


def test_inspect_json_has_whitelisted_metadata_only(flow) -> None:
    source = json.loads(flow["inspect"])
    assert len(source["studies"]) == 4 and source["errors"] == {}
    sidecars = [series["sidecar"] for study in source["studies"] for series in study["series"]]
    assert sidecars and all(sidecar == {"EchoTime": 0.03, "RepetitionTime": 2.0} for sidecar in sidecars)
    written = json.loads(flow["outputs"]["inspect_output"])
    assert len(written["studies"]) == 3 and written["errors"] == {}


def test_second_run_on_the_same_output_exits_one_without_changes(flow) -> None:
    assert flow["rerun_codes"] == {"process": 1, "build": 1, "export_ml": 1, "report": 1, "template": 1}
    assert flow["rerun_tree"] == flow["snapshot"]


def test_no_phi_in_console_logs_or_json(flow) -> None:
    text = flow["cli"].text
    assert flow["cli"].logs.getvalue()  # --verbose: the services' logs were captured
    tmp, source = flow["tmp"], flow["source"]
    lowered = text.lower()
    for marker in [*PLANTED, KEY, str(tmp), tmp.as_posix(), str(source), source.as_posix()]:
        assert marker.lower() not in lowered, marker
    assert "sub-" not in lowered and "ses-" not in lowered


def test_no_phi_anywhere_in_the_output_tree(flow) -> None:
    out, tmp = flow["out"], flow["tmp"]
    forbidden = [*PLANTED, KEY, str(tmp), tmp.as_posix(), str(flow["source"]), flow["source"].as_posix()]
    files = [p for p in out.rglob("*") if p.is_file()]
    assert len(files) > 40 and (out / "manifest" / "run.json") in files
    for path in out.rglob("*"):
        relative = path.relative_to(out).as_posix()
        assert not any(marker.lower() in relative.lower() for marker in PLANTED), relative
        if path.is_file():
            content = _contents(path).decode("utf-8", errors="replace").lower()
            leaked = [m for m in forbidden if m.lower() in content or m.replace("\\", "\\\\").lower() in content]
            assert not leaked, (relative, leaked)


def test_cli_equals_services(flow, tmp_path, monkeypatch) -> None:
    """The same figures as calling the services directly with the same inputs and defaults."""
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    config = _config()
    result = run_pipeline(
        pipeline_from_config(config), config, "bids", flow["source"], tmp_path / "processed",
        tmp_path / "run.json", lambda path, error: None, verify=False,
    )
    cli_manifest = RunManifest.from_json((flow["out"] / "manifest" / "run.json").read_text(encoding="utf-8"))
    assert RunManifest.from_json((tmp_path / "run.json").read_text(encoding="utf-8")) == cli_manifest
    assert sorted(p.name for p in (tmp_path / "processed").iterdir()) == sorted(
        p.name for p in (flow["out"] / "processed").iterdir()
    )
    assert result.files_written == 5

    dataset = tmp_path / "dataset"
    report, errors = _export(flow["source"], dataset)
    assert (report.studies_written, report.series_written, report.participants, len(errors)) == (3, 5, 3, 1)
    write_label_template(dataset, dict(item.partition("=")[::2] for item in CLASSES))
    apply_label_corrections(dataset, flow["corrections"])
    finalize_labels(dataset)
    write_ml_exports(dataset)
    report_dataset(dataset, tmp_path / "report")

    cli_dataset = flow["out"] / "a" / "dataset"
    for name in ("participants.tsv", "labels.tsv", "labels.json", "splits.tsv", "dataset_index.csv", "datalist.json"):
        assert (cli_dataset / name).read_text(encoding="utf-8") == (dataset / name).read_text(encoding="utf-8"), name
    cli_report = json.loads((flow["out"] / "a" / "report" / "dataset_report.json").read_text(encoding="utf-8"))
    assert cli_report == json.loads((tmp_path / "report" / "dataset_report.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("argv", "code"),
    [
        (["process", "{src}", "--format", "bids", "--config", str(CONFIG), "--output-dir", "{out}"], 2),  # no key
        (["dataset", "build", "{src}", "--output-dir", "{src}/derivatives", "--config", str(CONFIG)], 2),
        (["dataset", "build", "{src}", "--output-dir", "{out}", "--config", str(CONFIG), "--classes", "A", "A"], 2),
        (["dataset", "export-ml", "{src}", "--ratios", "0.5", "0.5", "0.5"], 2),
        (["inspect", "{tmp}/missing", "--format", "bids"], 2),
    ],
)
def test_invalid_arguments_exit_two_and_create_nothing(tmp_path, monkeypatch, argv, code) -> None:
    source = _input(tmp_path)
    if argv[0] != "process":
        monkeypatch.setenv("MRI_ANON_KEY", KEY)
    else:
        monkeypatch.delenv("MRI_ANON_KEY", raising=False)
    monkeypatch.chdir(REPO)
    before = _tree(tmp_path)
    cli = _Transcript()
    args = [a.format(src=source, out=tmp_path / "out", tmp=tmp_path) for a in argv]
    assert cli(*args)[0] == code
    assert _tree(tmp_path) == before
    assert str(tmp_path).lower() not in cli.text.lower()


def _executables() -> list[list[str]]:
    commands = [[sys.executable, "-m", "mri_dataset_tool.presentation.cli"]]
    script = shutil.which("mri-dataset", path=os.pathsep.join([str(Path(sys.executable).parent), os.environ["PATH"]]))
    commands.append([script] if script else [])
    return commands


@pytest.mark.parametrize("command", _executables(), ids=["python-m", "mri-dataset"])
def test_installed_entry_points(command, flow, tmp_path) -> None:
    if not command:
        pytest.skip("mri-dataset is not installed (pip install -e .)")
    env = {**os.environ, "MRI_ANON_KEY": KEY}
    run = lambda *argv: subprocess.run([*command, *map(str, argv)], capture_output=True, text=True, cwd=REPO, env=env)

    assert run("--help").stdout.startswith("uso: mri-dataset")
    inspected = run("inspect", flow["source"], "--format", "bids", "--json")
    assert inspected.returncode == 0 and json.loads(inspected.stdout) == json.loads(flow["inspect"])
    review = run("labels", "review", flow["out"] / "a" / "dataset", "--json")
    assert review.returncode == 0 and json.loads(review.stdout)["complete"] is True
    missing = run("process", tmp_path / "missing", "--format", "bids", "--config", CONFIG, "--output-dir", tmp_path / "o")
    assert missing.returncode == 2 and not (tmp_path / "o").exists()
    for result in (inspected, review, missing):
        text = (result.stdout + result.stderr).lower()
        assert not [m for m in [*PLANTED, KEY, str(flow["tmp"]).lower(), str(tmp_path).lower()] if m.lower() in text]

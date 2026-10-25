"""QA5: adversarial audit of the CLI (stage 5A), as a real subprocess where the console matters.

Covers what the unit and E5 tests leave out: hostile arguments (Unicode and spaces in every path,
classes with formula prefixes, NaN/Inf ratios, extreme seeds, empty inputs), argparse echoing the typed
values, dataset commands pointed at a raw (non-anonymized) BIDS input, the stage 3/4 scripts against the
equivalent commands, determinism of two runs, ``--quiet`` and the exit-code contract (2 creates nothing).
Planted values contain ``Planted`` and are searched case-insensitively.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from mri_dataset_tool.infrastructure.anonymization.pseudonym import load_key, pseudonymize_label
from mri_dataset_tool.presentation.cli import _common
from mri_dataset_tool.presentation.cli.main import main

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config" / "stage3_bids.yaml"
KEY = "qa5-anonymization-key-0123456789abcdef"
SUBJECTS = {"PlantedSubjA": "PlantedSesA", "PlantedSubjB": "PlantedSesB", "PlantedSubjC": "PlantedSesC"}
SIDECAR = {"PatientName": "Doe^PlantedName", "InstitutionName": "PlantedHospital", "EchoTime": 0.03}
ROOT_NAME = "Ñandú PlantedRoot datos"  # Unicode and spaces in the input root
MARK = "planted"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bids(base: Path) -> Path:
    """Three sessions with a T1w (LPS 1.5 mm) and planted ids, sidecar PHI and header text."""
    rng = np.random.default_rng(5)
    root = base / ROOT_NAME / "bids"
    root.mkdir(parents=True)
    (root / "dataset_description.json").write_text('{"Name": "PlantedStudyName", "BIDSVersion": "1.9.0"}', "utf-8")
    for subject, session in SUBJECTS.items():
        anat = root / f"sub-{subject}" / f"ses-{session}" / "anat"
        anat.mkdir(parents=True)
        stem = f"sub-{subject}_ses-{session}_T1w"
        image = nib.Nifti1Image(rng.uniform(10, 100, (6, 7, 5)).astype(np.float32), np.diag([-1.5, -1.5, 1.5, 1.0]))
        image.header["descrip"] = b"PlantedDescrip"
        nib.save(image, anat / f"{stem}.nii.gz")
        (anat / f"{stem}.json").write_text(json.dumps(SIDECAR), "utf-8")
    return root


def _corrections(path: Path) -> Path:
    key = load_key()
    rows = ["participant_id\tsession_id\tlabel"]
    for i, (subject, session) in enumerate(SUBJECTS.items()):
        rows.append(f"sub-{pseudonymize_label(subject, 'subject', key)}\tses-{pseudonymize_label(session, 'session', key)}"
                    f"\t{'CN' if i else 'AD'}")
    path.write_text("\n".join(rows) + "\n", "utf-8")
    return path


def _tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def _digests(root: Path, skip: tuple[str, ...] = ()) -> dict[str, str]:
    """Relative path → sha256 of every file, except names in *skip* (non-deterministic by design)."""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file() and p.name not in skip
    }


def _cli(*argv: object) -> tuple[int, str]:
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main([*map(str, argv)])
    finally:
        _common.configure_output()
    return code, out.getvalue()


def _subprocess(*argv: object, cwd: Path = REPO, key: str | None = KEY) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "MRI_ANON_KEY"}
    if key is not None:
        env["MRI_ANON_KEY"] = key
    return subprocess.run(
        [sys.executable, "-m", "mri_dataset_tool.presentation.cli", *map(str, argv)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd, env=env,
    )


def _leaks(text: str, *extra: str) -> list[str]:
    text = text.lower()
    found = [m for m in (MARK, "ñandú", KEY.lower(), *(e.lower() for e in extra)) if m in text]
    return found


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    monkeypatch.chdir(REPO)  # config/default.yaml is read from the current directory (documented)


# --- 1. hostile arguments, PHI on the console --------------------------------------------------------


def test_unicode_and_spaces_in_every_path_full_flow_subprocess(tmp_path) -> None:
    """Input, outputs, manifest and corrections under Unicode/space names; console and tree stay clean."""
    source = _bids(tmp_path)
    out = tmp_path / "salida con espacios ü"
    corrections = _corrections(tmp_path / "corrección ñ.tsv")
    runs = [
        _subprocess("--verbose", "inspect", source, "--format", "bids", "--json"),
        _subprocess("--verbose", "process", source, "--format", "bids", "--config", CONFIG, "--output-dir",
                    out / "procesado", "--manifest-path", out / "manifiesto é.json", "--verify"),
        _subprocess("--verbose", "dataset", "build", source, "--output-dir", out / "dataset é", "--config", CONFIG,
                    "--classes", "AD=Alzheimer", "CN=Control", "--corrections", corrections),
    ]
    assert [r.returncode for r in runs] == [0, 0, 0], [r.stdout + r.stderr for r in runs]
    assert len(json.loads(runs[0].stdout)["studies"]) == 3
    for r in runs:
        assert "Traceback" not in r.stderr
        assert not _leaks(r.stdout + r.stderr, str(tmp_path)), r.stdout + r.stderr
    for path in out.rglob("*"):
        assert not _leaks(path.relative_to(out).as_posix()), path.name
        if path.is_file() and path.suffix in {".json", ".tsv", ".csv", ".md", ".xml", ""}:
            assert not _leaks(path.read_text("utf-8"), str(tmp_path)), path.name


@pytest.mark.parametrize(
    "classes",
    [["=x"], ["A", "A=other"], ["A\tB"], ["@SUM(1)"], ["+A"], ["=A"], [" A"], ["A "], ["A\nB"], ["A\x00"]],
)
def test_hostile_classes_exit_two_and_create_nothing(tmp_path, classes) -> None:
    source = _bids(tmp_path)
    before = _tree(tmp_path)
    code, text = _cli("dataset", "build", source, "--output-dir", tmp_path / "out", "--config", CONFIG, "--classes", *classes)
    assert code == 2 and text.strip() == "Invalid --classes."
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "ratios", [["nan", "nan", "nan"], ["inf", "0", "0"], ["-0.5", "1", "0.5"], ["1e308", "1e308", "-1e308"], ["0.7", "0.15", "0.1"]]
)
def test_invalid_ratios_exit_two_and_create_nothing(tmp_path, ratios) -> None:
    source = _bids(tmp_path)
    before = _tree(tmp_path)
    assert _cli("dataset", "build", source, "--output-dir", tmp_path / "o", "--config", CONFIG, "--ratios", *ratios)[0] == 2
    assert _cli("dataset", "export-ml", source, "--ratios", *ratios)[0] == 2
    assert _tree(tmp_path) == before


def test_extreme_seeds_are_accepted_and_deterministic(tmp_path) -> None:
    """``--seed`` is any Python int (random.Random): huge and negative seeds work; same seed, same splits."""
    source = _bids(tmp_path)
    splits = {}
    for name, seed in (("huge", str(10**40)), ("huge_again", str(10**40)), ("negative", "-7")):
        out = tmp_path / name
        code, text = _cli("dataset", "build", source, "--output-dir", out, "--config", CONFIG, "--seed", seed,
                          "--classes", "AD", "CN", "--corrections", _corrections(tmp_path / f"{name}.tsv"))
        assert code == 0, text
        splits[name] = json.loads((out / "dataset" / "splits.json").read_text("utf-8"))
    assert splits["huge"] == splits["huge_again"]
    assert splits["negative"]["seed"] == -7


@pytest.mark.parametrize(
    "argv",
    [
        ["inspect", "{src}", "--format", "sub-PlantedSubjA"],
        ["inspect", "{src}", "--format", "bids", "E:/pacientes/sub-PlantedSubjA"],
        ["dataset", "export-ml", "{src}", "--ratios", "Doe^PlantedName", "0", "0"],
        ["dataset", "export-ml", "{src}", "--seed", "PlantedSeed"],
    ],
    ids=["choice", "extra-positional", "ratio", "seed"],
)
def test_argparse_errors_do_not_echo_typed_values(tmp_path, argv) -> None:
    source = _bids(tmp_path)
    result = _subprocess(*[a.format(src=source) for a in argv])
    assert result.returncode == 2
    assert not _leaks(result.stdout + result.stderr, str(tmp_path)), result.stderr


def test_empty_inputs_fail_without_traceback(tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    cases = {
        ("inspect", empty, "--format", "bids", "--json"): 1,
        ("inspect", empty, "--format", "nifti"): 1,
        ("convert", "dicom-to-nifti", empty, tmp_path / "c"): 1,
        ("process", empty, "--format", "nifti", "--config", CONFIG, "--output-dir", tmp_path / "p",
         "--manifest-path", tmp_path / "p.json"): 1,
        ("dataset", "build", empty, "--output-dir", tmp_path / "b", "--config", CONFIG): 1,
        # QA5-01 fix: an empty directory is not an exported dataset → usage error before anything is read.
        ("labels", "review", empty): 2,
        ("dataset", "report", empty, tmp_path / "r"): 2,
    }
    for argv, code in cases.items():
        got, text = _cli(*argv)
        assert got == code and "Traceback" not in text and not _leaks(text, str(tmp_path)), (argv, text)
    assert not (tmp_path / "c").exists() and not (tmp_path / "p.json").exists()


@pytest.mark.parametrize("key", [None, "", "k" * 31])
def test_missing_or_short_key_exit_two_and_create_nothing(tmp_path, key) -> None:
    source = _bids(tmp_path)
    before = _tree(tmp_path)
    for argv in (
        ["anonymize", source, tmp_path / "a"],
        ["process", source, "--format", "bids", "--config", CONFIG, "--output-dir", tmp_path / "p",
         "--manifest-path", tmp_path / "p.json"],
        ["dataset", "build", source, "--output-dir", tmp_path / "b", "--config", CONFIG],
    ):
        result = _subprocess(*argv, key=key)
        assert result.returncode == 2 and "nothing was run" in result.stdout, result.stdout + result.stderr
    assert _tree(tmp_path) == before


# --- 2. dataset commands on a raw input ---------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [["labels", "template", "{src}", "--classes", "A", "B"], ["dataset", "export-ml", "{src}", "--allow-unfinalized"]],
    ids=["labels-template", "export-ml"],
)
def test_dataset_commands_refuse_a_raw_input(tmp_path, argv) -> None:
    source = _bids(tmp_path)
    before = _tree(source)
    code, _ = _cli(*[a.format(src=source) for a in argv])
    assert code == 2
    assert _tree(source) == before


_DATASET_COMMANDS = [
    ["labels", "template", "{src}", "--classes", "A", "B"],
    ["labels", "review", "{src}", "--json"],
    ["labels", "apply", "{src}", "--corrections", "{fix}"],
    ["labels", "finalize", "{src}"],
    ["labels", "reopen", "{src}"],
    ["dataset", "export-ml", "{src}", "--allow-unfinalized"],
    ["dataset", "report", "{src}", "{out}"],
]


@pytest.mark.parametrize(
    "description",
    [
        {"Name": "x", "BIDSVersion": "1.9.0"},  # a raw BIDS with its own description
        {"GeneratedBy": []},
        {"GeneratedBy": {"Name": "MRI-Dataset-Tool"}},  # an object, not a list
        {"GeneratedBy": "MRI-Dataset-Tool"},
        {"GeneratedBy": ["MRI-Dataset-Tool"]},
        {"GeneratedBy": [{"Name": "fMRIPrep"}]},
        {"GeneratedBy": [{"Name": "mri-dataset-tool"}]},
        {"GeneratedBy": [{"Name": "MRI-Dataset-Tool "}]},
        {"GeneratedBy": [{"name": "MRI-Dataset-Tool"}]},
        {"GeneratedBy": [{"Name": ["MRI-Dataset-Tool"]}]},
        [{"GeneratedBy": [{"Name": "MRI-Dataset-Tool"}]}],  # root is not an object
        "not json {",
        b"\xff\xfe\x00bad",
        None,  # dataset_description.json is a directory
    ],
    ids=lambda d: repr(d)[:40],
)
def test_raw_or_malformed_description_is_not_a_dataset(tmp_path, description) -> None:
    """QA5-01 fix: every DATASET command exits 2 and writes nothing unless GeneratedBy names the tool."""
    source = _bids(tmp_path)
    target = source / "dataset_description.json"
    target.unlink()
    if description is None:
        target.mkdir()
    elif isinstance(description, bytes):
        target.write_bytes(description)
    elif isinstance(description, str):
        target.write_text(description, "utf-8")
    else:
        target.write_text(json.dumps(description), "utf-8")
    fix = _corrections(tmp_path / "fix.tsv")
    before = _tree(tmp_path)
    for argv in _DATASET_COMMANDS:
        code, text = _cli(*[a.format(src=source, fix=fix, out=tmp_path / "r") for a in argv])
        assert code == 2 and text.strip() == "Not a dataset exported by this tool.", (argv, text)
    assert _tree(tmp_path) == before


# --- 3. invariants ------------------------------------------------------------------------------------


def test_two_process_runs_write_identical_files(tmp_path) -> None:
    source = _bids(tmp_path)
    for name in ("one", "two"):
        code, text = _cli("process", source, "--format", "bids", "--config", CONFIG, "--output-dir", tmp_path / name,
                          "--manifest-path", tmp_path / f"{name}.json")
        assert code == 0, text
    assert _digests(tmp_path / "one") == _digests(tmp_path / "two")
    manifests = [json.loads((tmp_path / f"{n}.json").read_text("utf-8")) for n in ("one", "two")]
    for m in manifests:
        m.pop("timestamps")
    assert manifests[0] == manifests[1]


def test_stage3_bids_script_equals_process_command(tmp_path) -> None:
    source = _bids(tmp_path)
    script = _load_script("run_stage3_bids_pipeline")
    with contextlib.redirect_stdout(io.StringIO()):
        assert script.main([str(source), "--output-dir", str(tmp_path / "s"), "--manifest-path", str(tmp_path / "s.json")]) == 0
    assert _cli("process", source, "--format", "bids", "--config", CONFIG, "--output-dir", tmp_path / "c",
                "--manifest-path", tmp_path / "c.json", "--verify")[0] == 0
    assert _digests(tmp_path / "s") == _digests(tmp_path / "c")
    script_m, cli_m = (json.loads((tmp_path / n).read_text("utf-8")) for n in ("s.json", "c.json"))
    script_m.pop("timestamps"), cli_m.pop("timestamps")
    assert script_m == cli_m


def test_stage4_script_equals_dataset_build_command(tmp_path) -> None:
    source = _bids(tmp_path)
    corrections = _corrections(tmp_path / "fix.tsv")
    extra = ["--classes", "AD=Alzheimer", "CN=Control", "--corrections", str(corrections), "--seed", "3"]
    script = _load_script("run_stage4_dataset")
    with contextlib.redirect_stdout(io.StringIO()):
        assert script.main([str(source), "--output-dir", str(tmp_path / "s"), "--config", str(CONFIG), *extra]) == 0
    assert _cli("dataset", "build", source, "--output-dir", tmp_path / "c", "--config", CONFIG, *extra)[0] == 0
    # run_manifest.json carries timestamps; the XLSX stores its save date (documented, QA4).
    # labels_changes.tsv has a timestamp column; the report embeds the manifest timestamps.
    skip = ("run_manifest.json", "labels_changes.tsv", *(f"dataset_report.{e}" for e in ("xlsx", "json", "md", "xml")))
    assert _digests(tmp_path / "s", skip) == _digests(tmp_path / "c", skip)
    changes = [
        [row.split("	")[1:] for row in (tmp_path / n / "dataset" / "labels_changes.tsv").read_text("utf-8").splitlines()]
        for n in ("s", "c")
    ]
    assert changes[0] == changes[1]
    assert _tree(tmp_path / "s") == _tree(tmp_path / "c")
    for name in ("s", "c"):
        manifest = json.loads((tmp_path / name / "dataset" / "code" / "run_manifest.json").read_text("utf-8"))
        manifest.pop("timestamps")
        (tmp_path / f"{name}_manifest.json").write_text(json.dumps(manifest, sort_keys=True), "utf-8")
    assert (tmp_path / "s_manifest.json").read_text("utf-8") == (tmp_path / "c_manifest.json").read_text("utf-8")


def test_quiet_prints_only_results(tmp_path) -> None:
    source = _bids(tmp_path)
    code, text = _cli("--quiet", "process", source, "--format", "bids", "--config", CONFIG, "--output-dir", tmp_path / "o",
                      "--manifest-path", tmp_path / "o.json")
    assert code == 0
    assert "Processing studies..." not in text and text.startswith("Studies: 3")


def test_usage_errors_create_nothing_across_commands(tmp_path) -> None:
    """Every code 2 leaves the tree byte-for-byte as it was (missing paths, output inside input, bad config)."""
    source = _bids(tmp_path)
    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text("pipeline:\n  steps:\n    - name: resample\n      params: {spacing: [0, 1, 1]}\n", "utf-8")
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")}
    cases = [
        ["convert", "dicom-to-nifti", source, source / "out"],
        ["convert", "nifti-to-dicom", source, source / "derivatives" / "x"],
        ["anonymize", source, source / "anon"],
        ["process", source, "--format", "bids", "--config", bad_config, "--output-dir", tmp_path / "p"],
        ["process", source, "--format", "bids", "--config", CONFIG, "--output-dir", tmp_path / "p",
         "--manifest-path", source / "m.json"],
        ["process", source, "--format", "dicom", "--config", CONFIG, "--output-dir", tmp_path / "p"],
        ["dataset", "report", source, source / "report"],
        ["dataset", "build", source, "--output-dir", tmp_path / "b", "--config", bad_config],
        ["dataset", "build", source, "--output-dir", tmp_path / "b", "--config", CONFIG, "--corrections", tmp_path / "x"],
        ["labels", "apply", source, "--corrections", tmp_path / "missing.tsv"],
        ["inspect", next(source.rglob("*.nii.gz")), "--format", "dicom"],
    ]
    for argv in cases:
        code, text = _cli(*argv)
        assert code == 2, (argv, text)
        assert not _leaks(text, str(tmp_path)), text
    assert {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")} == before

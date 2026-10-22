"""QA4 (3)/(4): invariants of the exported dataset and memory release.

Write → read keeps shape/affine (oblique too); the dataset does not depend on the input order nor on
``PYTHONHASHSEED``; partitions never split a participant, also with several sessions of mixed classes;
the label fingerprint ignores row order; the memory peak of export and report does not grow with the batch.
"""

import csv
import gc
import json
import os
import random
import subprocess
import sys
import tracemalloc
import zlib
from pathlib import Path, PurePosixPath

import nibabel as nib
import numpy as np
import openpyxl
import pytest

from mri_dataset_tool.application.pipeline.manifest import pipeline_from_config
from mri_dataset_tool.application.services.dataset import export_dataset, write_ml_exports
from mri_dataset_tool.application.services.dataset_report import report_dataset
from mri_dataset_tool.application.services.labels import (
    apply_label_corrections,
    dataset_pairs,
    finalize_labels,
    write_label_template,
)
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.anonymization.pseudonym import KEY_ENV_VAR
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.bids.reader import find_nifti_files
from mri_dataset_tool.infrastructure.dataset.splits import assign_splits

REPO = Path(__file__).resolve().parents[2]
KEY = "qa4-anonymization-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV_VAR, KEY)


def _oblique() -> np.ndarray:
    affine = np.eye(4)
    affine[:3, :3] = nib.eulerangles.euler2mat(0.3, -0.2, 0.1) @ np.diag([0.9, 1.3, 2.2])
    affine[:3, 3] = [12.5, -30.25, 7.0]
    return affine


def _study(subject: str, session: str | None, suffixes=("T1w",), shape=(5, 6, 7), affine=None) -> MRIStudy:
    rng = np.random.default_rng(zlib.crc32(f"{subject}/{session}".encode()))
    series = []
    for suffix in suffixes:
        volume = rng.uniform(1, 9, shape).astype(np.float32)
        aff = np.diag([1.0, 1.0, 1.0, 1.0]) if affine is None else affine
        series.append(MRISeries(modality=suffix, volume=volume, metadata={"shape": list(shape), "affine": aff}))
    return MRIStudy(None, series, subject_id=subject, session_id=session)


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_write_read_keeps_oblique_geometry_single_slice_and_4d(tmp_path: Path) -> None:
    studies = [
        _study("obl", None, ("T1w", "T2w"), (5, 6, 7), _oblique()),
        _study("slc", None, ("FLAIR",), (6, 5, 1), _oblique()),
        _study("dif", None, ("dwi",), (4, 5, 3, 2), _oblique()),
    ]
    expected = {(s.subject_id, x.modality): (tuple(x.metadata["shape"]), x.metadata["affine"], np.asarray(x.volume)) for s in studies for x in s.series}
    export_dataset(studies, tmp_path / "ds")
    read = {(s.subject_id, x.modality): x for s in BIDSBatchReader().load_studies(tmp_path / "ds", lazy=True) for x in s.series}
    assert set(read) == set(expected)
    for key, series in read.items():
        shape, affine, volume = expected[key]
        assert tuple(series.metadata["shape"]) == shape
        np.testing.assert_allclose(series.metadata["affine"], affine, atol=1e-5)
        np.testing.assert_array_equal(np.asanyarray(series.volume), volume)  # float32 in, float32 out


def test_dataset_does_not_depend_on_the_input_order(tmp_path: Path) -> None:
    def studies() -> list[MRIStudy]:
        return [_study(f"p{i}", ses, ("T1w", "T1w", "T2w") if i == 1 else ("T1w",)) for i in range(5) for ses in ("01", "02")]

    export_dataset(studies(), tmp_path / "a")
    export_dataset(list(reversed(studies())), tmp_path / "b")
    for root in (tmp_path / "a", tmp_path / "b"):
        write_ml_exports(root, seed=11)
    assert _tree(tmp_path / "a") == _tree(tmp_path / "b")


@pytest.mark.parametrize("seed", [0, 1, 7, 12345])
@pytest.mark.parametrize("ratios", [(0.7, 0.15, 0.15), (0.5, 0.5, 0.0), (0.34, 0.33, 0.33), (1.0, 0.0, 0.0)])
def test_multi_session_participants_never_cross_splits(tmp_path: Path, seed: int, ratios) -> None:
    rng = random.Random(seed)
    studies, labels = [], {}
    for i in range(23):
        for ses in [f"{n:02d}" for n in range(1, rng.randint(1, 3) + 1)]:
            studies.append(_study(f"p{i:02d}", ses, ("T1w", "T2w") if rng.random() < 0.3 else ("T1w",)))
            labels[(f"p{i:02d}", ses)] = rng.choice(["A", "B", "C", ""])  # mixed classes and unlabeled sessions
    root = tmp_path / "ds"
    export_dataset(studies, root)
    write_label_template(root, {"A": "a", "B": "b", "C": "c"})
    corrections = tmp_path / "c.tsv"
    corrections.write_text(
        "participant_id\tsession_id\tlabel\n" + "".join(f"sub-{p}\tses-{s}\t{v}\n" for (p, s), v in labels.items() if v),
        encoding="utf-8",
    )
    apply_label_corrections(root, corrections)
    write_ml_exports(root, ratios, seed, allow_unfinalized=True)

    with (root / "dataset_index.csv").open(encoding="utf-8", newline="") as handle:
        index = list(csv.DictReader(handle))
    splits = dict(line.split("\t") for line in (root / "splits.tsv").read_text(encoding="utf-8").splitlines()[1:])
    by_participant: dict[str, set[str]] = {}
    for row in index:
        by_participant.setdefault(row["participant_id"], set()).add(row["split"])
    assert all(len(found) == 1 for found in by_participant.values())  # one split per participant
    labelled = {f"sub-{p}" for (p, _), v in labels.items() if v}
    assert set(splits) == labelled and all(next(iter(by_participant[p])) == s for p, s in splits.items())
    datalist = json.loads((root / "datalist.json").read_text(encoding="utf-8"))
    in_splits = [item["image"] for name in ("training", "validation", "testing") for item in datalist[name]]
    unlabeled = [item["image"] for item in datalist["unlabeled"]]
    assert sorted(in_splits + unlabeled) == sorted(row["image"] for row in index) and not set(in_splits) & set(unlabeled)
    assert all("label" in item for name in ("training", "validation", "testing") for item in datalist[name])
    for name, ratio in zip(("training", "validation", "testing"), ratios):
        if ratio == 0:
            assert datalist[name] == []


def test_assign_splits_is_independent_of_the_mapping_order() -> None:
    strata = {f"p{i:03d}": (random.Random(i).choice("ABC"),) for i in range(200)}
    shuffled = dict(random.Random(1).sample(list(strata.items()), len(strata)))
    assert assign_splits(strata, seed=3) == assign_splits(shuffled, seed=3)


def test_label_fingerprint_ignores_row_order(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    export_dataset([_study(f"p{i}", None) for i in range(6)], root)
    write_label_template(root, {"A": "a", "B": "b"})
    corrections = tmp_path / "c.tsv"
    corrections.write_text("participant_id\tsession_id\tlabel\n" + "".join(f"sub-p{i}\t\t{'AB'[i % 2]}\n" for i in range(6)), encoding="utf-8")
    apply_label_corrections(root, corrections)
    finalize_labels(root)
    header, *rows = (root / "labels.tsv").read_text(encoding="utf-8").splitlines()
    (root / "labels.tsv").write_text("\n".join([header, *reversed(rows)]) + "\n", encoding="utf-8")
    assert len(write_ml_exports(root)) == 4


# --- Determinism of the whole launcher across processes (hash randomization)

_RUN = """
import sys, importlib.util
spec = importlib.util.spec_from_file_location("l", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
sys.exit(m.main(sys.argv[2:]))
"""


def _bids(root: Path) -> Path:
    rng = np.random.default_rng(3)
    (root / "dataset_description.json").parent.mkdir(parents=True)
    (root / "dataset_description.json").write_text('{"Name": "x", "BIDSVersion": "1.9.0"}', encoding="utf-8")
    for subject in ("s1", "s2", "s3", "s4", "s5"):
        for suffix in ("T1w", "T2w"):
            path = root / f"sub-{subject}" / "ses-1" / "anat" / f"sub-{subject}_ses-1_{suffix}.nii.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            nib.save(nib.Nifti1Image(rng.uniform(1, 9, (6, 7, 5)).astype(np.float32), np.diag([-1.2, 1.1, 1.4, 1.0])), path)
    return root


def _normalized(out: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(out).as_posix()
        if path.suffix == ".xlsx":
            book = openpyxl.load_workbook(path)
            result[name] = {s.title: [[c.value for c in row] for row in s.iter_rows()] for s in book.worksheets}
        elif name.endswith("run_manifest.json"):
            result[name] = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if k != "timestamps"}
        elif path.name == "labels_changes.tsv":
            result[name] = [line.split("\t")[1:] for line in path.read_text(encoding="utf-8").splitlines()]
        else:
            result[name] = path.read_bytes()
    return result


def test_launcher_output_is_identical_across_processes_and_hash_seeds(tmp_path: Path) -> None:
    source = _bids(tmp_path / "in")
    outputs = []
    for hash_seed in ("1", "987"):
        out = tmp_path / f"out{hash_seed}"
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, KEY_ENV_VAR: KEY}
        done = subprocess.run(
            [sys.executable, "-c", _RUN, str(REPO / "scripts" / "run_stage4_dataset.py"), str(source),
             "--output-dir", str(out), "--classes", "A", "B", "--allow-unfinalized", "--seed", "4"],
            env=env, capture_output=True, text=True, timeout=600,
        )
        assert done.returncode == 0, done.stdout[-2000:]
        outputs.append(_normalized(out))
    assert outputs[0].keys() == outputs[1].keys()
    assert [k for k in outputs[0] if outputs[0][k] != outputs[1][k]] == []


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows orders paths case-insensitively")
@pytest.mark.xfail(strict=True, reason="QA4-03: find_nifti_files sorts Path objects (case-insensitive on Windows)")
def test_file_order_is_the_same_on_every_os(tmp_path: Path) -> None:
    for name in ("sub-a_acq-B_T1w.nii.gz", "sub-a_acq-a_T1w.nii.gz"):
        nib.save(nib.Nifti1Image(np.ones((2, 2, 2), np.float32), np.eye(4)), tmp_path / name)
    found = [p.relative_to(tmp_path).as_posix() for p in find_nifti_files(tmp_path)]
    assert found == sorted(found, key=PurePosixPath)  # what Linux returns


# --- Memory (RNF02)


def _bids_batch(root: Path, count: int) -> Path:
    data = (np.random.default_rng(0).random((48, 48, 40)) * 1000 + 1).astype(np.float32)
    root.mkdir(parents=True)
    for index in range(count):
        path = root / f"sub-m{index:03d}" / "anat" / f"sub-m{index:03d}_T1w.nii.gz"
        path.parent.mkdir(parents=True)
        nib.save(nib.Nifti1Image(data, np.diag([1.2, 1.2, 1.5, 1.0])), path)
    return root


def _peak(function) -> float:
    gc.collect()
    tracemalloc.start()
    try:
        function()
        return tracemalloc.get_traced_memory()[1] / 2**20
    finally:
        tracemalloc.stop()


def test_export_and_report_peaks_do_not_grow_with_the_batch(tmp_path: Path) -> None:
    config = {"pipeline": {"steps": [{"name": "validate"}, {"name": "anonymize"}, {"name": "reorient"},
                                     {"name": "resample", "params": {"spacing": [1.0, 1.0, 1.0]}}, {"name": "normalize"}]}}
    peaks = {}
    for count in (3, 30):
        source = _bids_batch(tmp_path / f"in{count}", count)
        dataset = tmp_path / f"ds{count}"
        export_peak = _peak(lambda: export_dataset(
            BIDSBatchReader().iter_studies(source, lazy=True), dataset, pipeline=pipeline_from_config(config), config=config
        ))
        assert len(dataset_pairs(dataset)) == count
        report_peak = _peak(lambda: report_dataset(dataset, tmp_path / f"rep{count}"))
        peaks[count] = (export_peak, report_peak)
    (small_export, small_report), (large_export, large_report) = peaks[3], peaks[30]
    assert large_export <= small_export * 1.1 + 1.0, peaks
    assert large_report <= small_report * 1.1 + 1.0, peaks

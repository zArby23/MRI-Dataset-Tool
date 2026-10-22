import json
import math
import weakref
from pathlib import Path

import numpy as np
import pytest

from mri_dataset_tool.application.services.summary import summarize_study
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.dataset.exporters import to_json, to_markdown, write_json, write_markdown
from mri_dataset_tool.infrastructure.dataset.report import build_dataset_summary

SECRETS = ("SECRET", "1.2.840.99", "19700101", "C:\\private", "/home/private")


def _series(volume, modality="T1w", voxel_size=(1.0, 1.0, 1.0), findings=()) -> MRISeries:
    return MRISeries(
        modality=modality,
        volume=volume,
        metadata={
            "shape": None if volume is None else tuple(volume.shape),
            "voxel_size": voxel_size,
            "affine": np.diag([*voxel_size, 1.0]),
            "orientation": ("R", "A", "S"),
            "validation": {"status": "ok", "findings": list(findings)},
        },
    )


def _entry(subject, session, *series):
    return subject, session, summarize_study(MRIStudy(study_uid=None, series=list(series)))


def _dataset():
    a = np.arange(8, dtype=np.float32).reshape(2, 2, 2)
    b = np.full((2, 2, 2), 3.0, dtype=np.float32)
    b[0, 0, 0] = np.nan
    return [
        _entry("01", "1", _series(a), _series(np.zeros((2, 2, 2, 3), np.float32), "dwi", (2.0, 2.0, 2.0))),
        _entry("01", "2", _series(b, findings=["CONSTANT_VOLUME"])),
        _entry("02", None, _series(a, voxel_size=(0.99999999, 1.0, 1.0))),
    ], (a, b)


def test_counts_and_distributions() -> None:
    entries, _ = _dataset()
    summary = build_dataset_summary(entries)
    assert (summary["studies"], summary["participants"], summary["sessions"], summary["series"]) == (3, 2, 3, 4)
    assert list(summary["modalities"]) == ["T1w", "dwi"]
    t1 = summary["modalities"]["T1w"]
    assert t1["series"] == 3
    assert t1["shape"] == [{"value": [2, 2, 2], "count": 3}]
    assert t1["voxel_size"] == [{"value": [1.0, 1.0, 1.0], "count": 3}]  # rounding groups 0.99999999
    assert t1["orientation"] == [{"value": ["R", "A", "S"], "count": 3}]
    assert t1["dtype"] == [{"value": "float32", "count": 3}]
    assert summary["modalities"]["dwi"]["shape"] == [{"value": [2, 2, 2, 3], "count": 1}]
    assert summary["labels"] is None
    assert summary["warnings"] == [{"code": "CONSTANT_VOLUME", "count": 1}, {"code": "NON_FINITE_VOXELS", "count": 1}]


def test_intensity_is_aggregated_over_finite_voxels() -> None:
    entries, (a, b) = _dataset()
    intensity = build_dataset_summary(entries)["modalities"]["T1w"]["intensity"]
    values = np.concatenate([a.ravel(), b[np.isfinite(b)], a.ravel()]).astype(np.float64)
    assert intensity["finite_voxels"] == values.size
    assert intensity["non_finite_voxels"] == 1
    assert (intensity["min"], intensity["max"]) == (values.min(), values.max())
    assert intensity["mean"] == pytest.approx(values.mean())
    assert intensity["std"] == pytest.approx(values.std())


def test_series_without_volume_or_subject_are_warned() -> None:
    summary = build_dataset_summary([_entry(None, None, _series(None))])
    assert summary["participants"] == summary["sessions"] == 0
    assert summary["modalities"]["T1w"]["intensity"] == {
        "min": None, "max": None, "mean": None, "std": None, "finite_voxels": 0, "non_finite_voxels": 0,
    }
    assert summary["warnings"] == [{"code": "MISSING_SUBJECT_ID", "count": 1}, {"code": "NO_VOLUME", "count": 1}]
    assert build_dataset_summary([_entry("01", None, MRISeries())])["modalities"]["unknown"]["series"] == 1


def test_labels_balance_unlabeled_and_declared_classes() -> None:
    entries, _ = _dataset()
    labels = {("01", "1"): "tumor", ("01", "2"): "", ("02", None): "other", ("99", None): "tumor"}
    summary = build_dataset_summary(entries, labels, classes=["healthy", "tumor"])
    assert summary["labels"] == {
        "classes": {
            "healthy": {"participants": 0, "sessions": 0, "series": 0},
            "other": {"participants": 1, "sessions": 1, "series": 1},
            "tumor": {"participants": 1, "sessions": 1, "series": 2},
        },
        "unlabeled_sessions": 1,
        "unlabeled_participants": 1,
    }
    codes = {w["code"]: w["count"] for w in summary["warnings"]}
    assert codes["UNLABELED_SESSIONS"] == 1 and codes["UNKNOWN_CLASS"] == 1


def test_entries_are_consumed_lazily() -> None:
    class Summary(dict):  # dicts are not weak-referenceable
        pass

    previous: list[weakref.ref] = []

    def entries():
        for subject in ("01", "02", "03"):
            assert all(ref() is None for ref in previous)
            item = Summary(summarize_study(MRIStudy(study_uid=None, series=[_series(np.ones((2, 2, 2)))])))
            previous.append(weakref.ref(item))
            yield subject, None, item
            del item

    assert build_dataset_summary(entries())["studies"] == 3


def test_output_is_json_pure_and_deterministic() -> None:
    first = build_dataset_summary(_dataset()[0], {("01", "1"): "tumor"})
    second = build_dataset_summary(_dataset()[0], {("01", "1"): "tumor"})
    assert first == second
    assert json.loads(to_json(first)) == first
    assert to_json(first) == to_json(second) and to_markdown(first) == to_markdown(second)
    with pytest.raises(ValueError):
        to_json({"x": math.nan})


def test_markdown_shows_the_same_figures_as_the_json() -> None:
    summary = build_dataset_summary(_dataset()[0], {("01", "1"): "tumor"}, classes=["tumor"])
    markdown = to_markdown(summary)
    for stats in summary["modalities"].values():
        for value in stats["intensity"].values():
            assert f" {json.dumps(value)} " in markdown
    assert "| tumor | 1 | 1 | 2 |" in markdown
    assert "| CONSTANT_VOLUME | 1 |" in markdown


def test_markdown_escapes_table_separators() -> None:
    summary = build_dataset_summary([_entry("01", None, _series(np.ones((2, 2, 2)), modality="a|b\nc"))])
    assert "### a\\|b c" in to_markdown(summary)


def test_no_phi_in_json_or_markdown(tmp_path: Path) -> None:
    series = _series(np.ones((2, 2, 2), np.float32))
    series.series_uid = "1.2.840.99.1"
    series.files = [Path("C:\\private\\sub-SECRET_T1w.nii.gz")]
    series.metadata.update({
        "PatientName": "SECRET^NAME",
        "StudyDate": "19700101",
        "source": "/home/private/x.nii.gz",
        "provenance": {"tool": "x", "path": "/home/private/x"},
        "bids": {"sub": "SECRET"},
        "sidecar": {"RepetitionTime": 2.0, "PatientName": "SECRET^NAME", "AcquisitionDateTime": "19700101T1010"},
    })
    study = MRIStudy(study_uid="1.2.840.99.3", series=[series], subject_id="SECRET", session_id="SECRET")
    summary = build_dataset_summary([("SECRET", "SECRET", summarize_study(study))], {("SECRET", "SECRET"): "tumor"})
    for text in (to_json(summary), to_markdown(summary)):
        for secret in (*SECRETS, str(tmp_path)):
            assert secret not in text


@pytest.mark.parametrize("writer", [write_json, write_markdown])
def test_writers_do_not_overwrite_and_leave_no_temporaries(tmp_path: Path, writer) -> None:
    summary = build_dataset_summary(_dataset()[0])
    path = writer(summary, tmp_path / "report.out")
    assert b"\r\n" not in path.read_bytes()
    before = path.read_bytes()
    with pytest.raises(FileExistsError, match=r"^Report file already exists\.$"):
        writer(summary, path)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.out"]


@pytest.mark.parametrize("writer", [write_json, write_markdown])
def test_unencodable_content_has_fixed_message_and_leaves_nothing(tmp_path: Path, writer) -> None:
    summary = build_dataset_summary(_dataset()[0], {("01", "1"): "A\ud800"})
    with pytest.raises(ValueError, match=r"^Report content is invalid\.$") as info:
        writer(summary, tmp_path / "r.out")
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert list(tmp_path.iterdir()) == []


def test_series_without_shape_is_warned_and_left_out_of_intensity() -> None:
    series = _series(np.ones((2, 2, 2)))
    del series.metadata["shape"]
    summary = build_dataset_summary([_entry("01", None, series)])
    assert summary["modalities"]["T1w"]["intensity"]["finite_voxels"] == 0
    assert summary["warnings"] == [{"code": "MISSING_SHAPE", "count": 1}]


def test_write_failure_has_fixed_message(tmp_path: Path) -> None:
    with pytest.raises(OSError, match=r"^Report file could not be written\.$"):
        write_json({}, tmp_path / "missing_dir" / "report.json")

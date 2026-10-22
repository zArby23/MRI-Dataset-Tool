import gzip
import json
import logging
import weakref
from pathlib import Path

import numpy as np
import pytest

from mri_dataset_tool.application.pipeline.manifest import RunManifest, pipeline_from_config, pipeline_from_manifest
from mri_dataset_tool.application.services.dataset import DatasetReport, export_dataset
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy

KEY = "k" * 40
SECRETS = ("SECRETNAME", "1.2.840.99", "19700101", "private")


def _series(modality="T1w", volume=None, source: Path | None = None) -> MRISeries:
    volume = np.arange(1, 61, dtype=np.float32).reshape(3, 4, 5) if volume is None else volume
    return MRISeries(
        series_uid="1.2.840.99.1",
        modality=modality,
        volume=volume,
        files=[] if source is None else [source],
        metadata={
            "shape": tuple(volume.shape),
            "voxel_size": (1.0, 1.0, 1.0),
            "affine": np.eye(4),
            "orientation": ("R", "A", "S"),
            "PatientName": "SECRETNAME",
            "sidecar": {"RepetitionTime": 2.0, "AcquisitionDateTime": "19700101T1010", "PatientName": "SECRETNAME"},
        },
    )


def _study(subject="01", session="01", *series) -> MRIStudy:
    return MRIStudy(study_uid="1.2.840.99.3", series=list(series) or [_series()], subject_id=subject, session_id=session)


def _config(*steps: str) -> dict:
    return {"pipeline": {"steps": [{"name": name} for name in steps]}}


def test_export_without_pipeline_counts_and_continues(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    errors: list[tuple[Path, str]] = []
    report = export_dataset(
        [_study("01", "01", _series(), _series("MR")), _study(None, "01"), _study("02", None)],
        root,
        lambda path, error: errors.append((path, str(error))),
    )
    assert report == DatasetReport(studies_written=2, series_written=2, participants=2, errors=2)
    assert errors == [(Path("sub-01/ses-01"), "Unsupported BIDS suffix."), (Path(), "Study has no subject id.")]
    assert (root / "participants.tsv").read_text(encoding="utf-8") == "participant_id\nsub-01\nsub-02\n"
    assert not (root / "code/run_manifest.json").exists()


@pytest.mark.parametrize("relative", [".", "inside", "inside/deeper"])
def test_output_inside_the_input_is_rejected_before_creating_anything(tmp_path: Path, relative) -> None:
    source = tmp_path / "input"
    source.mkdir()
    root = source / relative
    before = sorted(source.rglob("*"))
    with pytest.raises(ValueError, match=r"^Output directory must be outside the input directory\.$"):
        export_dataset([_study()], root, source_dir=source)
    assert sorted(source.rglob("*")) == before


def test_existing_output_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "ds").mkdir()
    with pytest.raises(FileExistsError, match=r"^Dataset directory already exists\.$"):
        export_dataset([_study()], tmp_path / "ds")


def test_one_study_alive_at_a_time(tmp_path: Path) -> None:
    previous: list[weakref.ref] = []

    def studies():
        for subject in ("01", "02", "03"):
            assert all(ref() is None for ref in previous)  # the previous study (and its volume) was released
            study = _study(subject, "01")
            previous.append(weakref.ref(study))
            yield study
            del study

    assert export_dataset(studies(), tmp_path / "ds").studies_written == 3


def test_pipeline_manifest_travels_without_source_paths(tmp_path: Path) -> None:
    source = tmp_path / "private" / "sub-01_T1w.nii.gz"
    nan_volume = np.full((3, 4, 5), np.nan, dtype=np.float32)
    config = {**_config("validate"), "report": {"path": "C:/Users/SECRETUSER/out/m.json"}, "logging": {"level": "INFO"}}
    errors: list[Exception] = []
    report = export_dataset(
        [_study("01", "01", _series(source=source)), _study("02", "01", _series(volume=nan_volume, source=source))],
        tmp_path / "ds",
        lambda _, error: errors.append(error),
        pipeline=pipeline_from_config(config),
        config=config,
    )
    assert report == DatasetReport(studies_written=1, series_written=1, participants=1, errors=1)
    assert [str(e) for e in errors] == ["Volume contains non-finite values."]
    text = (tmp_path / "ds/code/run_manifest.json").read_text(encoding="utf-8")
    manifest = RunManifest.from_json(text)
    assert [r.source_path for r in manifest.reports] == [None, None]
    assert [s.status for r in manifest.reports for s in r.steps] == ["ok", "failed"]
    assert manifest.config == {"pipeline": config["pipeline"], "logging": {"level": "INFO"}}
    for secret in (str(tmp_path), "private", "SECRETUSER"):
        assert secret not in text
    assert pipeline_from_manifest(manifest).steps[0].name == "validate"


def test_anonymized_export_has_no_phi(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("MRI_ANON_KEY", KEY)
    caplog.set_level(logging.DEBUG)
    source = tmp_path / "private" / "SECRETNAME" / "sub-01_T1w.nii.gz"
    config = _config("validate", "anonymize")
    root = tmp_path / "ds"
    report = export_dataset(
        [_study("01", "01", _series(source=source), _series("dwi", source=source))],
        root,
        pipeline=pipeline_from_config(config),
        config=config,
    )
    assert report.series_written == 2 and report.errors == 0
    participants = (root / "participants.tsv").read_text(encoding="utf-8").split()
    assert participants[0] == "participant_id" and participants[1] != "sub-01" and len(participants[1]) == 20
    assert "Anonymization policy" in (root / "dataset_description.json").read_text(encoding="utf-8")
    names = [p.relative_to(root).as_posix() for p in root.rglob("*")]
    assert not any("sub-01" in name for name in names)
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            data = gzip.decompress(data) if path.name.endswith(".gz") else data
            for secret in (*SECRETS, str(tmp_path), "sub-01"):
                assert secret.encode() not in data, (path.name, secret)
    sidecars = [json.loads(p.read_text(encoding="utf-8")) for p in root.rglob("sub-*.json")]
    assert sidecars == [{"RepetitionTime": 2.0}] * 2
    for secret in (*SECRETS, str(tmp_path)):
        assert secret not in caplog.text

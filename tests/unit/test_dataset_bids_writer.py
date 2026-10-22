import gzip
import json
import logging
from pathlib import Path

import numpy as np
import pytest

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.anonymization.policy import POLICY_VERSION, SIDECAR_WHITELIST
from mri_dataset_tool.infrastructure.bids.batch_reader import BIDSBatchReader
from mri_dataset_tool.infrastructure.dataset import bids_writer
from mri_dataset_tool.infrastructure.dataset.bids_writer import BIDSDatasetWriter
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader

SECRETS = ("SECRETNAME", "1.2.840.99", "19700101", "C:\\private", "/home/private", "103000")
AFFINE = np.array([[0.0, 0.0, 2.0, -10.0], [1.5, 0.0, 0.0, 5.0], [0.0, 1.0, 0.0, 3.0], [0.0, 0.0, 0.0, 1.0]])


def _series(modality="T1w", volume=None, sidecar=None, shape=(3, 4, 5)) -> MRISeries:
    volume = np.arange(np.prod(shape), dtype=np.int16).reshape(shape) if volume is None else volume
    return MRISeries(
        modality=modality,
        volume=volume,
        metadata={"shape": tuple(volume.shape), "affine": AFFINE.copy(), "sidecar": sidecar or {}},
    )


def _study(subject="a1", session="01", *series) -> MRIStudy:
    return MRIStudy(study_uid=None, series=list(series) or [_series()], subject_id=subject, session_id=session)


def _tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


class _UnreadableVolume:
    shape = (3, 4, 5)
    dtype = np.dtype(np.float32)

    def __array__(self, dtype=None, copy=None):
        raise OSError("disk gone")


def test_layout_geometry_and_dtype(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    writer = BIDSDatasetWriter(root)
    written = writer.add_study(_study("a1", "01", _series("T1w"), _series("dwi", shape=(3, 4, 5, 2))))
    assert written == [
        root / "sub-a1/ses-01/anat/sub-a1_ses-01_T1w.nii.gz",
        root / "sub-a1/ses-01/dwi/sub-a1_ses-01_dwi.nii.gz",
    ]
    for path in written:
        assert path.with_name(path.name.replace(".nii.gz", ".json")).is_file()
    series = NIfTIReader().load_study(written[0]).series[0]
    assert series.metadata["shape"] == (3, 4, 5)
    np.testing.assert_allclose(series.metadata["affine"], AFFINE)
    np.testing.assert_allclose(series.metadata["voxel_size"], (1.5, 1.0, 2.0))
    assert series.metadata["datatype"] == "float32"
    np.testing.assert_array_equal(series.volume, np.arange(60).reshape(3, 4, 5))


def test_without_session_and_participants(tmp_path: Path) -> None:
    writer = BIDSDatasetWriter(tmp_path / "ds")
    writer.add_study(_study("b2", None))
    writer.add_study(_study("a1", "02"))
    writer.add_study(_study("a1", "01"))
    assert (tmp_path / "ds/sub-b2/anat/sub-b2_T1w.nii.gz").is_file()
    assert writer.participants == ["a1", "b2"]


def test_repeated_suffix_gets_runs_in_series_order(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    first, second = _series("T1w", np.zeros((3, 4, 5), np.float32)), _series("T1w", np.ones((3, 4, 5), np.float32))
    written = BIDSDatasetWriter(root).add_study(_study("a1", "01", first, _series("FLAIR"), second))
    assert [p.name for p in written] == [
        "sub-a1_ses-01_run-1_T1w.nii.gz",
        "sub-a1_ses-01_FLAIR.nii.gz",
        "sub-a1_ses-01_run-2_T1w.nii.gz",
    ]
    assert NIfTIReader().load_study(written[2]).series[0].volume.max() == 1.0


def test_sidecar_keeps_only_whitelisted_plain_values(tmp_path: Path) -> None:
    sidecar = {
        "RepetitionTime": 2.0,
        "SliceTiming": [0.0, 0.5],
        "EchoTime": float("nan"),
        "FlipAngle": {"nested": 1},
        "AcquisitionTime": "10:30:00",
        "PatientName": "SECRETNAME",
    }
    written = BIDSDatasetWriter(tmp_path / "ds").add_study(_study("a1", "01", _series(sidecar=sidecar)))
    data = json.loads(written[0].with_name("sub-a1_ses-01_T1w.json").read_text(encoding="utf-8"))
    assert data == {"RepetitionTime": 2.0, "SliceTiming": [0.0, 0.5]}
    assert set(data) <= SIDECAR_WHITELIST


@pytest.mark.parametrize(
    ("subject", "session", "message"),
    [
        (None, "01", "Study has no subject id."),
        ("a_1", "01", "Invalid BIDS label."),
        ("a1", "../x", "Invalid BIDS label."),
        ("a1", "", "Invalid BIDS label."),
    ],
)
def test_invalid_ids_raise_and_write_nothing(tmp_path: Path, subject, session, message) -> None:
    root = tmp_path / "ds"
    with pytest.raises(ValueError) as info:
        BIDSDatasetWriter(root).add_study(_study(subject, session))
    assert str(info.value) == message
    assert _tree(root) == []


def test_duplicate_study_and_mixed_sessions_are_rejected(tmp_path: Path) -> None:
    writer = BIDSDatasetWriter(tmp_path / "ds")
    writer.add_study(_study("a1", "01"))
    writer.add_study(_study("b2", None))
    with pytest.raises(ValueError, match=r"^Study subject/session was already written\.$"):
        writer.add_study(_study("a1", "01"))
    with pytest.raises(ValueError, match=r"^Study session layout is inconsistent for its subject\.$"):
        writer.add_study(_study("a1", None))
    with pytest.raises(ValueError, match=r"^Study session layout is inconsistent for its subject\.$"):
        writer.add_study(_study("b2", "01"))


def test_bad_series_are_reported_and_the_rest_is_written(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    bad_geometry = _series("T2w")
    bad_geometry.metadata["shape"] = (9, 9, 9)
    unreadable = _series("PDw", volume=_UnreadableVolume())
    errors: list[tuple[Path, Exception]] = []
    written = BIDSDatasetWriter(root).add_study(
        _study("a1", "01", _series("MR"), _series(None), bad_geometry, unreadable, _series("T1w")),
        lambda path, error: errors.append((path, error)),
    )
    assert [p.name for p in written] == ["sub-a1_ses-01_T1w.nii.gz"]
    assert [str(e) for _, e in errors] == [
        "Unsupported BIDS suffix.",
        "Unsupported BIDS suffix.",
        "Series shape does not match its volume.",
        "Unable to read volume data.",
    ]
    assert all(path == Path("sub-a1/ses-01") for path, _ in errors)
    assert _tree(root) == [
        "sub-a1", "sub-a1/ses-01", "sub-a1/ses-01/anat",
        "sub-a1/ses-01/anat/sub-a1_ses-01_T1w.json", "sub-a1/ses-01/anat/sub-a1_ses-01_T1w.nii.gz",
    ]


def test_study_with_no_written_series_is_not_a_participant(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    writer = BIDSDatasetWriter(root)
    assert writer.add_study(_study("a1", "01", _series("MR"))) == []
    assert writer.participants == [] and _tree(root) == []


def test_sidecar_failure_removes_the_image_and_empty_folders(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ds"

    def fail(path, data):
        raise OSError("Dataset file could not be written.")

    monkeypatch.setattr(bids_writer, "_write_bytes", fail)
    errors: list[Exception] = []
    assert BIDSDatasetWriter(root).add_study(_study(), lambda _, e: errors.append(e)) == []
    assert [type(e) for e in errors] == [OSError]
    assert _tree(root) == []


def test_callback_that_raises_does_not_stop_the_study(tmp_path: Path) -> None:
    def explode(path, error):
        raise RuntimeError("boom")

    written = BIDSDatasetWriter(tmp_path / "ds").add_study(_study("a1", "01", _series("MR"), _series()), explode)
    assert len(written) == 1


def test_never_overwrites(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    root.mkdir()
    with pytest.raises(FileExistsError, match=r"^Dataset directory already exists\.$"):
        BIDSDatasetWriter(root)
    other = tmp_path / "ds2"
    writer = BIDSDatasetWriter(other)
    image = other / "sub-a1/ses-01/anat/sub-a1_ses-01_T1w.nii.gz"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"keep")
    errors: list[Exception] = []
    assert writer.add_study(_study(), lambda _, e: errors.append(e)) == []
    assert str(errors[0]) == "Dataset file already exists." and image.read_bytes() == b"keep"
    writer.finalize()
    before = (other / "README").read_bytes()
    with pytest.raises(FileExistsError, match=r"^Dataset file already exists\.$"):
        writer.finalize()
    assert (other / "README").read_bytes() == before


def test_finalize_files(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    writer = BIDSDatasetWriter(root)
    writer.add_study(_study("b2", "01"))
    writer.add_study(_study("a1", "01"))
    manifest = json.dumps({"steps": [{"name": "anonymize", "version": "1", "params": {}}], "reports": []})
    writer.finalize(manifest)
    description = json.loads((root / "dataset_description.json").read_text(encoding="utf-8"))
    assert description["DatasetType"] == "raw" and description["BIDSVersion"]
    assert description["GeneratedBy"][0]["Name"] == "MRI-Dataset-Tool"
    assert description["GeneratedBy"][0]["Description"] == f"Anonymization policy {POLICY_VERSION}"
    assert (root / "participants.tsv").read_bytes() == b"participant_id\nsub-a1\nsub-b2\n"
    assert list(json.loads((root / "participants.json").read_text(encoding="utf-8"))) == ["participant_id"]
    assert f"policy {POLICY_VERSION}" in (root / "README").read_text(encoding="utf-8")
    assert (root / "code/run_manifest.json").read_text(encoding="utf-8") == manifest
    assert not list(root.rglob(".*.tmp"))


def test_finalize_without_anonymize_does_not_claim_it(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    BIDSDatasetWriter(root).finalize()
    assert "Description" not in json.loads((root / "dataset_description.json").read_text())["GeneratedBy"][0]
    assert "No anonymization step" in (root / "README").read_text(encoding="utf-8")
    assert not (root / "code").exists()
    assert (root / "participants.tsv").read_text(encoding="utf-8") == "participant_id\n"


@pytest.mark.parametrize("manifest", ["not json", "[]", '{"steps": 3}', '{"other": []}', '{"steps": []}', '{"steps": [], "reports": [3]}'])
def test_invalid_manifest_writes_nothing(tmp_path: Path, manifest) -> None:
    root = tmp_path / "ds"
    with pytest.raises(ValueError, match=r"^Invalid run manifest\.$"):
        BIDSDatasetWriter(root).finalize(manifest)
    assert _tree(root) == []


def test_written_dataset_is_read_back_by_the_bids_reader(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    writer = BIDSDatasetWriter(root)
    writer.add_study(_study("a1", "01", _series("T1w", sidecar={"RepetitionTime": 2.0}), _series("T1w")))
    writer.add_study(_study("b2", "01", _series("dwi", shape=(3, 4, 5, 2))))
    writer.finalize()
    errors: list[Exception] = []
    studies = BIDSBatchReader().load_studies(root, lambda _, e: errors.append(e))
    assert errors == []
    assert [(s.subject_id, s.session_id, [x.modality for x in s.series]) for s in studies] == [
        ("a1", "01", ["T1w", "T1w"]),
        ("b2", "01", ["dwi"]),
    ]
    assert studies[0].series[0].metadata["sidecar"] == {"RepetitionTime": 2.0}
    assert studies[1].series[0].metadata["shape"] == (3, 4, 5, 2)


def test_output_is_deterministic(tmp_path: Path) -> None:
    def export(root: Path) -> dict[str, bytes]:
        writer = BIDSDatasetWriter(root)
        writer.add_study(_study("a1", "01", _series(sidecar={"EchoTime": 0.03})))
        writer.finalize('{"steps": [], "reports": [{"source_path": null}]}')
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    assert export(tmp_path / "one") == export(tmp_path / "two")


def test_no_phi_in_names_contents_or_logs(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    series = _series(sidecar={
        "RepetitionTime": 2.0,
        "PatientName": "SECRETNAME",
        "AcquisitionDateTime": "19700101T103000",
        "SeriesInstanceUID": "1.2.840.99.2",
    })
    series.series_uid = "1.2.840.99.1"
    series.files = [Path("C:\\private\\SECRETNAME.nii.gz"), Path("/home/private/x.nii.gz")]
    series.metadata.update({
        "PatientName": "SECRETNAME",
        "StudyDate": "19700101",
        "provenance": {"path": "/home/private/x"},
        "bids": {"sub": "SECRETNAME"},
    })
    root = tmp_path / "ds"
    writer = BIDSDatasetWriter(root)
    writer.add_study(MRIStudy(study_uid="1.2.840.99.3", series=[series, _series("MR")], subject_id="a1", session_id="01"))
    writer.finalize()
    for path in root.rglob("*"):
        assert not any(secret in path.name for secret in SECRETS)
        if path.is_file():
            data = path.read_bytes()
            data = gzip.decompress(data) if path.name.endswith(".gz") else data
            for secret in (*SECRETS, str(tmp_path)):
                assert secret.encode() not in data
    for secret in (*SECRETS, "a1"):
        assert secret not in caplog.text


@pytest.mark.parametrize("source", ["C:/Users/SECRETUSER/in/x.nii.gz", "", "relative/x.nii.gz"])
def test_manifest_with_source_paths_is_rejected(tmp_path: Path, source) -> None:
    root = tmp_path / "ds"
    manifest = json.dumps({"steps": [], "reports": [{"source_path": None}, {"source_path": source}]})
    with pytest.raises(ValueError) as info:
        BIDSDatasetWriter(root).finalize(manifest)
    assert str(info.value) == "Run manifest must not contain source paths."
    assert _tree(root) == []


def test_finalize_failure_leaves_nothing_and_can_be_retried(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ds"
    writer = BIDSDatasetWriter(root)
    real = bids_writer._write_bytes
    calls = 0

    def fail_third(path, data):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("Dataset file could not be written.")
        real(path, data)

    monkeypatch.setattr(bids_writer, "_write_bytes", fail_third)
    with pytest.raises(OSError):
        writer.finalize('{"steps": [], "reports": []}')
    assert _tree(root) == []
    monkeypatch.setattr(bids_writer, "_write_bytes", real)
    assert len(writer.finalize('{"steps": [], "reports": []}')) == 5

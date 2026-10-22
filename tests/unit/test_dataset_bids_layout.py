from pathlib import PurePosixPath

import pytest

from mri_dataset_tool.infrastructure.bids.entities import parse_bids_filename
from mri_dataset_tool.infrastructure.dataset.bids_layout import (
    SUFFIX_DATATYPES,
    bids_path,
    datatype_for,
    validate_label,
)

EXPECTED_DATATYPES = {
    "T1w": "anat",
    "T2w": "anat",
    "PDw": "anat",
    "T2starw": "anat",
    "FLAIR": "anat",
    "dwi": "dwi",
    "magnitude1": "fmap",
    "magnitude2": "fmap",
    "phasediff": "fmap",
}

INVALID_LABELS = ["", "a_b", "a b", "a/b", "..", "a-b", "a.b", "a\\b", "ab\n", "é1", None, 1]


def test_supported_suffixes_are_exactly_the_documented_ones():
    assert SUFFIX_DATATYPES == EXPECTED_DATATYPES


@pytest.mark.parametrize(("suffix", "datatype"), EXPECTED_DATATYPES.items())
@pytest.mark.parametrize("extension", [".nii.gz", ".json"])
def test_path_with_session(suffix, datatype, extension):
    path = bids_path("01", "a1", suffix, extension)
    assert path == PurePosixPath(f"sub-01/ses-a1/{datatype}/sub-01_ses-a1_{suffix}{extension}")
    entities = parse_bids_filename(path.name)
    assert (entities.sub, entities.ses, entities.suffix, entities.other) == ("01", "a1", suffix, {})


@pytest.mark.parametrize(("suffix", "datatype"), EXPECTED_DATATYPES.items())
def test_path_without_session(suffix, datatype):
    path = bids_path("01", None, suffix)
    assert path == PurePosixPath(f"sub-01/{datatype}/sub-01_{suffix}.nii.gz")
    assert not path.is_absolute()


def test_default_extension_is_nii_gz():
    assert bids_path("1", None, "T1w").name.endswith(".nii.gz")


@pytest.mark.parametrize("label", INVALID_LABELS)
def test_invalid_subject(label):
    with pytest.raises(ValueError) as info:
        bids_path(label, "01", "T1w")
    assert str(info.value) == "Invalid BIDS label."


@pytest.mark.parametrize("label", [lbl for lbl in INVALID_LABELS if lbl is not None])
def test_invalid_session(label):
    with pytest.raises(ValueError) as info:
        bids_path("01", label, "T1w")
    assert str(info.value) == "Invalid BIDS label."


@pytest.mark.parametrize("label", INVALID_LABELS)
def test_validate_label_rejects(label):
    with pytest.raises(ValueError, match=r"^Invalid BIDS label\.$"):
        validate_label(label)


@pytest.mark.parametrize("label", ["01", "abc", "A1b2", "0f3a9c1d2e4b5a6c"])
def test_validate_label_accepts(label):
    assert validate_label(label) == label


@pytest.mark.parametrize(
    "suffix", [None, "", "MR", "t1w", "T1", "bold", "T1w ", "anat", "sub-01_T1w", 3]
)
def test_unknown_suffix(suffix):
    with pytest.raises(ValueError) as info:
        bids_path("01", "01", suffix)
    assert str(info.value) == "Unsupported BIDS suffix."
    with pytest.raises(ValueError, match=r"^Unsupported BIDS suffix\.$"):
        datatype_for(suffix)


@pytest.mark.parametrize("extension", [".nii", ".NII.GZ", ".tsv", "", "nii.gz"])
def test_unsupported_extension(extension):
    with pytest.raises(ValueError, match=r"^Unsupported BIDS extension\.$"):
        bids_path("01", "01", "T1w", extension)


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ("a1", "sub-01/ses-a1/dwi/sub-01_ses-a1_run-2_dwi.json"),
        (None, "sub-01/dwi/sub-01_run-2_dwi.json"),
    ],
)
def test_run_entity_follows_bids_order(session, expected):
    path = bids_path("01", session, "dwi", ".json", run=2)
    assert path == PurePosixPath(expected)
    entities = parse_bids_filename(path.name)
    assert (entities.sub, entities.ses, entities.other) == ("01", session, {"run": "2"})


def test_run_none_is_omitted():
    assert "run-" not in str(bids_path("01", "01", "T1w", run=None))


@pytest.mark.parametrize("run", [0, -1, True, False, 1.0, "1", "01"])
def test_invalid_run(run):
    with pytest.raises(ValueError, match=r"^Invalid BIDS run\.$"):
        bids_path("01", "01", "T1w", run=run)


def test_error_messages_do_not_echo_input():
    with pytest.raises(ValueError) as info:
        bids_path("01", "01", "PatientName")
    assert "PatientName" not in str(info.value)

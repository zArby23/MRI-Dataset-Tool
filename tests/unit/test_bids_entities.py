import pytest

from mri_dataset_tool.infrastructure.bids.entities import parse_bids_filename


def test_sub_ses_suffix():
    e = parse_bids_filename("sub-001_ses-01_T1w.nii.gz")
    assert (e.sub, e.ses, e.suffix, e.extension, e.other) == ("001", "01", "T1w", ".nii.gz", {})


def test_other_entities_keep_order():
    e = parse_bids_filename("sub-01_acq-mprage_run-2_T1w.nii")
    assert e.ses is None and e.extension == ".nii"
    assert list(e.other.items()) == [("acq", "mprage"), ("run", "2")]


def test_task_bold():
    e = parse_bids_filename("sub-01_task-rest_bold.nii.gz")
    assert e.other == {"task": "rest"} and e.suffix == "bold"


@pytest.mark.parametrize(
    "name",
    [
        "T1w.nii.gz",
        "ses-01_T1w.nii.gz",
        "sub-01_ses-01_acq_T1w.nii",  # entity without value
        "sub-_T1w.nii",
        "sub-01_ses-01_ses-02_T1w.nii",
        "sub-01_a-b-c_T1w.nii",
        "sub-01_ses-01.nii",  # no suffix
        "sub-01/ses-01_T1w.nii",
        "",
    ],
)
def test_invalid_names(name):
    with pytest.raises(ValueError):
        parse_bids_filename(name)

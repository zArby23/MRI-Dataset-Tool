"""C5: ``labels template|review|apply|finalize|reopen`` over a dataset built by the CLI; no ids printed."""

import json

import pytest

from mri_dataset_tool.presentation.cli.main import main
from test_cli_dataset import bids_input, build, clean, cli_env, corrections  # noqa: F401 (cli_env: autouse fixture)


@pytest.fixture
def dataset(tmp_path, capsys):
    bids_input(tmp_path / "in")
    assert build(tmp_path) == 0  # no classes: no label files yet
    capsys.readouterr()
    return str(tmp_path / "out" / "dataset")


def test_full_label_cycle(tmp_path, dataset, capsys):
    assert main(["labels", "template", dataset, "--classes", "AD=Alzheimer", "CN"]) == 0
    assert "Label template written (2 classes)." in capsys.readouterr().out

    assert main(["labels", "review", dataset]) == 0
    out = capsys.readouterr().out
    assert "Pairs: 2  labeled: 0" in out and "Defects: {'UNLABELED': 2}" in out and "Complete: no" in out

    fix = corrections(tmp_path / "fix.tsv", [("PATIENT01", "AD"), ("PATIENT02", "CN")])
    assert main(["labels", "apply", dataset, "--corrections", str(fix)]) == 0
    assert "Label corrections applied: 2" in capsys.readouterr().out

    assert main(["labels", "review", dataset, "--json"]) == 0
    review = json.loads(capsys.readouterr().out)
    assert review == {"class_counts": {"AD": 1, "CN": 1}, "complete": True, "dataset_pairs": 2, "defects": {},
                      "labeled": 2}

    assert main(["labels", "finalize", dataset]) == 0
    assert main(["labels", "finalize", dataset]) == 1  # already finalized
    assert main(["labels", "apply", dataset, "--corrections", str(fix)]) == 1  # finalized: no corrections
    assert main(["labels", "reopen", dataset]) == 0
    assert main(["labels", "reopen", dataset]) == 1  # not finalized
    out = capsys.readouterr().out
    assert "Labels finalized." in out and "Labels finalize failed: FileExistsError" in out
    assert "Labels apply failed: ValueError" in out and "Labels reopened." in out
    assert "Labels reopen failed: ValueError" in out
    assert clean(out, tmp_path)


def test_service_errors_exit_one_with_type_only(tmp_path, dataset, capsys):
    assert main(["labels", "review", dataset]) == 1  # no label files yet
    assert main(["labels", "template", dataset, "--classes", "AD"]) == 0
    assert main(["labels", "template", dataset, "--classes", "AD"]) == 1  # never overwritten
    assert main(["labels", "finalize", dataset]) == 1  # incomplete
    out = capsys.readouterr().out
    assert "Labels review failed: FileNotFoundError" in out and "Labels template failed: FileExistsError" in out
    assert "Labels finalize failed: ValueError" in out and clean(out, tmp_path)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["labels", "review", "missing"], "Dataset directory not found."),
        (["labels", "template", "{ds}", "--classes", "A", "A"], "Invalid --classes."),
        (["labels", "template", "{ds}", "--classes", "=x"], "Invalid --classes."),
        (["labels", "apply", "{ds}", "--corrections", "none.tsv"], "Corrections file not found."),
    ],
)
def test_validation_exits_two_before_writing(tmp_path, dataset, capsys, argv, message):
    before = sorted(tmp_path.rglob("*"))
    assert main([arg.format(ds=dataset) for arg in argv]) == 2
    assert message in capsys.readouterr().out
    assert sorted(tmp_path.rglob("*")) == before


def test_missing_action_exits_two(dataset):
    assert main(["labels", dataset]) == 2


@pytest.mark.parametrize("argv", [["labels", "template", "{src}", "--classes", "A"], ["labels", "review", "{src}"],
                                  ["dataset", "export-ml", "{src}", "--allow-unfinalized"], ["dataset", "report", "{src}", "rep"]])
def test_a_raw_input_is_not_a_dataset(tmp_path, capsys, argv):
    source = bids_input(tmp_path / "in")
    before = sorted(tmp_path.rglob("*"))
    assert main([arg.format(src=source) for arg in argv]) == 2
    assert "Not a dataset exported by this tool." in capsys.readouterr().out
    assert sorted(tmp_path.rglob("*")) == before


def test_review_json_errors_go_to_stderr(tmp_path, capsys):
    assert main(["labels", "review", str(bids_input(tmp_path / "in")), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "Not a dataset exported by this tool." in captured.err

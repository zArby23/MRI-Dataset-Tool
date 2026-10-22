from collections import Counter

import pytest

from mri_dataset_tool.infrastructure.dataset.splits import SPLITS, assign_splits, participant_strata


def _ids(n: int, prefix: str = "p") -> list[str]:
    return [f"{prefix}{i:03d}" for i in range(n)]


def test_defaults_give_70_15_15_and_are_deterministic() -> None:
    strata = {p: () for p in _ids(100)}
    assignment, warnings = assign_splits(strata)
    assert Counter(assignment.values()) == {"training": 70, "validation": 15, "testing": 15}
    assert warnings == []
    assert assign_splits(strata) == (assignment, warnings)
    assert assign_splits(dict(reversed(strata.items()))) == (assignment, warnings)  # input order is irrelevant
    assert assign_splits(strata, seed=1)[0] != assignment
    assert list(assignment) == sorted(assignment)


def test_every_participant_gets_exactly_one_split() -> None:
    strata = {p: () for p in _ids(17)}
    assignment, _ = assign_splits(strata, (0.5, 0.25, 0.25), 3)
    assert set(assignment) == set(strata) and set(assignment.values()) <= set(SPLITS)


def test_stratified_each_class_in_each_split() -> None:
    strata = {p: ("AD",) for p in _ids(4, "a")} | {p: ("CN",) for p in _ids(10, "c")} | {p: ("AD", "CN") for p in _ids(3, "m")}
    assignment, warnings = assign_splits(strata)
    for stratum in {("AD",), ("CN",), ("AD", "CN")}:
        splits = Counter(assignment[p] for p, s in strata.items() if s == stratum)
        assert set(splits) == set(SPLITS)
    assert Counter(assignment[p] for p in _ids(10, "c")) == {"training": 7, "validation": 2, "testing": 1}
    assert warnings == []


def test_small_stratum_is_a_warning_not_an_error() -> None:
    strata = {"a1": ("AD",), "a2": ("AD",)} | {p: ("CN",) for p in _ids(6)}
    assignment, warnings = assign_splits(strata)
    assert warnings == [{"code": "FEW_PARTICIPANTS", "stratum": ["AD"], "participants": 2}]
    assert assignment["a1"] == assignment["a2"] == "training"


def test_zero_ratio_split_stays_empty() -> None:
    assignment, warnings = assign_splits({p: () for p in _ids(10)}, (0.8, 0.0, 0.2))
    assert Counter(assignment.values()) == {"training": 8, "testing": 2}
    assert assign_splits({"x": ()}, [1, 0, 0]) == ({"x": "training"}, [])
    assert warnings == []


@pytest.mark.parametrize(
    "ratios",
    [(0.7, 0.2, 0.2), (0.7, 0.3), (1.2, -0.1, -0.1), (0.7, 0.15, float("nan")), (True, False, False), "0.7", None, (0.7, "0.15", 0.15)],
)
def test_invalid_ratios(ratios) -> None:
    with pytest.raises(ValueError, match=r"^Split ratios must be three non-negative numbers that sum to 1\.$"):
        assign_splits({"a": ()}, ratios)


@pytest.mark.parametrize("seed", [None, 1.0, "0", True])
def test_invalid_seed(seed) -> None:
    with pytest.raises(ValueError, match=r"^Split seed must be an integer\.$"):
        assign_splits({"a": ()}, seed=seed)


def test_no_participants() -> None:
    with pytest.raises(ValueError, match=r"^No participants to split\.$"):
        assign_splits({})


def test_strata_from_labels() -> None:
    sessions = [("a", "1"), ("a", "2"), ("b", "1"), ("c", None), ("d", "1"), ("d", "2")]
    labels = {("a", "1"): "CN", ("a", "2"): "AD", ("b", "1"): None, ("c", None): "CN", ("d", "2"): "AD", ("z", "1"): "AD"}
    strata, unlabeled = participant_strata(sessions, labels)
    assert strata == {"a": ("AD", "CN"), "c": ("CN",), "d": ("AD",)}
    assert unlabeled == ["b"]
    assert participant_strata(sessions, None) == ({"a": (), "b": (), "c": (), "d": ()}, [])

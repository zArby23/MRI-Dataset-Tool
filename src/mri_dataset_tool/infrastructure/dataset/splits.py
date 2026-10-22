"""Train/validation/test partitions by participant (RF13). Pure functions, no I/O.

All sessions of a participant land in the same split (no leakage). With labels, participants are
stratified by their *stratum*: the sorted tuple of distinct classes over their labelled sessions
(usually one class). Participants without any label are left out and listed apart.
"""

import math
import random
from collections.abc import Iterable, Mapping

SPLITS = ("training", "validation", "testing")
DEFAULT_RATIOS = (0.7, 0.15, 0.15)
DEFAULT_SEED = 0

Stratum = tuple[str, ...]


def participant_strata(
    sessions: Iterable[tuple[str, str | None]], labels: Mapping[tuple[str, str | None], str | None] | None
) -> tuple[dict[str, Stratum], list[str]]:
    """Return (participant -> stratum, unlabeled participants), both sorted by participant.

    Without *labels* every participant gets the empty stratum. With labels (``LabelTable.labels``),
    a participant whose sessions are all unlabeled (or absent from the table) is unlabeled.
    """
    classes: dict[str, set[str]] = {}
    for participant, session in sessions:
        found = classes.setdefault(participant, set())
        label = None if labels is None else labels.get((participant, session))
        if label is not None:
            found.add(label)
    strata = {p: tuple(sorted(c)) for p, c in sorted(classes.items()) if labels is None or c}
    unlabeled = [p for p in sorted(classes) if p not in strata]
    return strata, unlabeled


def assign_splits(
    strata: Mapping[str, Stratum],
    ratios: object = DEFAULT_RATIOS,
    seed: object = DEFAULT_SEED,
) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Assign each participant to a split; returns (participant -> split, warnings).

    Deterministic for a given (*strata*, *ratios*, *seed*). Each stratum is split on its own:
    when it has at least one participant per split with a positive ratio, every such split gets
    one; the rest goes, one at a time, to the split furthest below its quota (ties in
    ``SPLITS`` order). A smaller stratum gives a ``FEW_PARTICIPANTS`` warning (not an error).
    """
    weights = check_split_params(ratios, seed)
    if not strata:
        raise ValueError("No participants to split.")

    groups: dict[Stratum, list[str]] = {}
    for participant in sorted(strata):
        groups.setdefault(strata[participant], []).append(participant)

    rng = random.Random(seed)
    assignment: dict[str, str] = {}
    warnings: list[dict[str, object]] = []
    active = [i for i, weight in enumerate(weights) if weight > 0]
    for stratum in sorted(groups):
        members = groups[stratum]
        rng.shuffle(members)
        n = len(members)
        counts = [1 if i in active and n >= len(active) else 0 for i in range(len(SPLITS))]
        for _ in range(n - sum(counts)):
            target = max(active, key=lambda i: (n * weights[i] - counts[i], -i))
            counts[target] += 1
        start = 0
        for i, count in enumerate(counts):
            for participant in members[start : start + count]:
                assignment[participant] = SPLITS[i]
            start += count
        if n < len(active):
            warnings.append({"code": "FEW_PARTICIPANTS", "stratum": list(stratum), "participants": n})
    return dict(sorted(assignment.items())), warnings


def check_split_params(ratios: object, seed: object) -> tuple[float, ...]:
    """Validate *ratios* (three non-negative numbers summing to 1) and *seed* (``int``); return the ratios."""
    if type(seed) is not int:
        raise ValueError("Split seed must be an integer.")
    invalid = ValueError("Split ratios must be three non-negative numbers that sum to 1.")
    if not isinstance(ratios, (list, tuple)) or len(ratios) != len(SPLITS):
        raise invalid
    if not all(isinstance(r, (int, float)) and not isinstance(r, bool) and math.isfinite(r) and r >= 0 for r in ratios):
        raise invalid
    if not math.isclose(sum(ratios), 1.0, abs_tol=1e-9):
        raise invalid
    return tuple(float(r) for r in ratios)

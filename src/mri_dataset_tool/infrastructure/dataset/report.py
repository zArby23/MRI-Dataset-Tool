"""Dataset-level statistical summary (RF14) aggregated from per-study summaries.

The input is the output of ``summarize_study`` (already allow-listed), one study at a
time; subject/session ids are only used to count and are never written to the result.
"""

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

UNKNOWN_MODALITY = "unknown"
_DISTRIBUTION_KEYS = ("shape", "voxel_size", "orientation", "dtype")
_VOXEL_SIZE_DECIMALS = 6  # groups 0.9999999 and 1.0 as the same spacing

StudyEntry = tuple[str | None, str | None, Mapping[str, Any]]
Labels = Mapping[tuple[str, str | None], str | None]


def build_dataset_summary(
    entries: Iterable[StudyEntry], labels: Labels | None = None, classes: Iterable[str] | None = None
) -> dict[str, Any]:
    """Aggregate ``(subject_id, session_id, summarize_study(study))`` entries into a JSON-ready dict.

    Deterministic (sorted keys and lists), no NaN, no ids, paths or UIDs. *labels* maps
    ``(subject_id, session_id)`` (without ``sub-``/``ses-``) to a class; ``None`` or ``""``
    means unlabeled. *classes* (declared in ``labels.json``) appear even with zero sessions;
    a label outside them is counted and warned as ``UNKNOWN_CLASS``. Warnings are ``{"code", "count"}`` items only.
    """
    sessions: dict[tuple[str, str | None], int] = {}  # (subject, session) -> series count
    warnings: Counter[str] = Counter()
    modalities: dict[str, _ModalityStats] = {}
    studies = 0
    for subject_id, session_id, study_summary in entries:
        studies += 1
        series = study_summary.get("series", [])
        if subject_id is None:
            warnings["MISSING_SUBJECT_ID"] += 1
        else:
            key = (subject_id, session_id)
            sessions[key] = sessions.get(key, 0) + len(series)
        for series_summary in series:
            modality = series_summary.get("modality") or UNKNOWN_MODALITY
            modalities.setdefault(str(modality), _ModalityStats()).add(series_summary, warnings)
        del study_summary, series

    summary: dict[str, Any] = {
        "studies": studies,
        "participants": len({subject for subject, _ in sessions}),
        "sessions": len(sessions),
        "series": sum(stats.series for stats in modalities.values()),
        "modalities": {name: modalities[name].to_dict() for name in sorted(modalities)},
        "labels": None if labels is None else _label_summary(sessions, labels, classes, warnings),
    }
    summary["warnings"] = [{"code": code, "count": warnings[code]} for code in sorted(warnings)]
    return summary


class _ModalityStats:
    def __init__(self) -> None:
        self.series = 0
        self.distributions: dict[str, Counter[str]] = {key: Counter() for key in _DISTRIBUTION_KEYS}
        self.count, self.mean, self.m2 = 0, 0.0, 0.0
        self.low, self.high = math.inf, -math.inf
        self.non_finite = 0

    def add(self, series: Mapping[str, Any], warnings: Counter[str]) -> None:
        self.series += 1
        for key in _DISTRIBUTION_KEYS:
            value = series.get(key)
            if key == "voxel_size" and isinstance(value, list):
                value = [round(v, _VOXEL_SIZE_DECIMALS) if isinstance(v, float) else v for v in value]
            self.distributions[key][json.dumps(value)] += 1
        for code in (series.get("validation") or {}).get("findings", []):
            warnings[code] += 1
        intensity = series.get("intensity")
        if intensity is None:
            warnings["NO_VOLUME"] += 1
            return
        non_finite = intensity["non_finite_voxels"]
        if non_finite:
            warnings["NON_FINITE_VOXELS"] += 1
        self.non_finite += non_finite
        shape = series.get("shape")
        if intensity["mean"] is None:
            return
        if not isinstance(shape, list):
            warnings["MISSING_SHAPE"] += 1  # without a shape the voxel count is unknown: left out of intensity
            return
        n = math.prod(shape) - non_finite
        if n <= 0:
            return
        # Chan et al. parallel combination of (n, mean, M2), as in summarize_study.
        mean, m2 = intensity["mean"], intensity["std"] ** 2 * n
        delta = mean - self.mean
        total = self.count + n
        self.mean += delta * n / total
        self.m2 += m2 + delta**2 * self.count * n / total
        self.count = total
        self.low, self.high = min(self.low, intensity["min"]), max(self.high, intensity["max"])

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"series": self.series}
        for key, counter in self.distributions.items():
            # Most frequent first; ties by the value's JSON text, so the order is stable.
            ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
            result[key] = [{"value": json.loads(text), "count": count} for text, count in ranked]
        finite = self.count > 0
        result["intensity"] = {
            "min": self.low if finite else None,
            "max": self.high if finite else None,
            "mean": self.mean if finite else None,
            "std": math.sqrt(self.m2 / self.count) if finite else None,
            "finite_voxels": self.count,
            "non_finite_voxels": self.non_finite,
        }
        return result


def _label_summary(
    sessions: Mapping[tuple[str, str | None], int],
    labels: Labels,
    classes: Iterable[str] | None,
    warnings: Counter[str],
) -> dict[str, Any]:
    declared = None if classes is None else set(classes)
    by_class: dict[str, dict[str, Any]] = {
        name: {"participants": set(), "sessions": 0, "series": 0} for name in declared or ()
    }
    unlabeled: set[tuple[str, str | None]] = set()
    for key in sorted(sessions, key=lambda k: (k[0], k[1] or "")):
        label = labels.get(key)
        if not label:
            unlabeled.add(key)
            continue
        if declared is not None and label not in declared:
            warnings["UNKNOWN_CLASS"] += 1
        stats = by_class.setdefault(label, {"participants": set(), "sessions": 0, "series": 0})
        stats["participants"].add(key[0])
        stats["sessions"] += 1
        stats["series"] += sessions[key]
    if unlabeled:
        warnings["UNLABELED_SESSIONS"] += len(unlabeled)
    return {
        "classes": {
            name: {**by_class[name], "participants": len(by_class[name]["participants"])} for name in sorted(by_class)
        },
        "unlabeled_sessions": len(unlabeled),
        # A participant counts as unlabeled when any of its sessions is.
        "unlabeled_participants": len({subject for subject, _ in unlabeled}),
    }

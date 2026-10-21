"""Step ``anonymize`` (RF09): pseudonymize identifiers and filter metadata by allow list.

The volume is never read: a lazy volume stays lazy. Files are dropped because their paths
carry identifiers. The HMAC key is read from the environment when the step is built and is
never part of ``params``, ``repr`` or any output.
"""

import copy
from dataclasses import replace
from typing import Any, ClassVar

from mri_dataset_tool.application.pipeline.step import register_step
from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.anonymization.policy import (
    BIDS_ENTITY_WHITELIST,
    BIDS_KEPT_FIELDS,
    METADATA_WHITELIST,
    POLICY_VERSION,
    PROVENANCE_WHITELIST,
    SIDECAR_WHITELIST,
    filter_validation,
)
from mri_dataset_tool.infrastructure.anonymization.pseudonym import (
    load_key,
    pseudonymize_label,
    pseudonymize_uid,
)

_SCALARS = (str, int, float, bool)


@register_step("anonymize")
class AnonymizeStep:
    name: ClassVar[str] = "anonymize"
    version: ClassVar[str] = "1"
    # Contract C1: the runner records no source path for a pipeline with this step.
    redacts_sources: ClassVar[bool] = True

    def __init__(self, policy_version: str = POLICY_VERSION) -> None:
        if policy_version != POLICY_VERSION:
            raise ValueError("Unsupported anonymization policy version.")
        self._key = load_key()

    def __repr__(self) -> str:
        return f"AnonymizeStep(policy_version={POLICY_VERSION!r})"

    @property
    def params(self) -> dict[str, Any]:
        return {"policy_version": POLICY_VERSION}

    def apply(self, study: MRIStudy) -> MRIStudy:
        return replace(
            study,
            study_uid=self._uid(study.study_uid),
            subject_id=self._label(study.subject_id, "subject"),
            session_id=self._label(study.session_id, "session"),
            series=[self._series(series) for series in study.series],
        )

    def _uid(self, value: str | None) -> str | None:
        return None if value is None else pseudonymize_uid(value, self._key)

    def _label(self, value: str | None, kind: str) -> str | None:
        return None if value is None else pseudonymize_label(value, kind, self._key)

    def _series(self, series: MRISeries) -> MRISeries:
        # Deep copy (like replace_volume): editing the output in place must not change the input.
        metadata = copy.deepcopy({key: value for key, value in series.metadata.items() if key in METADATA_WHITELIST})
        if "sidecar" in metadata:
            metadata["sidecar"] = _filter_sidecar(metadata["sidecar"])
        if "bids" in metadata:
            metadata["bids"] = self._bids(metadata["bids"])
        if "provenance" in metadata:
            metadata["provenance"] = _filter_provenance(metadata["provenance"])
        if "validation" in metadata:
            metadata["validation"] = filter_validation(metadata["validation"])
        return replace(series, series_uid=self._uid(series.series_uid), files=[], metadata=metadata)

    def _bids(self, entities: Any) -> dict[str, Any]:
        if not isinstance(entities, dict):
            return {}
        result: dict[str, Any] = {
            key: value for key, value in entities.items() if key in BIDS_KEPT_FIELDS and isinstance(value, str)
        }
        for key, kind in (("sub", "subject"), ("ses", "session")):
            if isinstance(entities.get(key), str):
                result[key] = self._label(entities[key], kind)
        other = entities.get("other")
        if isinstance(other, dict):
            result["other"] = {
                key: value for key, value in other.items() if key in BIDS_ENTITY_WHITELIST and isinstance(value, str)
            }
        return result


def _filter_sidecar(sidecar: Any) -> dict[str, Any]:
    if not isinstance(sidecar, dict):
        return {}
    return {key: value for key, value in sidecar.items() if key in SIDECAR_WHITELIST and _is_plain(value)}


def _filter_provenance(provenance: Any) -> dict[str, str]:
    if not isinstance(provenance, dict):
        return {}
    return {key: value for key, value in provenance.items() if key in PROVENANCE_WHITELIST and isinstance(value, str)}


def _is_plain(value: Any) -> bool:
    if isinstance(value, list):
        return all(isinstance(item, _SCALARS) for item in value)
    return isinstance(value, _SCALARS)

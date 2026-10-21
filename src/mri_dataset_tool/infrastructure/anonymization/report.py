"""Audit report of a DICOM anonymization run: per tag, the action taken and how often.

It never holds element values, paths, UIDs or the key: only tag labels, action names and counts.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from pydicom.datadict import keyword_for_tag
from pydicom.tag import BaseTag

from mri_dataset_tool.infrastructure.anonymization.policy import POLICY_VERSION, Action


def tag_label(tag: BaseTag) -> str:
    """Keyword of a standard tag, ``"GGGG,EEEE"`` for private or unknown ones (a tag is not a value)."""
    return keyword_for_tag(tag) or f"{tag.group:04X},{tag.element:04X}"


@dataclass
class AnonymizationReport:
    policy_version: str = POLICY_VERSION
    files_written: int = 0
    files_failed: int = 0
    actions: dict[str, dict[str, int]] = field(default_factory=dict)  # tag label → action → count

    def record(self, tag: BaseTag, action: Action) -> None:
        counts = self.actions.setdefault(tag_label(tag), {})
        counts[action.value] = counts.get(action.value, 0) + 1

    def merge_actions(self, other: "AnonymizationReport") -> None:
        """Add the action counts of *other* (one written file) to this report."""
        for label, counts in other.actions.items():
            mine = self.actions.setdefault(label, {})
            for action, count in counts.items():
                mine[action] = mine.get(action, 0) + count

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "files_written": self.files_written,
            "files_failed": self.files_failed,
            "actions": {label: dict(sorted(counts.items())) for label, counts in sorted(self.actions.items())},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

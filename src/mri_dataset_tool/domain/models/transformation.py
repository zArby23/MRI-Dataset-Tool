import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class StepRecord:
    """What one processing step did to one study (RF15).

    ``params`` holds only JSON-serializable values. ``error_type`` is the exception
    type name when ``status == "failed"``; the exception message is never stored.
    ``outputs`` holds the values the step computed (JSON only, no PHI, paths or UIDs),
    stored in their JSON form (tuples become lists); a failed step has none.
    """

    name: str
    version: str
    params: dict[str, Any]
    status: Literal["ok", "failed"]
    error_type: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in ("ok", "failed"):
            raise ValueError("Step status must be 'ok' or 'failed'.")
        if (self.status == "failed") != (self.error_type is not None):
            raise ValueError("Step error_type must be set exactly when status is 'failed'.")
        if not isinstance(self.outputs, dict):
            raise ValueError("Step outputs must be a dict.")
        if self.status == "failed" and self.outputs:
            raise ValueError("Failed steps have no outputs.")
        try:
            outputs = json.loads(json.dumps(self.outputs, allow_nan=False))
        except (TypeError, ValueError):
            raise ValueError("Step outputs must be JSON-serializable.") from None  # the cause quotes the value
        object.__setattr__(self, "outputs", outputs)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["outputs"]:
            del data["outputs"]  # stage 2 manifests stay byte-identical
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StepRecord":
        return cls(**data)


@dataclass(frozen=True)
class StudyReport:
    """Steps applied to one study of a batch, in execution order.

    ``index`` is 1-based in the order of the input iterable. A failed step is the
    last record: the following steps do not run for that study.
    """

    index: int
    source_path: str | None
    steps: list[StepRecord]

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "source_path": self.source_path, "steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StudyReport":
        return cls(
            index=data["index"],
            source_path=data["source_path"],
            steps=[StepRecord.from_dict(step) for step in data["steps"]],
        )

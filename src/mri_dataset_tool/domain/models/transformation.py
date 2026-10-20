from dataclasses import asdict, dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class StepRecord:
    """What one processing step did to one study (RF15).

    ``params`` holds only JSON-serializable values. ``error_type`` is the exception
    type name when ``status == "failed"``; the exception message is never stored.
    """

    name: str
    version: str
    params: dict[str, Any]
    status: Literal["ok", "failed"]
    error_type: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ("ok", "failed"):
            raise ValueError("Step status must be 'ok' or 'failed'.")
        if (self.status == "failed") != (self.error_type is not None):
            raise ValueError("Step error_type must be set exactly when status is 'failed'.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

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
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StudyReport":
        return cls(
            index=data["index"],
            source_path=data["source_path"],
            steps=[StepRecord.from_dict(step) for step in data["steps"]],
        )

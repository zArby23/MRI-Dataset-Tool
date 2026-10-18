from dataclasses import dataclass

from mri_dataset_tool.domain.models.serie import MRISeries


@dataclass
class MRIStudy:
    study_uid: str | None
    series: list[MRISeries]
    subject_id: str | None = None
    session_id: str | None = None



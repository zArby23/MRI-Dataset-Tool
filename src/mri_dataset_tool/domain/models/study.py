from dataclasses import dataclass

from mri_dataset_tool.domain.models.serie import MRISeries


@dataclass
class MRIStudy:
    study_uid: str
    series: list[MRISeries]



from pathlib import Path
from typing import Any

import pydicom
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class DICOMReader:
    def load_study(self, directory: Path) -> MRIStudy:
        """
        Load a DICOM study from a directory.
        
        All valid DICOM files are read, grouped by StudyInstanceUID
        and SeriesInstanceUID, and converted into an MRIStudy object.
        """
        
        if not directory.exists():
            raise FileNotFoundError(
                f"Path doesn't exist: {directory}"
            )
        
        if not directory.is_dir():
            raise NotADirectoryError(
                f"Path is not a directory: {directory}"
            )
        
        logger.info("Loading DICOM study from %s", directory)
        
        datasets: list[tuple[Path, Dataset]] = []
        
        for file_path in directory.iterdir():
            
            if not file_path.is_file():
                continue
            
            try:
                dataset = pydicom.dcmread(file_path)
                
            except InvalidDicomError:
                logger.warning(
                    "file is not a valid DICOM file: %s",
                    file_path
                )
                continue
            
            datasets.append(
                (file_path, dataset)
            )
        
        if not datasets:
            raise ValueError(
                f"No DICOM files were found in directory: {directory}"
            )
            
        logger.info(
            "Found %d valid DICOM files", len(datasets)
        )
        
        study_uids = {
            dataset.get("StudyInstanceUID")
            for _, dataset in datasets
        }
        
        study_uids.discard(None)
        
        if len(study_uids) > 1:
            raise ValueError(
                f"Multiple studies found in directory: {directory}"
            )
        
        if not study_uids:
            raise ValueError(
                "No DICOM files with StudyInstanceUID were found."
            )

        study_uid = study_uids.pop()
        
        series_groups: dict[str, list[tuple[Path, Dataset]]] = {}
        
        for file_path, dataset in datasets:
            series_uid = dataset.get("SeriesInstanceUID")
            
            if series_uid is None:
                logger.warning(
                    "Skipping DICOM file without SeriesInstanceUID: %s",
                    file_path
                )
                continue
            
            series_groups.setdefault(
                series_uid,
                []
            ).append(
                (file_path, dataset)
            )
        
        if not series_groups:
            raise ValueError(
                "No valid DICOM series found."
            )
        
        series = []
        
        for series_uid, instances in series_groups.items():
            dataset = instances[0][1]
            
            modality = dataset.get(
                "Modality",
                "Unknown"
                )
            
            files = [
                file_path
                for file_path, _ in instances
            ]
            
            metadata = self._extract_series_metadata(
                dataset
            )
            
            series.append(
                MRISeries(
                    series_uid=series_uid,
                    modality=modality,
                    files=files,
                    metadata=metadata
                )
            )
            
            logger.info(
                "Loaded series %s with %d instances",
                series_uid,
                len(files)
            )
        
        return MRIStudy(
            study_uid=study_uid,
            series=series
        )
    
    def _extract_series_metadata(
        self,
        dataset: Dataset
        ) -> dict[str, Any]:
        """
        Extract metadata required by the application
        from a representative DICOM instance.
        """
        
        return {
            "rows": dataset.get("Rows"),
            "columns": dataset.get("Columns"),
            "pixel_spacing": dataset.get("PixelSpacing"),
            "slice_thickness": dataset.get("SliceThickness"),
            "spacing_between_slices": dataset.get("SpacingBetweenSlices"),
            "image_orientation": dataset.get("ImageOrientationPatient")
        }
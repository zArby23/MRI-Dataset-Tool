from pathlib import Path
from typing import Any

import nibabel as nib
from nibabel.filebasedimages import ImageFileError

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class NIfTIReader:
    def load_study(self, path: Path) -> MRIStudy:
        """Load one NIfTI image as a study containing one MRI series.

        NIfTI has no DICOM study or series UIDs, so those fields are ``None``.
        Processing such as normalization and reorientation remains elsewhere.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"NIfTI file does not exist. {path}"
            )
        if not path.is_file():
            raise ValueError(
                f"NIfTI path must identify a file. {path}"
            )
        if not self._is_nifti_file(path):
            raise ValueError(
                f"Unsupported NIfTI file extension. Expected .nii or .nii.gz. {path}"
            )

        logger.info("Loading NIfTI study")
        try:
            image = nib.load(path)
            volume = image.get_fdata()
        except (ImageFileError, OSError) as error:
            logger.error("Unable to load NIfTI image")
            raise ValueError("Unable to load NIfTI image.") from error

        series = MRISeries(
            files=[path],
            metadata=self._extract_series_metadata(image),
            volume=volume,
        )
        logger.info("Loaded NIfTI volume with shape %s", image.shape)
        return MRIStudy(study_uid=None, series=[series])

    def _is_nifti_file(self, path: Path) -> bool:
        """Return whether *path* uses a supported single-file NIfTI suffix."""
        return path.suffix == ".nii" or path.name.endswith(".nii.gz")

    def _extract_series_metadata(
        self,
        image: nib.spatialimages.SpatialImage,
    ) -> dict[str, Any]:
        """Extract NIfTI metadata needed by downstream MRI processing."""
        header = image.header
        return {
            "shape": image.shape,
            "voxel_size": header.get_zooms()[:3],
            "datatype": str(header.get_data_dtype()),
            "bitpix": int(header["bitpix"]),
            "affine": image.affine,
            "qform_code": int(header["qform_code"]),
            "sform_code": int(header["sform_code"]),
            "orientation": nib.aff2axcodes(image.affine),
        }

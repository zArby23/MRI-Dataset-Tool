import os
from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.spatialimages import HeaderDataError

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.logging.logger import get_logger
from mri_dataset_tool.infrastructure.nifti.reader import is_nifti_file

logger = get_logger(__name__)

# NIFTI_XFORM_SCANNER_ANAT: the affine maps voxels to scanner coordinates.
_SCANNER_XFORM_CODE = 1


class NIfTIWriter:
    def write(self, series: MRISeries, path: Path, overwrite: bool = False) -> Path:
        """Write ``series.volume`` with ``metadata["affine"]`` as one NIfTI file.

        Voxel size comes from the affine. The parent directory must already exist;
        nothing is created outside *path*.
        """
        if not is_nifti_file(path):
            raise ValueError("Unsupported NIfTI file extension. Expected .nii or .nii.gz.")
        if series.volume is None:
            raise ValueError("Series has no volume to write.")
        affine = series.get("affine")
        if affine is None:
            raise ValueError("Series metadata has no affine to write.")
        affine = np.asarray(affine, dtype=np.float64)
        if affine.shape != (4, 4):
            raise ValueError("Series affine must be a 4x4 matrix.")
        if path.exists() and not overwrite:
            raise FileExistsError("Output file already exists.")

        try:
            image = nib.Nifti1Image(series.volume, affine)
        except (TypeError, ValueError, HeaderDataError) as error:
            raise ValueError("Unsupported volume for NIfTI output.") from error
        image.set_sform(affine, code=_SCANNER_XFORM_CODE)
        image.set_qform(affine, code=_SCANNER_XFORM_CODE)

        # Atomic write: temp file in the same directory keeps the NIfTI suffix
        # (nibabel picks compression from it), so a failure never leaves a partial output.
        suffix = ".nii.gz" if path.name.lower().endswith(".nii.gz") else ".nii"
        tmp = path.with_name(f".{path.name}.tmp{suffix}")
        try:
            nib.save(image, tmp)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        logger.info("Wrote NIfTI volume with shape %s", image.shape)
        return path

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from pydicom.valuerep import format_number_as_ds

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.infrastructure.dicom.volume_builder import (
    IN_PLANE_TOLERANCE_MM,
    ras_to_lps,
)
from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"
_INT16_MIN, _INT16_MAX = -32768, 32767
# Tight enough to catch shear/tilt, loose enough for direction cosines rounded to ~6 decimals.
_ORTHOGONALITY_TOLERANCE = 1e-4

# Type-2 attributes written empty: the writer never carries identifiers.
_EMPTY_TYPE2 = (
    "PatientName", "PatientID", "PatientBirthDate", "PatientSex", "StudyDate", "StudyTime",
    "ReferringPhysicianName", "StudyID", "AccessionNumber", "PositionReferenceIndicator",
    "Manufacturer", "ContentDate", "ContentTime", "ScanOptions", "MRAcquisitionType", "EchoTime",
)


class DICOMWriter:
    """Write a 3D series volume as one MR Image Storage file per slice."""

    def write(self, series: MRISeries, output_dir: Path, overwrite: bool = False) -> list[Path]:
        """Write the series; nothing is written if validation or any slice write fails.

        Files are staged in a sibling directory and moved at the end. Existing files are never
        deleted: with ``overwrite=True`` only ``slice-NNNN.dcm`` files with the same names are
        replaced, and leftover ``slice-*.dcm`` from a longer previous series raise ``ValueError``.
        """
        volume, affine_lps = _validate(series)
        names = [f"slice-{k + 1:04d}.dcm" for k in range(volume.shape[2])]
        if output_dir.exists():
            if not output_dir.is_dir():
                raise NotADirectoryError("The output path is not a directory.")
            if not overwrite and any(output_dir.iterdir()):
                raise FileExistsError("The output directory is not empty.")
            if set(p.name for p in output_dir.glob("slice-*.dcm")) - set(names):
                raise ValueError("The output directory has slice files not covered by this series.")

        slope, intercept = _rescale_parameters(volume)
        stored = np.rint((volume - intercept) / slope).clip(_INT16_MIN, _INT16_MAX).astype(np.int16)

        study_uid, series_uid, frame_uid = generate_uid(), generate_uid(), generate_uid()
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        created_output_dir = not output_dir.exists()
        staging = Path(tempfile.mkdtemp(prefix=".dicomwriter-", dir=output_dir.parent))
        try:
            for k, name in enumerate(names):
                dataset = _slice_dataset(k, stored[:, :, k], affine_lps, slope, intercept,
                                         study_uid, series_uid, frame_uid)
                dataset.save_as(staging / name, enforce_file_format=True)
            output_dir.mkdir(exist_ok=True)
            for name in names:
                os.replace(staging / name, output_dir / name)
        except BaseException:
            if created_output_dir and output_dir.is_dir() and not any(output_dir.iterdir()):
                output_dir.rmdir()
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        logger.info("Wrote %d DICOM slices", len(names))
        return [output_dir / name for name in names]


def _validate(series: MRISeries) -> tuple[np.ndarray, np.ndarray]:
    if series.volume is None:
        raise ValueError("The series has no volume.")
    affine = series.metadata.get("affine")
    if affine is None or np.shape(affine) != (4, 4):
        raise ValueError("The series has no valid 4x4 affine.")
    volume = np.asarray(series.volume, dtype=np.float64)
    if volume.ndim != 3:
        # 3D only by design (docs/dicom/writer.md).
        raise ValueError("Only 3D volumes are supported.")
    if not np.isfinite(volume).all() or not np.isfinite(affine).all():
        raise ValueError("The volume or affine contains non-finite values.")

    affine_lps = ras_to_lps(np.asarray(affine, dtype=np.float64))
    axes = affine_lps[:3, :3]
    norms = np.linalg.norm(axes, axis=0)
    if (norms <= 0).any():
        raise ValueError("The affine has a zero-length axis.")
    unit = axes / norms
    if np.abs(unit.T @ unit - np.eye(3)).max() > _ORTHOGONALITY_TOLERANCE:
        raise ValueError("The affine axes are not orthogonal (sheared geometry is not supported).")
    # Same criterion as the volume builder: drift of the last slice origin off the normal.
    normal = np.cross(unit[:, 0], unit[:, 1])
    step = axes[:, 2]
    drift = (volume.shape[2] - 1) * (step - (step @ normal) * normal)
    if np.abs(drift).max() > IN_PLANE_TOLERANCE_MM:
        raise ValueError("The slice axis is tilted relative to the slice plane normal.")
    return volume, affine_lps


def _rescale_parameters(volume: np.ndarray) -> tuple[float, float]:
    """Slope/intercept mapping [min, max] onto the int16 range, as stored in the file."""
    low, high = float(volume.min()), float(volume.max())
    if _INT16_MIN <= low and high <= _INT16_MAX and np.array_equal(volume, np.rint(volume)):
        return 1.0, 0.0  # integer data that fits int16 is stored losslessly
    slope = (high - low) / (_INT16_MAX - _INT16_MIN) or 1.0
    # Round-trip through the DS text form so the encoder and the reader use identical values.
    slope = float(format_number_as_ds(slope))
    if slope <= 0:
        raise ValueError("The intensity range is too small to encode.")
    intercept = float(format_number_as_ds(low - _INT16_MIN * slope))
    return slope, intercept


def _slice_dataset(
    k: int,
    pixels: np.ndarray,
    affine_lps: np.ndarray,
    slope: float,
    intercept: float,
    study_uid: str,
    series_uid: str,
    frame_uid: str,
) -> FileDataset:
    column_step, row_step, slice_step = (affine_lps[:3, i] for i in range(3))
    position = affine_lps[:3, 3] + k * slice_step

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = MR_IMAGE_STORAGE
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    for name in _EMPTY_TYPE2:
        setattr(ds, name, "")
    ds.SOPClassUID = MR_IMAGE_STORAGE
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
    ds.FrameOfReferenceUID = frame_uid
    ds.Modality = "MR"
    ds.ImageType = ["DERIVED", "SECONDARY"]
    ds.SeriesNumber = 1
    ds.InstanceNumber = k + 1
    ds.ImageOrientationPatient = [
        format_number_as_ds(float(v))
        for v in (*(column_step / np.linalg.norm(column_step)),
                  *(row_step / np.linalg.norm(row_step)))
    ]
    ds.ImagePositionPatient = [format_number_as_ds(float(v)) for v in position]
    ds.PixelSpacing = [
        format_number_as_ds(float(np.linalg.norm(row_step))),
        format_number_as_ds(float(np.linalg.norm(column_step))),
    ]
    thickness = format_number_as_ds(float(np.linalg.norm(slice_step)))
    ds.SliceThickness = thickness
    ds.SpacingBetweenSlices = thickness
    ds.Rows, ds.Columns = pixels.shape[1], pixels.shape[0]
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.RescaleSlope = format_number_as_ds(slope)
    ds.RescaleIntercept = format_number_as_ds(intercept)
    ds.PixelData = np.ascontiguousarray(pixels.T).tobytes()  # (rows, columns), C order
    return ds

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import nibabel as nib

from mri_dataset_tool.domain.models.serie import MRISeries
from mri_dataset_tool.domain.models.study import MRIStudy
from mri_dataset_tool.infrastructure.dicom.batch_reader import DICOMBatchReader
from mri_dataset_tool.infrastructure.dicom.volume_builder import build_series_volume
from mri_dataset_tool.infrastructure.dicom.writer import DICOMWriter
from mri_dataset_tool.infrastructure.logging.logger import get_logger
from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader
from mri_dataset_tool.infrastructure.nifti.reader import NIfTIReader
from mri_dataset_tool.infrastructure.nifti.writer import NIfTIWriter

logger = get_logger(__name__)


def convert_dicom_to_nifti(
    input_dir: Path,
    output_dir: Path,
    on_error: Callable[[Path, Exception], None] | None = None,
) -> list[MRIStudy]:
    """Convert every DICOM series below *input_dir* to one ``.nii.gz`` in *output_dir*.

    Files are named ``study-<ix>_series-<ix>.nii.gz`` (1-based, in the deterministic
    order of ``DICOMBatchReader``), so names never carry patient data. Existing outputs
    are never overwritten and inputs are never modified. A series that fails to build
    or write is reported through ``on_error(first_file, error)`` and the rest continue.

    To keep memory bounded (RNF02) each volume is released right after it is written:
    the returned series have ``volume=None``, ``files=[written_path]``, the canonical
    geometry in ``metadata`` and the conversion parameters in ``metadata["provenance"]``.
    Studies where every series failed are omitted from the result.

    Known limits: unreadable DICOM files are skipped by ``DICOMBatchReader`` without
    ``on_error`` until T12; running again over the same *output_dir* raises
    ``FileExistsError`` per series (by design, there is no overwrite option).
    """
    if output_dir.resolve().is_relative_to(input_dir.resolve()):
        raise ValueError("Output directory must not be inside the input directory.")

    studies = DICOMBatchReader().load_studies(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    writer = NIfTIWriter()
    provenance = {
        "tool": "mri_dataset_tool.convert_dicom_to_nifti",
        "source_format": "DICOM",
        "target_format": "NIfTI",
        "nibabel_version": nib.__version__,
        "compression": "gzip",
    }
    converted: list[MRIStudy] = []
    errors_count = 0

    for study_ix, study in enumerate(studies, start=1):
        out_series: list[MRISeries] = []
        for series_ix, series in enumerate(study.series, start=1):
            built = None  # release the previous volume before building the next one
            target = output_dir / f"study-{study_ix:03d}_series-{series_ix:03d}.nii.gz"
            try:
                built = build_series_volume(series)
                writer.write(built, target)
            except Exception as error:  # per-series boundary: any failure must not stop the batch
                errors_count += 1
                logger.warning("Skipping series that failed to convert (%s)", type(error).__name__)
                _report(on_error, series.files[0] if series.files else input_dir, error)
                continue
            out_series.append(
                replace(
                    built,
                    files=[target],
                    volume=None,
                    metadata={**built.metadata, "provenance": dict(provenance)},
                )
            )
            del built
        if out_series:
            converted.append(replace(study, series=out_series))

    logger.info(
        "Converted %d series in %d studies. Errors: %d.",
        sum(len(s.series) for s in converted),
        len(converted),
        errors_count,
    )
    return converted


def convert_nifti_to_dicom(
    input_path: Path,
    output_dir: Path,
    on_error: Callable[[Path, Exception], None] | None = None,
) -> list[MRIStudy]:
    """Convert a ``.nii``/``.nii.gz`` file, or every one below a directory, to DICOM.

    Each input is written by ``DICOMWriter`` into ``output_dir/study-<ix>/`` (1-based, in
    the deterministic order of ``NIfTIBatchReader``; unreadable inputs also consume an
    index so names stay stable), so names never carry patient data. Inputs are never
    modified. A failing input (unreadable, 4D, non-orthogonal affine, existing output...)
    is reported through ``on_error(input_file, error)`` and the rest continue. For a
    missing *input_path* raises ``FileNotFoundError``. If no input can be loaded at all
    (a single unreadable file, or a directory without valid NIfTI) the failures are
    reported and ``ValueError("No valid NIfTI studies were found.")`` is raised. If some
    input loads but the writer rejects it (e.g. 4D), the error is reported and the result
    may be ``[]``, as in ``convert_dicom_to_nifti``.

    Each volume is released right after it is written: the returned series have
    ``volume=None``, ``files=[written slices]``, the NIfTI geometry in ``metadata`` and
    ``metadata["provenance"]``. Failed inputs are omitted from the result.
    """
    if not input_path.exists():
        raise FileNotFoundError("Input path does not exist.")
    if output_dir.resolve().is_relative_to(input_path.resolve()):
        raise ValueError("Output directory must not be inside the input path.")

    if input_path.is_dir():
        index = 0

        def count_failure(path: Path, error: Exception) -> None:
            nonlocal index
            index += 1
            _report(on_error, path, error)

        sources = NIfTIBatchReader().iter_studies(input_path, on_error=count_failure)
    else:
        try:
            sources = iter([NIfTIReader().load_study(input_path)])
        except Exception as error:
            logger.warning("Skipping NIfTI that failed to load (%s)", type(error).__name__)
            _report(on_error, input_path, error)
            raise ValueError("No valid NIfTI studies were found.") from error
        index = 0

    writer = DICOMWriter()
    provenance = {
        "tool": "mri_dataset_tool.convert_nifti_to_dicom",
        "source_format": "NIfTI",
        "target_format": "DICOM",
        "sop_class": "MR Image Storage",
        "image_type": r"DERIVED\SECONDARY",
    }
    converted: list[MRIStudy] = []
    errors_count = 0

    for study in sources:
        index += 1
        series = study.series[0]
        try:
            files = writer.write(series, output_dir / f"study-{index:03d}")
        except Exception as error:  # per-input boundary: any failure must not stop the batch
            errors_count += 1
            logger.warning("Skipping NIfTI that failed to convert (%s)", type(error).__name__)
            _report(on_error, series.files[0], error)
            continue
        out = replace(
            series,
            files=files,
            volume=None,
            metadata={**series.metadata, "provenance": dict(provenance)},
        )
        converted.append(replace(study, series=[out]))
        del series, study

    logger.info("Converted %d NIfTI inputs. Write errors: %d.", len(converted), errors_count)
    return converted


def _report(
    on_error: Callable[[Path, Exception], None] | None, path: Path, error: Exception
) -> None:
    if on_error is None:
        return
    try:
        on_error(path, error)
    except Exception as callback_error:
        logger.warning("on_error callback failed (%s)", type(callback_error).__name__)

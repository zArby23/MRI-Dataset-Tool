"""Anonymization policy as data (RF09, RNF07): allow lists plus a DICOM tag → action table.

Everything is an allow list: a key or tag not listed here is discarded. Any change to this
file that changes an anonymized result must bump ``POLICY_VERSION``. Rationale per group is in
``docs/anonymization/policy.md``.
"""

from enum import StrEnum

POLICY_VERSION = "1"


class Action(StrEnum):
    REMOVED = "removed"
    EMPTIED = "emptied"
    REPLACED = "replaced"
    GENERALIZED = "generalized"
    KEPT = "kept"


# --- Domain model (MRISeries.metadata) -------------------------------------------------------

# Geometry and array description written by the readers and the processing steps.
GEOMETRY_METADATA_KEYS = frozenset({
    "shape", "voxel_size", "affine", "orientation",
    "datatype", "bitpix", "qform_code", "sform_code",
    "rows", "columns", "pixel_spacing", "slice_thickness", "spacing_between_slices", "image_orientation",
})
# Written by this tool with fixed values or constant codes, never header values.
TOOL_METADATA_KEYS = frozenset({"provenance", "validation"})
# Filtered key by key with the allow lists below.
FILTERED_METADATA_KEYS = frozenset({"sidecar", "bids"})

METADATA_WHITELIST = GEOMETRY_METADATA_KEYS | TOOL_METADATA_KEYS | FILTERED_METADATA_KEYS

# BIDS sidecar: technical acquisition parameters only. A kept key keeps only a scalar
# (str, int, float, bool) or a list of scalars; any other value is discarded.
SIDECAR_WHITELIST = frozenset({
    # Scanner hardware (class of device, not the device itself).
    "Manufacturer", "ManufacturersModelName", "MagneticFieldStrength",
    # Sequence.
    "MRAcquisitionType", "ScanningSequence", "SequenceVariant", "ScanOptions", "SequenceName",
    "PulseSequenceType",
    # Timing, relative to the acquisition (seconds), never clock time.
    "RepetitionTime", "EchoTime", "InversionTime", "SliceTiming", "EffectiveEchoSpacing",
    "TotalReadoutTime", "EchoTrainLength",
    # Encoding and geometry.
    "FlipAngle", "SliceThickness", "SliceEncodingDirection", "PhaseEncodingDirection",
    "ParallelReductionFactorInPlane", "PartialFourier", "MultibandAccelerationFactor", "PixelBandwidth",
})

# BIDS entities: sub/ses are pseudonymized; of the others only the acquisition entities of the
# BIDS MRI specification are kept.
BIDS_KEPT_FIELDS = frozenset({"suffix", "extension"})
BIDS_ENTITY_WHITELIST = frozenset({
    "task", "acq", "ce", "rec", "dir", "run", "echo", "flip", "inv", "mt", "part", "chunk",
})

# --- DICOM files (used by A2) ----------------------------------------------------------------

# Keyword → action. Any element not listed (private elements, unlisted sequences included) is
# removed. "generalized" depends on the VR: DA → YYYY0101, DT → YYYY, AS → lower bound of a
# 10-year range (>= 90 → 090Y; D/W/M converted to years first; < 1 year → 000Y).
DICOM_ACTIONS: dict[str, Action] = {
    # Identifiers: deterministic HMAC pseudonyms.
    "StudyInstanceUID": Action.REPLACED,
    "SeriesInstanceUID": Action.REPLACED,
    "SOPInstanceUID": Action.REPLACED,
    "MediaStorageSOPInstanceUID": Action.REPLACED,
    "FrameOfReferenceUID": Action.REPLACED,
    "PatientID": Action.REPLACED,
    # Type 2 attributes that must exist but carry identity or clock time.
    "PatientName": Action.EMPTIED,
    "ReferringPhysicianName": Action.EMPTIED,
    "StudyID": Action.EMPTIED,
    "AccessionNumber": Action.EMPTIED,
    "StudyTime": Action.EMPTIED,
    # Dates keep only the year; age keeps only its 10-year range.
    "PatientBirthDate": Action.GENERALIZED,
    "StudyDate": Action.GENERALIZED,
    "SeriesDate": Action.GENERALIZED,
    "AcquisitionDate": Action.GENERALIZED,
    "ContentDate": Action.GENERALIZED,
    "AcquisitionDateTime": Action.GENERALIZED,
    "PatientAge": Action.GENERALIZED,
    # Kept by decision of the human.
    "PatientSex": Action.KEPT,
    # Encoding and object type.
    "SpecificCharacterSet": Action.KEPT,
    "SOPClassUID": Action.KEPT,
    "MediaStorageSOPClassUID": Action.KEPT,
    "TransferSyntaxUID": Action.KEPT,
    "Modality": Action.KEPT,
    "ImageType": Action.KEPT,
    # Image pixel module and geometry (needed by build_series_volume).
    "Rows": Action.KEPT,
    "Columns": Action.KEPT,
    "SamplesPerPixel": Action.KEPT,
    "PhotometricInterpretation": Action.KEPT,
    "BitsAllocated": Action.KEPT,
    "BitsStored": Action.KEPT,
    "HighBit": Action.KEPT,
    "PixelRepresentation": Action.KEPT,
    "PixelData": Action.KEPT,
    "RescaleSlope": Action.KEPT,
    "RescaleIntercept": Action.KEPT,
    "RescaleType": Action.KEPT,
    "WindowCenter": Action.KEPT,
    "WindowWidth": Action.KEPT,
    "PixelSpacing": Action.KEPT,
    "SliceThickness": Action.KEPT,
    "SpacingBetweenSlices": Action.KEPT,
    "ImageOrientationPatient": Action.KEPT,
    "ImagePositionPatient": Action.KEPT,
    "SliceLocation": Action.KEPT,
    "PatientPosition": Action.KEPT,
    "SeriesNumber": Action.KEPT,
    "InstanceNumber": Action.KEPT,
    "AcquisitionNumber": Action.KEPT,
    "TemporalPositionIdentifier": Action.KEPT,
    "NumberOfTemporalPositions": Action.KEPT,
    # Technical acquisition parameters (same groups as SIDECAR_WHITELIST).
    "Manufacturer": Action.KEPT,
    "ManufacturerModelName": Action.KEPT,
    "MagneticFieldStrength": Action.KEPT,
    "MRAcquisitionType": Action.KEPT,
    "ScanningSequence": Action.KEPT,
    "SequenceVariant": Action.KEPT,
    "ScanOptions": Action.KEPT,
    "SequenceName": Action.KEPT,
    "RepetitionTime": Action.KEPT,
    "EchoTime": Action.KEPT,
    "InversionTime": Action.KEPT,
    "EchoTrainLength": Action.KEPT,
    "FlipAngle": Action.KEPT,
    "PixelBandwidth": Action.KEPT,
}
DICOM_DEFAULT_ACTION = Action.REMOVED

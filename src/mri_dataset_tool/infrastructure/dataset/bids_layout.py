"""Pure BIDS naming rules for the exported dataset (RF10). No I/O.

Supported suffixes and their datatype folder are listed in ``SUFFIX_DATATYPES``. To support a new
suffix, add it there with its BIDS datatype; only suffixes whose file name needs no entity other
than ``sub``/``ses`` belong here (``bold`` needs ``task-`` and is therefore not supported). A suffix
outside the map is rejected, never guessed from free text (Q2).
"""

import re
from pathlib import PurePosixPath

SUFFIX_DATATYPES: dict[str, str] = {
    "T1w": "anat",
    "T2w": "anat",
    "PDw": "anat",
    "T2starw": "anat",
    "FLAIR": "anat",
    "dwi": "dwi",
    "magnitude1": "fmap",
    "magnitude2": "fmap",
    "phasediff": "fmap",
}

EXTENSIONS: frozenset[str] = frozenset({".nii.gz", ".json"})

_LABEL = re.compile(r"[A-Za-z0-9]+")


def validate_label(label: object) -> str:
    """Return ``label`` if it is a valid BIDS ``sub``/``ses`` label (ASCII alphanumeric, non-empty)."""
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise ValueError("Invalid BIDS label.")
    return label


def datatype_for(suffix: object) -> str:
    """Return the BIDS datatype folder (``anat``, ``dwi``, ``fmap``) for a supported suffix."""
    if not isinstance(suffix, str) or suffix not in SUFFIX_DATATYPES:
        raise ValueError("Unsupported BIDS suffix.")
    return SUFFIX_DATATYPES[suffix]


def bids_path(
    subject: object,
    session: object,
    suffix: object,
    extension: str = ".nii.gz",
    run: object = None,
) -> PurePosixPath:
    """Relative path ``sub-<s>[/ses-<t>]/<datatype>/sub-<s>[_ses-<t>][_run-<n>]_<suffix><ext>``.

    ``session=None`` omits the session level; any other session must be a valid label.
    ``run=None`` omits the run entity; otherwise it must be a positive ``int`` (written unpadded).
    """
    sub = validate_label(subject)
    ses = None if session is None else validate_label(session)
    datatype = datatype_for(suffix)
    if extension not in EXTENSIONS:
        raise ValueError("Unsupported BIDS extension.")
    # bool is an int subclass: reject it explicitly.
    if run is not None and (type(run) is not int or run < 1):
        raise ValueError("Invalid BIDS run.")
    entities = f"sub-{sub}" if ses is None else f"sub-{sub}_ses-{ses}"
    if run is not None:
        entities += f"_run-{run}"
    folder = PurePosixPath(f"sub-{sub}") if ses is None else PurePosixPath(f"sub-{sub}", f"ses-{ses}")
    return folder / datatype / f"{entities}_{suffix}{extension}"

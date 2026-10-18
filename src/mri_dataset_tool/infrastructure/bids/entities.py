import re
from dataclasses import dataclass, field

_LABEL = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class BIDSEntities:
    sub: str
    suffix: str
    extension: str
    ses: str | None = None
    # Entities other than sub/ses, in order of appearance.
    other: dict[str, str] = field(default_factory=dict)


def parse_bids_filename(name: str) -> BIDSEntities:
    """Parse a BIDS file name (not a path), e.g. ``sub-01_ses-01_T1w.nii.gz``."""
    stem, dot, ext = name.partition(".")
    extension = dot + ext
    *entity_parts, suffix = stem.split("_")
    if not _LABEL.fullmatch(suffix) or not entity_parts:
        raise ValueError("Invalid BIDS file name: missing entities or suffix.")

    found: dict[str, str] = {}
    for part in entity_parts:
        key, sep, value = part.partition("-")
        if not sep or not _LABEL.fullmatch(key) or not _LABEL.fullmatch(value):
            raise ValueError("Invalid BIDS file name: malformed entity.")
        if key in found:
            raise ValueError("Invalid BIDS file name: repeated entity.")
        found[key] = value

    if "sub" not in found or next(iter(found)) != "sub":
        raise ValueError("Invalid BIDS file name: 'sub-' entity must come first.")
    sub = found.pop("sub")
    ses = found.pop("ses", None)
    return BIDSEntities(sub=sub, suffix=suffix, extension=extension, ses=ses, other=found)

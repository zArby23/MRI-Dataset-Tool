"""Conservative BIDS suffix rules for series that carry no BIDS name (DICOM, loose NIfTI).

A closed list: a series is mapped only when exactly one suffix matches its text (DICOM
SeriesDescription/ProtocolName, or a NIfTI file name) and no exclusion word appears. Anything else
is left unmapped; nothing is guessed. The texts are only read here, never returned or logged.
Rules and examples: ``docs/dataset/ingest.md``.
"""

import re

MATCHED, NO_MATCH, AMBIGUOUS, EXCLUDED = "MATCHED", "NO_MATCH", "AMBIGUOUS", "EXCLUDED"

# Words whose series cannot be told apart safely, so they are never mapped: localizers, derived
# maps and reformats, contrast-enhanced and subtraction images, dark-fluid/STIR (FLAIR-like) and gradient-echo
# (T2*-like) sequences named "T2", quantitative maps, dynamic/perfusion, angiography, functional and multi-image ones.
EXCLUDED_WORDS = frozenset({
    "localizer", "localiser", "scout", "survey", "loc",
    "adc", "fa", "trace", "tracew", "colfa", "exp", "tensor", "dixon", "mpr", "mip", "reformat", "reformatted",
    "subtraction", "nd", "desc", "preproc",
    "c", "km", "mdc", "ce",
    "dark", "darkfluid", "tirm", "stir",
    "gre", "ffe", "fl2d", "fl3d", "medic", "merge",
    "map", "mapping", "relaxometry", "molli", "dyn", "dynamic", "perf", "twist",
    "perfusion", "dsc", "dce", "asl", "swi", "mra", "tof",
    "bold", "fmri", "rest", "resting",
    "mp2rage", "inv1", "inv2", "uni",
})
# Contrast markers excluded also inside a word ("postGd", "postcontrast", "gadolinium").
EXCLUDED_PARTS = ("post", "gd", "gad", "contrast")

SUFFIX_WORDS = {
    "FLAIR": frozenset({"flair"}),
    "T2starw": frozenset({"t2star"}),
    "T2w": frozenset({"t2", "t2w"}),
    "T1w": frozenset({"t1", "t1w", "mprage", "bravo", "spgr"}),
    "PDw": frozenset({"pd", "pdw"}),
    "dwi": frozenset({"dwi", "dti", "diffusion", "dmri", "diff"}),
}

_WORD = re.compile(r"[a-z0-9]+")
_T2_STAR = re.compile(r"t2\s*\*|t2[\s_-]*star")  # "t2*", "T2 STAR", "T2_STAR"
_DARK_FLUID = re.compile(r"(?<![a-z0-9])da[-_]?fl(?![a-z0-9])")  # Siemens SPACE dark-fluid, "da-fl"


def suffix_from_text(*texts: str | None, exclude_sub: bool = False) -> tuple[str | None, str]:
    """``(suffix, MATCHED)`` or ``(None, NO_MATCH | AMBIGUOUS | EXCLUDED)`` for the joined *texts*.

    *exclude_sub*: the word ``sub`` marks a subtraction image (DICOM descriptions); it stays allowed
    for NIfTI file names, where ``sub-01_...`` is the BIDS subject entity."""
    text = " ".join(t for t in texts if t).lower()
    words = set(_WORD.findall(text))
    if (
        words & EXCLUDED_WORDS
        or any(part in word for word in words for part in EXCLUDED_PARTS)
        or (exclude_sub and "sub" in words)
        or _DARK_FLUID.search(text)
    ):
        return None, EXCLUDED
    found = {suffix for suffix, keys in SUFFIX_WORDS.items() if words & keys}
    if _T2_STAR.search(text):
        found.add("T2starw")
    if {"proton", "density"} <= words:
        found.add("PDw")
    if found & {"FLAIR", "T2starw"}:
        found.discard("T2w")  # "T2 FLAIR" is FLAIR; "t2*" also yields the word "t2"
    if len(found) == 1:
        return found.pop(), MATCHED
    return None, AMBIGUOUS if found else NO_MATCH

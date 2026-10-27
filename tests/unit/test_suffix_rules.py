"""Closed-list BIDS suffix rules: one case per rule, plus the ambiguous, excluded and unknown ones."""

import pytest

from mri_dataset_tool.infrastructure.dataset.suffix_rules import (
    AMBIGUOUS,
    EXCLUDED,
    MATCHED,
    NO_MATCH,
    suffix_from_text,
)


@pytest.mark.parametrize(
    ("texts", "suffix"),
    [
        (("T1_MPRAGE_SAG",), "T1w"),
        (("t1w 3d",), "T1w"),
        (("Sag BRAVO",), "T1w"),
        (("3D SPGR",), "T1w"),
        (("T2 TSE axial",), "T2w"),
        (("sub-01_T2w",), "T2w"),
        (("t2_flair_tra",), "FLAIR"),
        (("FLAIR",), "FLAIR"),
        (("T2*",), "T2starw"),
        (("T2 * axial",), "T2starw"),
        (("t2star",), "T2starw"),
        (("PD TSE",), "PDw"),
        (("proton density",), "PDw"),
        (("ep2d_diff_mddw_30",), "dwi"),
        (("DTI 64 dir",), "dwi"),
        (("Diffusion",), "dwi"),
        (("", "t1 sag", None), "T1w"),  # empty and missing texts are ignored
    ],
)
def test_each_rule(texts, suffix):
    assert suffix_from_text(*texts) == (suffix, MATCHED)


@pytest.mark.parametrize(
    "text",
    [
        "localizer", "AAHead_Scout", "ep2d_diff_ADC", "dti FA", "DWI TRACEW", "T1 post gd", "t1 MPR cor",
        "MP2RAGE UNI", "ep2d_bold_rest", "SWI", "TOF MRA", "perfusion DSC", "DCE", "sub-01_ce-gd_T1w",
        # contrast-enhanced
        "+C Ax T1", "T1 C+", "T1+C", "T1_MPRAGE_postGd", "T1 postcontrast", "t1_se_tra_KM", "T1 MDC", "T1 gadolinium",
        # dark-fluid (FLAIR-like) and gradient echo (T2*-like) named T2
        "t2_tse_dark-fluid_tra", "t2_tirm_tra_dark-fluid", "T2W_FFE", "Ax T2 GRE", "t2_fl2d_tra", "t2_fl3d",
        "T2 * GRE", "T2* GRE", "t2_medic", "T2 MERGE",
        # quantitative maps, dynamic and perfusion
        "T1 map", "T2 map", "T2_mapping", "T1_MOLLI", "t1_vibe_dyn", "T1 dynamic", "T1 perf", "t1_twist",
        # derived
        "ep2d_diff_TENSOR", "t1_vibe_dixon_W",
        # Siemens SPACE dark-fluid; reformats, non-distortion-corrected, relaxometry, STIR,
        # BIDS derivatives
        "t2_spc_da-fl_sag_p2_iso", "t2_spc_da_fl_irprep_sag_p2_iso", "Sag T1 Reformatted", "t1_mprage_sag_ND",
        "T2 relaxometry", "Cor T2 STIR", "sub-01_space-MNI_desc-preproc_T1w",
    ],
)
def test_excluded_words_are_never_mapped(text):
    assert suffix_from_text(text) == (None, EXCLUDED)


@pytest.mark.parametrize("text", ["PD T2 dual echo", "PD_T2", "t1 t2 combined", "dwi t1", "Sag T1 FLAIR"])
def test_ambiguous_texts_are_not_guessed(text):
    assert suffix_from_text(text) == (None, AMBIGUOUS)


@pytest.mark.parametrize("text", ["", "Brain tumour follow-up", "t1map", "magnitude", "phasediff", "scan 3"])
def test_unknown_texts_are_unmapped(text):
    assert suffix_from_text(text) == (None, NO_MATCH)


def test_sub_is_a_subtraction_only_when_asked():
    assert suffix_from_text("T1_SUB", exclude_sub=True) == (None, EXCLUDED)
    assert suffix_from_text("t1_mprage_sag_SUB", exclude_sub=True) == (None, EXCLUDED)
    assert suffix_from_text("sub-01_T1w") == ("T1w", MATCHED)  # NIfTI names: the BIDS subject entity


@pytest.mark.parametrize("text", ["T2_STAR_HEMO", "Ax T2 Star", "T2 STAR", "t2-star"])
def test_t2_star_in_two_words_is_t2starw(text):
    assert suffix_from_text(text, exclude_sub=True) == ("T2starw", MATCHED)


@pytest.mark.parametrize("text", ["t2_spc_sag_p2_iso", "T2 SPACE sag", "sub-01_ses-1_T1w", "Sag CUBE T2"])
def test_qa6_exclusions_do_not_catch_plain_names(text):
    assert suffix_from_text(text)[1] == MATCHED

"""Stage 5D integration: the GUI walk in a simulated portable build, and the build script.

A portable build is simulated with ``monkeypatch`` (``sys.frozen``, the unpacked folder in ``sys._MEIPASS``
with the bundled ``config/*.yaml``, no ``.py`` file next to ``inputs`` and a working directory without
``config/``): the controller must find the bundled config and write the same dataset as from source.
PyInstaller itself is never run here (the real bundle is checked by hand and by QA9).
"""

import getpass
import importlib.util
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

import test_stage5b_gui_integration as e7
from mri_dataset_tool.application.services import inputs
from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput
from mri_dataset_tool.application.services.inputs import check_input_paths, project_config_dir
from mri_dataset_tool.presentation.gui.controller import PRESET_NAME, Controller
from test_stage5_cli_integration import _tree
from test_stage5_ingest_integration import INPUT_MARKER, KEY, SECRETS, _bids_input, _dicom_input, _volumes

REPO = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO / "packaging" / "build_exe.py"


def _freeze(patch: pytest.MonkeyPatch, root: Path, with_config: bool = True) -> Path:
    """A portable build unpacked in *root*/bundle, run from the empty folder *root*/cwd."""
    bundle, cwd = root / "bundle", root / "cwd"
    (bundle / "config").mkdir(parents=True)
    cwd.mkdir()
    if with_config:
        for yaml in (REPO / "config").glob("*.yaml"):  # what build_exe.py bundles
            shutil.copy2(yaml, bundle / "config" / yaml.name)
    patch.setattr(sys, "frozen", True, raising=False)
    patch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    patch.setattr(inputs, "__file__", str(bundle / "mri_dataset_tool" / "inputs.pyc"))  # inside the PYZ
    patch.chdir(cwd)
    return bundle


@pytest.fixture(scope="module")
def walks(tmp_path_factory: pytest.TempPathFactory):
    """The BIDS walk (steps 1→4) from source and in a simulated portable build, with the same key."""
    tmp = tmp_path_factory.mktemp("e9")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MRI_ANON_KEY", KEY)
        source = _bids_input(tmp / INPUT_MARKER / "bids", _volumes(_dicom_input(tmp / INPUT_MARKER / "dicom")))
        inputs_before = _tree(tmp / INPUT_MARKER)
        e7._walk(e7._Session(), source, "bids", tmp / "from_source")
        with pytest.MonkeyPatch.context() as frozen:
            bundle = _freeze(frozen, tmp / "portable")
            bundle_before = _tree(bundle)
            session = e7._Session()  # created frozen: the default config path comes from the bundle
            default_config = session.controller.state.config_path
            frozen.setattr(e7, "CONFIG", default_config)
            e7._walk(session, source, "bids", tmp / "frozen")
            cwd_after = list((tmp / "portable" / "cwd").iterdir())
            bundle_after = _tree(bundle)
    return {
        "tmp": tmp, "session": session, "bundle": bundle, "default_config": default_config,
        "inputs_same": inputs_before == _tree(tmp / INPUT_MARKER), "bundle_same": bundle_before == bundle_after,
        "cwd_after": cwd_after,
    }


def test_the_frozen_walk_reads_the_bundled_config(walks) -> None:
    assert walks["default_config"] == walks["bundle"] / "config" / PRESET_NAME


def test_the_frozen_walk_writes_the_same_dataset_as_from_source(walks) -> None:
    source, frozen = walks["tmp"] / "from_source", walks["tmp"] / "frozen"
    names = lambda root: sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert names(frozen) == names(source) and "dataset/code/run_manifest.json" in names(source)
    for relative in names(source):
        # Creation times (manifest, label log) and the XLSX save date differ between two runs.
        if relative.removeprefix("dataset/") not in e7.TIMED and not relative.endswith(".xlsx"):
            assert (frozen / relative).read_bytes() == (source / relative).read_bytes(), relative
    manifest = lambda root: {key: value for key, value in json.loads(
        (root / "dataset" / "code" / "run_manifest.json").read_text(encoding="utf-8")).items() if key != "timestamps"}
    assert manifest(frozen) == manifest(source)
    assert "unknown" not in manifest(frozen)["versions"].values()


def test_the_frozen_walk_writes_only_in_the_chosen_output(walks) -> None:
    assert walks["inputs_same"] and walks["bundle_same"] and walks["cwd_after"] == []


def test_no_phi_or_bundle_path_in_the_frozen_texts_and_state(walks) -> None:
    session, bundle = walks["session"], walks["bundle"]
    shown = "\n".join(session.texts + session.states)
    for secret in [*SECRETS, str(bundle), bundle.as_posix()]:
        assert secret not in shown, secret


def test_a_frozen_build_without_its_config_stops_at_step_one(tmp_path, monkeypatch) -> None:
    _freeze(monkeypatch, tmp_path, with_config=False)
    (tmp_path / "in").mkdir()
    output = tmp_path / "out"
    assert project_config_dir() == Path("config")  # the working directory's, which has none
    with pytest.raises(InvalidBuildInput, match="^Config file not found.$"):
        check_input_paths(tmp_path / "in", output)
    check = Controller().set_input(str(tmp_path / "in"), "bids", str(output))
    assert check.code == "CONFIG_NOT_FOUND" and not output.exists()


# --- packaging/build_exe.py (PyInstaller is replaced: nothing is compiled) ---

def _build_script(monkeypatch):
    pyinstaller = pytest.importorskip("PyInstaller.__main__")
    if sys.platform != "win32":
        pytest.skip("the portable build is Windows only")
    calls = []
    monkeypatch.setattr(pyinstaller, "run", calls.append)
    spec = importlib.util.spec_from_file_location("build_exe", BUILD_SCRIPT)  # "packaging" is also a PyPI package
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls


@pytest.mark.parametrize("inside", [REPO / "e9_build", Path(str(REPO).lower()) / "e9_build", REPO / "src" / "out"])
def test_the_build_script_rejects_an_output_inside_the_repository(inside, monkeypatch) -> None:
    module, calls = _build_script(monkeypatch)
    with pytest.raises(SystemExit) as stop:
        module.main(["--out", str(inside)])
    assert stop.value.code == 2 and calls == [] and not inside.exists()


def test_the_build_script_bundles_config_and_metadata_and_drops_the_repository_path(tmp_path, monkeypatch) -> None:
    module, calls = _build_script(monkeypatch)

    def fake_build(arguments):  # what PyInstaller would leave: the onedir folder with an editable-install record
        calls.append(arguments)
        info = tmp_path / "dist" / module.NAME / "_internal" / "mri_dataset_tool-0.1.0.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text("Name: mri-dataset-tool\n", encoding="utf-8")
        (info / "direct_url.json").write_text(json.dumps({"url": REPO.as_uri()}), encoding="utf-8")

    monkeypatch.setattr(module.PyInstaller.__main__, "run", fake_build)
    assert module.main(["--out", str(tmp_path), "--log-level=WARN"]) == 0
    arguments = calls[0]
    assert {"--windowed", "--onedir", "--log-level=WARN"} <= set(arguments)
    assert f"{REPO / 'config' / '*.yaml'}:config" in arguments
    assert {f"--copy-metadata={name}" for name in ("mri-dataset-tool", "numpy", "nibabel", "pydicom")} <= set(arguments)
    for flag in ("--workpath", "--distpath", "--specpath"):
        assert Path(arguments[arguments.index(flag) + 1]).is_relative_to(tmp_path)
    assert not list((tmp_path / "dist").rglob("direct_url.json"))
    with zipfile.ZipFile(tmp_path / f"{module.NAME}.zip") as archive:
        assert sorted(archive.namelist()) == sorted([
            f"{module.NAME}/", f"{module.NAME}/_internal/", f"{module.NAME}/_internal/mri_dataset_tool-0.1.0.dist-info/",
            f"{module.NAME}/_internal/mri_dataset_tool-0.1.0.dist-info/METADATA",
        ])


def test_the_build_script_has_no_path_of_the_developer_machine() -> None:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    forbidden = [str(REPO), REPO.as_posix(), REPO.parent.name, "E:/", "E:\\", "C:\\", "C:/", "MRI_ANON_KEY"]
    user = getpass.getuser()
    if len(user) >= 4:
        forbidden.append(user)
    for value in forbidden:
        assert value.lower() not in text.lower(), value

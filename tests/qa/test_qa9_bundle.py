"""QA9: audit of the portable Windows build (stage 5D). Report: docs/testing/qa_etapa9.md.

Two parts. The frozen config lookup is checked everywhere with ``monkeypatch`` (no PyInstaller): the bundled
``config/`` wins over one in the working directory, and with no config at all the input step stops with the
fixed message and creates nothing. The built bundle is audited only when ``MRI_QA9_BUNDLE`` names a
``dist/MRI-Dataset-Tool`` folder (Windows; the bundle lives outside the repository): string sweep of the files,
the zip members and the decompressed PYZ, its contents, and a start and close of the real exe in a clean
environment (no Python on PATH, TEMP redirected) that must write nothing anywhere. Only synthetic values.
"""

import ctypes
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from mri_dataset_tool.application.services import inputs
from mri_dataset_tool.application.services.dataset_build import InvalidBuildInput
from mri_dataset_tool.application.services.inputs import check_input_paths, project_config_dir
from mri_dataset_tool.presentation.gui.controller import WizardState

REPO = Path(__file__).resolve().parents[2]
BUNDLE = Path(os.environ["MRI_QA9_BUNDLE"]) if os.environ.get("MRI_QA9_BUNDLE") else None
EXE_NAME = "MRI-Dataset-Tool.exe"
# Strings of the development machine and the planted values that must not be in the bundle.
NEEDLES = ("Degree_Project", "mri_build", "mri_qa9", "Planted", str(REPO), REPO.as_posix(), Path.home().name)
# Upstream texts that contain a needle by coincidence (CI paths of the numpy wheels, pydoc examples).
KNOWN_UPSTREAM = {"pyz!numpy.__config__", "pyz!pydoc_data.topics"}


def _frozen(monkeypatch, tmp_path, bundled_config: bool) -> Path:
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    if bundled_config:
        (bundle / "config" / "default.yaml").write_text("pipeline: {}\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(inputs, "__file__", str(bundle / "mri_dataset_tool" / "inputs.pyc"))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return bundle


def test_bundled_config_wins_over_one_in_the_working_directory(tmp_path, monkeypatch):
    bundle = _frozen(monkeypatch, tmp_path, bundled_config=True)
    Path("config").mkdir()
    (Path("config") / "default.yaml").write_text("logging: {level: DEBUG}\n", encoding="utf-8")
    assert project_config_dir() == bundle / "config"
    assert WizardState().config_path.parent == bundle / "config"


def test_no_config_anywhere_stops_the_input_step_and_creates_nothing(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path, bundled_config=False)
    (tmp_path / "in").mkdir()
    assert not WizardState().config_path.is_file()
    with pytest.raises(InvalidBuildInput, match=r"^Config file not found\.$"):
        check_input_paths(tmp_path / "in", tmp_path / "out")
    assert not (tmp_path / "out").exists()


bundle_only = pytest.mark.skipif(BUNDLE is None or sys.platform != "win32", reason="set MRI_QA9_BUNDLE (Windows)")


def _members(bundle: Path, scratch: Path):
    """(name, bytes) of every file, zip member, exe CArchive entry and PYZ module (marshalled, so string
    constants appear verbatim)."""
    readers = pytest.importorskip("PyInstaller.archive.readers")
    for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
        rel = path.relative_to(bundle).as_posix()
        yield rel, path.read_bytes()
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    yield f"{rel}!{name}", archive.read(name)
    carchive = readers.CArchiveReader(str(bundle / EXE_NAME))
    for name in carchive.toc:
        if name != "PYZ.pyz":
            yield f"exe!{name}", carchive.extract(name)
    (scratch / "PYZ.pyz").write_bytes(carchive.extract("PYZ.pyz"))
    pyz = readers.ZlibArchiveReader(str(scratch / "PYZ.pyz"))
    modules = 0
    for name in pyz.toc:
        code = pyz.extract(name, raw=True)
        if code is not None:  # namespace packages carry no code
            modules += 1
            yield f"pyz!{name}", code
    assert modules > 1000, "the PYZ was not read"


@bundle_only
def test_bundle_has_no_development_paths_user_or_planted_values(tmp_path):
    paths = [n.encode(e).lower() for n in NEEDLES for e in ("utf-8", "utf-16-le")]
    # Exact case: the account and machine names are short words that also occur inside English text.
    exact = [os.environ.get(v) for v in ("MRI_ANON_KEY", "USERNAME", "COMPUTERNAME")]
    exact = [n.encode(e) for n in exact if n for e in ("utf-8", "utf-16-le")]
    hits = {name for name, data in _members(BUNDLE, tmp_path)
            if any(n in data.lower() for n in paths) or any(n in data for n in exact)}
    assert hits <= KNOWN_UPSTREAM, sorted(hits - KNOWN_UPSTREAM)  # names only: never the matched value


@bundle_only
def test_bundle_contents():
    internal = BUNDLE / "_internal"
    files = [p for p in BUNDLE.rglob("*") if p.is_file()]
    assert not [p for p in files if p.name == "direct_url.json" or p.suffix in (".spec", ".py")
                and "mri_dataset_tool" in p.parts]
    assert not [p for p in files if "tests" in p.relative_to(BUNDLE).parts]
    for name in ("mri_dataset_tool-0.1.0", "numpy-", "nibabel-", "pydicom-"):
        assert list(internal.glob(f"{name}*.dist-info/METADATA")), name
    shipped = {p.name: p.read_bytes() for p in (internal / "config").glob("*.yaml")}
    assert shipped == {p.name: p.read_bytes() for p in (REPO / "config").glob("*.yaml")}
    assert sum(p.stat().st_size for p in files) < 250 * 2**20  # plan: about 150-250 MB


def _visible_windows(pid: int) -> list[int]:
    user32, found = ctypes.windll.user32, []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(hwnd, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            found.append(hwnd)
        return True

    user32.EnumWindows(proto(collect), None)
    return found


@bundle_only
def test_exe_starts_without_python_and_writes_nowhere(tmp_path):
    cwd, temp = tmp_path / "cwd", tmp_path / "temp"
    cwd.mkdir()
    temp.mkdir()
    before = {p for p in BUNDLE.rglob("*")}
    system = os.environ["SystemRoot"]
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "VIRTUAL_ENV", "MRI_"))}
    env.update(PATH=f"{system}\\System32;{system}", TEMP=str(temp), TMP=str(temp))
    process = subprocess.Popen([str(BUNDLE / EXE_NAME)], cwd=cwd, env=env)
    try:
        deadline = time.monotonic() + 60
        while not _visible_windows(process.pid) and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(3)  # the startup task
        assert process.poll() is None, "the exe exited at startup"
        windows = _visible_windows(process.pid)
        assert windows, "no window"
        for hwnd in windows:
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)  # WM_CLOSE
        assert process.wait(20) == 0
    finally:
        if process.poll() is None:
            process.kill()
    assert {p for p in BUNDLE.rglob("*")} == before
    assert not list(cwd.iterdir()) and not list(temp.iterdir())

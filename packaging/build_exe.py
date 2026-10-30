"""Build the portable Windows GUI (``onedir`` folder plus its ``.zip``) with PyInstaller.

PyInstaller is a build tool, not a package dependency: install it by hand in the virtual environment
(``python -m pip install pyinstaller==6.22.3``). Run from any directory::

    python packaging/build_exe.py --out <folder>

``<folder>`` receives ``build/`` (work files), ``spec/`` (the generated spec), ``dist/MRI-Dataset-Tool/``
and ``MRI-Dataset-Tool.zip``; keep it outside the repository and on a disk with room (~1 GB). Other
arguments go to PyInstaller unchanged (e.g. ``--debug=imports``).
"""

import argparse
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
NAME = "MRI-Dataset-Tool"
# Versions shown by the GUI and written to the run manifest (importlib.metadata), not "unknown".
METADATA = ("mri-dataset-tool", "numpy", "nibabel", "pydicom")
# Optional imports of the dependencies (plots, notebooks, tests) the GUI never uses.
EXCLUDES = (
    "matplotlib", "PIL", "IPython", "ipykernel", "ipywidgets", "jupyter_client", "jupyter_core", "notebook",
    "nbformat", "tornado", "zmq", "pytest", "_pytest", "pygments", "jedi", "pandas", "h5py",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the portable Windows GUI.")
    parser.add_argument("--out", type=Path, required=True, help="output folder, outside the repository")
    args, extra = parser.parse_known_args(argv)
    if sys.platform != "win32":
        parser.error("the portable build is Windows only")
    out = args.out.resolve()
    if out.is_relative_to(ROOT):
        parser.error("--out must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    PyInstaller.__main__.run([
        str(ROOT / "src" / "mri_dataset_tool" / "presentation" / "gui" / "__main__.py"),
        "--name", NAME, "--windowed", "--onedir", "--noconfirm", "--clean",
        "--paths", str(ROOT / "src"),
        "--workpath", str(out / "build"), "--distpath", str(out / "dist"), "--specpath", str(out / "spec"),
        "--add-data", f"{ROOT / 'config' / '*.yaml'}:config",
        *(f"--copy-metadata={name}" for name in METADATA),
        *(f"--exclude-module={name}" for name in EXCLUDES),
        *extra,
    ])
    # An editable install records the repository folder there; the version needs only METADATA.
    for record in (out / "dist" / NAME).rglob("direct_url.json"):
        record.unlink()
    shutil.make_archive(str(out / NAME), "zip", out / "dist", NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

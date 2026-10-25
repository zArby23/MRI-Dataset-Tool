"""QA5 (RNF02): peak memory of ``mri-dataset process`` does not grow with the number of studies.

Each run is a fresh ``python -m mri_dataset_tool.presentation.cli`` process; its peak resident memory is
read at exit (Windows ``peak_wset``, Linux ``ru_maxrss``). A batch four times larger must not raise the
peak by more than a fraction of one extra study. Volumes are ~6 MiB float32 each, so a pipeline that kept
every study alive would add ~90 MiB. Data goes to E:/ when it exists (large outputs never on C:).
"""

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SHAPE = (128, 128, 96)
STEPS = "pipeline:\n  steps:\n    - name: validate\n    - name: reorient\n    - name: normalize\n"
_PEAK = (
    "import sys, psutil\n"
    "from mri_dataset_tool.presentation.cli.main import main\n"
    "code = main(sys.argv[1:])\n"
    "info = psutil.Process().memory_info()\n"
    "if hasattr(info, 'peak_wset'):\n"
    "    peak = info.peak_wset\n"
    "else:\n"
    "    import resource; peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024\n"
    "print('PEAK', peak, 'CODE', code)\n"
)


@pytest.fixture
def base(tmp_path):
    if os.path.isdir("E:/"):
        root = Path("E:/qa5_tmp") / uuid.uuid4().hex
        root.mkdir(parents=True)
        yield root
        shutil.rmtree(root, ignore_errors=True)
    else:
        yield tmp_path


def _batch(root: Path, count: int) -> Path:
    rng = np.random.default_rng(count)
    root.mkdir(parents=True)
    for i in range(count):
        volume = rng.normal(100, 20, SHAPE).astype(np.float32)
        nib.save(nib.Nifti1Image(volume, np.diag([-1.0, -1.0, 1.2, 1.0])), root / f"img{i:03d}.nii.gz")
    return root


def _peak(base: Path, count: int, config: Path) -> int:
    source = _batch(base / f"in{count}", count)
    result = subprocess.run(
        [sys.executable, "-c", _PEAK, "--quiet", "process", str(source), "--format", "nifti", "--config", str(config),
         "--output-dir", str(base / f"out{count}"), "--manifest-path", str(base / f"m{count}.json")],
        capture_output=True, text=True, cwd=REPO,
    )
    line = [l for l in result.stdout.splitlines() if l.startswith("PEAK")]
    assert line and line[0].endswith("CODE 0"), result.stdout + result.stderr
    assert len(list((base / f"out{count}").glob("study-*.nii.gz"))) == count
    return int(line[0].split()[1])


def test_process_peak_memory_does_not_grow_with_the_batch(base) -> None:
    config = base / "steps.yaml"
    config.write_text(STEPS, "utf-8")
    small, large = _peak(base, 5, config), _peak(base, 20, config)
    one_study = int(np.prod(SHAPE)) * 4
    assert large - small < one_study * 3, (small // 2**20, large // 2**20)

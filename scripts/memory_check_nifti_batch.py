"""Peak RSS of NIfTIBatchReader over a batch directory (RNF02).

Usage, from the repository root:  python scripts/memory_check_nifti_batch.py [batch_dir] [--lazy]

batch_dir defaults to data/raw/nifti_test_studies. The console shows only counts and RSS,
never file names or paths.
"""

from __future__ import annotations

import argparse
import gc
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psutil

from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader


def rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 ** 2)


DEFAULT_BATCH_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "nifti_test_studies"


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Peak RSS of NIfTIBatchReader over a batch directory.")
    parser.add_argument("batch_dir", nargs="?", type=Path, default=DEFAULT_BATCH_DIR)
    parser.add_argument("--lazy", action="store_true", help="keep volumes as nibabel proxies (M0)")
    args = parser.parse_args(argv)
    batch_dir, lazy = args.batch_dir, args.lazy

    if not batch_dir.is_dir():
        print("NIfTI batch directory not found.")  # fixed text: never the path
        return 2

    reader = NIfTIBatchReader()
    baseline = rss_mb()
    peak = baseline
    processed = 0

    print(f"Lazy loading: {lazy}")
    print(f"Baseline RSS: {baseline:.1f} MB")

    try:
        for study in reader.iter_studies(batch_dir, lazy=lazy):
            processed += 1
            current = rss_mb()
            peak = max(peak, current)
            print(f"Processed {processed}: RSS={current:.1f} MB")
            del study
            gc.collect()
    except ValueError:
        print("No valid NIfTI files were found.")
        return 1
    except Exception as error:  # its message or traceback may name a file
        print(f"Run failed: {type(error).__name__}")
        return 1

    final = rss_mb()
    print("\nSummary:")
    print(f"  files processed: {processed}")
    print(f"  baseline rss: {baseline:.1f} MB")
    print(f"  peak rss: {peak:.1f} MB")
    print(f"  final rss: {final:.1f} MB")
    print(f"  delta from baseline: {peak - baseline:.1f} MB")

    if peak - baseline > 500:
        print("\nWARNING: memory usage increased significantly during the batch run.")
        print("This suggests retention or accumulation of volumes in memory.")
        print("Prefer iter_studies() or process one file per iteration.")
        return 2

    print("\nOK: memory remained bounded during the batch process.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

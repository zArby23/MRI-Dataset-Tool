from __future__ import annotations

import gc
import os
from pathlib import Path

import psutil

from mri_dataset_tool.infrastructure.nifti.batch_reader import NIfTIBatchReader


def rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 ** 2)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    batch_dir = root / "data" / "raw" / "nifti_test_studies"

    if not batch_dir.exists():
        raise FileNotFoundError(f"NIfTI batch directory not found: {batch_dir}")

    reader = NIfTIBatchReader()
    baseline = rss_mb()
    peak = baseline
    processed = 0

    print(f"Batch directory: {batch_dir}")
    print(f"Baseline RSS: {baseline:.1f} MB")

    try:
        for study in reader.iter_studies(batch_dir):
            processed += 1
            current = rss_mb()
            peak = max(peak, current)
            print(
                f"Processed {processed}: "
                f"{study.series[0].files[0].name} | RSS={current:.1f} MB"
            )
            del study
            gc.collect()
    except ValueError as exc:
        print(f"No valid NIfTI files were found: {exc}")
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
    raise SystemExit(main())

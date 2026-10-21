"""Built-in processing steps: importing this package registers them (``register_step``).

Each step module is imported here; ``manifest.py`` imports this package so that
``pipeline_from_config`` and ``pipeline_from_manifest`` find them by name.
"""

from mri_dataset_tool.application.pipeline.steps import validate  # noqa: F401

from mri_dataset_tool.application.pipeline.steps import anonymize  # noqa: F401

from mri_dataset_tool.application.pipeline.steps import reorient  # noqa: F401

from mri_dataset_tool.application.pipeline.steps import normalize  # noqa: F401

from mri_dataset_tool.application.pipeline.steps import resample  # noqa: F401

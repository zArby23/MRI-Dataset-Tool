"""Available-RAM check before allocating a large output volume."""

import psutil

from mri_dataset_tool.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def check_allow_insufficient_memory(allow_insufficient: object) -> None:
    if not isinstance(allow_insufficient, bool):
        raise ValueError("Allow insufficient memory must be a boolean.")


def check_available_memory(required_bytes: int, allow_insufficient: bool = False) -> None:
    """Raise ``ValueError`` if *required_bytes* exceed the available RAM, unless *allow_insufficient*.

    If the available RAM cannot be read, the check passes: ``MemoryError`` stays the safety net.
    Never logs or reports memory figures.
    """
    try:
        available = psutil.virtual_memory().available
    except Exception as error:  # psutil can fail on restricted systems; do not block the run
        logger.warning("Available memory could not be read (%s); check skipped.", type(error).__name__)
        return
    if required_bytes <= available:
        return
    if not allow_insufficient:
        raise ValueError("Insufficient available memory for the resampled volume.")
    logger.warning("Proceeding without enough available memory (explicitly allowed).")

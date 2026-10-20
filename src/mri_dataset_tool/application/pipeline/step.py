import inspect
from collections.abc import Callable
from typing import Any, Protocol

from mri_dataset_tool.domain.models.study import MRIStudy


class ProcessingStep(Protocol):
    """One transformation of the pipeline.

    ``apply`` must not mutate its input (build the result with ``dataclasses.replace``)
    and must be deterministic given ``params``. ``params`` holds only JSON-serializable
    values and, passed back to the factory, rebuilds an equivalent step. ``name`` is the
    name the step is registered under.
    """

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def params(self) -> dict[str, Any]: ...

    def apply(self, study: MRIStudy) -> MRIStudy: ...


STEP_REGISTRY: dict[str, Callable[..., ProcessingStep]] = {}


def register_step[F: Callable[..., ProcessingStep]](name: str) -> Callable[[F], F]:
    """Register a step factory (usually the step class) under *name*.

    The factory is called as ``factory(**params)`` by ``build_step``.
    """

    def decorator(factory: F) -> F:
        if name in STEP_REGISTRY:
            raise ValueError("Processing step name is already registered.")
        STEP_REGISTRY[name] = factory
        return factory

    return decorator


def build_step(name: str, params: dict[str, Any] | None = None) -> ProcessingStep:
    """Rebuild the step registered under *name* with *params* (from config or a manifest)."""
    try:
        factory = STEP_REGISTRY[name]
    except KeyError:
        raise ValueError("Unknown processing step.") from None
    params = params or {}
    try:
        inspect.signature(factory).bind(**params)
    except TypeError as error:
        raise ValueError("Invalid parameters for processing step.") from error
    return factory(**params)

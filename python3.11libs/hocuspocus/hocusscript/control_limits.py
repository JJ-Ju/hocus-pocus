"""Fixed admission and expansion limits shared by control/value lanes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ControlExpansionLimits:
    import_depth: int = 64
    instance_depth: int = 64
    instances: int = 4096
    parameters_per_module: int = 256
    exports_per_module: int = 256
    expanded_nodes: int = 10_000
    aggregate_code_bytes: int = 4 * 1024 * 1024
    source_map_entries: int = 100_000
    diagnostics: int = 500
    per_fold_iterations: int = 4096
    aggregate_iterations: int = 100_000

    def __post_init__(self) -> None:
        maxima = {
            "import_depth": 64,
            "instance_depth": 64,
            "instances": 4096,
            "parameters_per_module": 256,
            "exports_per_module": 256,
            "expanded_nodes": 10_000,
            "aggregate_code_bytes": 4_194_304,
            "source_map_entries": 100_000,
            "diagnostics": 500,
            "per_fold_iterations": 4096,
            "aggregate_iterations": 100_000,
        }
        for name, maximum in maxima.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(
                    f"ControlExpansionLimits.{name} must be an integer from 1 to {maximum}."
                )

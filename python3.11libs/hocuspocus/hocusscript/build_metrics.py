"""Bounded HS8 build metrics and target-platform budget evaluation."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping


_PLATFORM = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_MAX_COUNT = (1 << 63) - 1
_MAX_DURATION_MS = 31_536_000_000.0


class BuildMetricsError(ValueError):
    """Typed malformed-metrics or platform-budget failure."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class BuildMetrics:
    """Portable numeric evidence from one completed build."""

    cook_duration_ms: float
    peak_memory_bytes: int
    polygon_count: int
    texture_count: int
    texture_bytes: int
    output_bytes: int
    cook_error_count: int = 0
    cook_warning_count: int = 0

    def __post_init__(self) -> None:
        for name in ("cook_duration_ms",):
            _finite_number(getattr(self, name), name, _MAX_DURATION_MS)
        for name in (
            "peak_memory_bytes", "polygon_count", "texture_count", "texture_bytes",
            "output_bytes", "cook_error_count", "cook_warning_count",
        ):
            _count(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cookDurationMs": self.cook_duration_ms,
            "peakMemoryBytes": self.peak_memory_bytes,
            "polygonCount": self.polygon_count,
            "textureCount": self.texture_count,
            "textureBytes": self.texture_bytes,
            "outputBytes": self.output_bytes,
            "cookErrorCount": self.cook_error_count,
            "cookWarningCount": self.cook_warning_count,
        }

    @classmethod
    def from_dict(cls, value: Any) -> BuildMetrics:
        if not isinstance(value, dict) or set(value) != {
            "cookDurationMs", "peakMemoryBytes", "polygonCount", "textureCount",
            "textureBytes", "outputBytes", "cookErrorCount", "cookWarningCount",
        }:
            raise _invalid("Build metrics have an invalid envelope.")
        return cls(
            cook_duration_ms=value["cookDurationMs"],
            peak_memory_bytes=value["peakMemoryBytes"],
            polygon_count=value["polygonCount"],
            texture_count=value["textureCount"],
            texture_bytes=value["textureBytes"],
            output_bytes=value["outputBytes"],
            cook_error_count=value["cookErrorCount"],
            cook_warning_count=value["cookWarningCount"],
        )


@dataclass(frozen=True, slots=True)
class PlatformBudget:
    """Maximum production cost accepted for one explicit target platform."""

    target_platform: str
    max_cook_duration_ms: float
    max_peak_memory_bytes: int
    max_polygon_count: int
    max_texture_count: int
    max_texture_bytes: int
    max_output_bytes: int
    max_cook_error_count: int = 0
    max_cook_warning_count: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target_platform, str)
            or _PLATFORM.fullmatch(self.target_platform) is None
        ):
            raise _invalid("Platform budget target is invalid.")
        _finite_number(
            self.max_cook_duration_ms, "max_cook_duration_ms", _MAX_DURATION_MS,
        )
        for name in (
            "max_peak_memory_bytes", "max_polygon_count", "max_texture_count",
            "max_texture_bytes", "max_output_bytes", "max_cook_error_count",
            "max_cook_warning_count",
        ):
            _count(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "targetPlatform": self.target_platform,
            "maxCookDurationMs": self.max_cook_duration_ms,
            "maxPeakMemoryBytes": self.max_peak_memory_bytes,
            "maxPolygonCount": self.max_polygon_count,
            "maxTextureCount": self.max_texture_count,
            "maxTextureBytes": self.max_texture_bytes,
            "maxOutputBytes": self.max_output_bytes,
            "maxCookErrorCount": self.max_cook_error_count,
            "maxCookWarningCount": self.max_cook_warning_count,
        }

    @classmethod
    def from_dict(cls, value: Any) -> PlatformBudget:
        if not isinstance(value, dict) or set(value) != {
            "targetPlatform", "maxCookDurationMs", "maxPeakMemoryBytes",
            "maxPolygonCount", "maxTextureCount", "maxTextureBytes",
            "maxOutputBytes", "maxCookErrorCount", "maxCookWarningCount",
        }:
            raise _invalid("Platform budget has an invalid envelope.")
        return cls(
            target_platform=value["targetPlatform"],
            max_cook_duration_ms=value["maxCookDurationMs"],
            max_peak_memory_bytes=value["maxPeakMemoryBytes"],
            max_polygon_count=value["maxPolygonCount"],
            max_texture_count=value["maxTextureCount"],
            max_texture_bytes=value["maxTextureBytes"],
            max_output_bytes=value["maxOutputBytes"],
            max_cook_error_count=value["maxCookErrorCount"],
            max_cook_warning_count=value["maxCookWarningCount"],
        )


def evaluate_platform_budget(
    metrics: BuildMetrics,
    budget: PlatformBudget,
    *,
    target_platform: str,
) -> dict[str, Any]:
    """Return deterministic, field-complete budget evidence without raising on fail."""

    if not isinstance(metrics, BuildMetrics) or not isinstance(budget, PlatformBudget):
        raise _invalid("Budget evaluation requires typed metrics and budget values.")
    if target_platform != budget.target_platform:
        raise BuildMetricsError(
            "HOCUS984",
            "Build target does not match the selected platform budget.",
            details={
                "targetPlatform": target_platform,
                "budgetPlatform": budget.target_platform,
            },
        )
    comparisons = (
        ("cookDurationMs", metrics.cook_duration_ms, budget.max_cook_duration_ms),
        ("peakMemoryBytes", metrics.peak_memory_bytes, budget.max_peak_memory_bytes),
        ("polygonCount", metrics.polygon_count, budget.max_polygon_count),
        ("textureCount", metrics.texture_count, budget.max_texture_count),
        ("textureBytes", metrics.texture_bytes, budget.max_texture_bytes),
        ("outputBytes", metrics.output_bytes, budget.max_output_bytes),
        ("cookErrorCount", metrics.cook_error_count, budget.max_cook_error_count),
        ("cookWarningCount", metrics.cook_warning_count, budget.max_cook_warning_count),
    )
    checks = [
        {
            "metric": name,
            "actual": actual,
            "maximum": maximum,
            "passed": actual <= maximum,
        }
        for name, actual, maximum in comparisons
    ]
    return {
        "targetPlatform": target_platform,
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }


def _finite_number(value: Any, name: str, maximum: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= maximum
    ):
        raise _invalid(f"{name} must be a finite bounded non-negative number.")


def _count(value: Any, name: str) -> None:
    if type(value) is not int or not 0 <= value <= _MAX_COUNT:
        raise _invalid(f"{name} must be a bounded non-negative integer.")


def _invalid(message: str) -> BuildMetricsError:
    return BuildMetricsError("HOCUS983", message)


__all__ = [
    "BuildMetrics",
    "BuildMetricsError",
    "PlatformBudget",
    "evaluate_platform_budget",
]

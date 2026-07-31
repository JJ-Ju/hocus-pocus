"""Run deterministic V1 parser/compiler benchmarks and emit an external receipt."""

from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from release_evidence_support import (
    ROOT,
    canonical_json,
    content_digest,
    file_digest,
    receipt,
    write_receipt,
)

from hocuspocus.hocusscript import (
    CompiledBundle,
    compile_source,
    lower_bundle_to_document,
    resolve_graph,
)
from tests.test_hocusscript_authoring_scenarios import _baseline, _provider

FIXTURE_PATH = ROOT / "scripts" / "fixtures" / "release" / "performance-fixtures.json"


def _houdini_identity(hython: Path) -> dict[str, Any]:
    resolved = hython.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("--hython must identify a real executable file.")
    probe = (
        "import hou,json,platform,sys;"
        "print(json.dumps({"
        "'applicationVersion':list(hou.applicationVersion()),"
        "'applicationVersionString':hou.applicationVersionString(),"
        "'python':platform.python_version(),"
        "'pythonImplementation':platform.python_implementation()"
        "},allow_nan=False,sort_keys=True))"
    )
    try:
        completed = subprocess.run(
            [str(resolved), "-c", probe],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        value = json.loads(lines[-1]) if lines else None
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Could not derive Houdini identity from --hython.") from exc
    fields = {
        "applicationVersion",
        "applicationVersionString",
        "python",
        "pythonImplementation",
    }
    version = value.get("applicationVersion") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or not isinstance(version, list)
        or not version
        or any(type(item) is not int or item < 0 for item in version)
        or any(
            not isinstance(value[field], str) or not value[field]
            for field in fields - {"applicationVersion"}
        )
    ):
        raise ValueError("--hython returned an invalid Houdini identity.")
    return {
        **value,
        "hythonDigest": file_digest(resolved),
    }


def _source(fixture: dict[str, Any]) -> str:
    if fixture["topology"] != "linear-chain":
        raise ValueError(f"Unsupported benchmark topology: {fixture['topology']!r}")
    count = fixture["nodeCount"]
    width = len(str(count - 1))
    lines = [
        "hocus 0.1;",
        f"graph {fixture['profile']}_{count} {{",
        f'  target "/obj/hocus_benchmark_{count}";',
        "  category Sop;",
        "  mode merge;",
    ]
    for index in range(count):
        symbol = f"n{index:0{width}d}"
        body = ""
        if index:
            previous = f"n{index - 1:0{width}d}"
            body = f" input[0] = {previous}.output[0]; "
        lines.append(
            f'  node {symbol} @id("benchmark.{symbol}"): '
            f'"{fixture["operator"]}" {{{body}}}'
        )
    lines.extend((f"  output = n{count - 1:0{width}d};", "}", ""))
    return "\n".join(lines)


def _compile(source: str, source_name: str, provider: Any) -> Any:
    compiled = compile_source(
        source,
        source_name,
        source_uri=f"hocus-project://benchmark/fixtures/{source_name}",
    )
    if not compiled.valid or compiled.graph_spec is None:
        diagnostics = [item.to_dict() for item in compiled.diagnostics]
        raise RuntimeError(f"Benchmark fixture did not compile: {diagnostics!r}")
    semantic = resolve_graph(compiled.graph_spec, provider)
    if not semantic.valid:
        diagnostics = [item.to_dict() for item in semantic.diagnostics]
        raise RuntimeError(f"Benchmark fixture did not resolve: {diagnostics!r}")
    compiled.semantic_result = semantic
    return compiled


def _preview(source: str, source_name: str, provider: Any, baseline: dict[str, Any]) -> None:
    compiled = _compile(source, source_name, provider)
    compiled.source_kind = "project_file"
    compiled.project_uid = "benchmark"
    compiled.project_manifest_digest = content_digest("benchmark-manifest")
    compiled.project_lock_digest = content_digest("benchmark-lock")
    compiled.catalog_fingerprint = provider.catalog.fingerprint
    compiled.catalog_content_digest = content_digest(provider.catalog.to_json())
    bundle = CompiledBundle.from_result(compiled)
    preview = lower_bundle_to_document(bundle, baseline)
    if not preview.valid or preview.candidate_plan is None:
        raise RuntimeError(
            f"Benchmark fixture did not produce a valid preview: {preview.diagnostics!r}"
        )


def _baseline_for(fixture: dict[str, Any]) -> dict[str, Any]:
    target = f"/obj/hocus_benchmark_{fixture['nodeCount']}"
    baseline = copy.deepcopy(_baseline())
    baseline["documentId"] = f"network:{target}"
    baseline["rootPath"] = target
    baseline["nodes"] = baseline["nodes"][:1]
    baseline["nodes"][0].update(
        {
            "uid": f"benchmark-root-{fixture['nodeCount']}",
            "name": target.rsplit("/", 1)[-1],
            "path": target,
            "parentPath": "/obj",
        }
    )
    return baseline


def _samples(operation: Callable[[], None], *, warmups: int, repetitions: int) -> list[float]:
    for _ in range(warmups):
        operation()
    measured: list[float] = []
    for _ in range(repetitions):
        start = time.perf_counter_ns()
        operation()
        measured.append(round((time.perf_counter_ns() - start) / 1_000_000, 6))
    return measured


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _measurement(
    fixture: dict[str, Any],
    *,
    repetitions: int,
    warmups: int,
    target_ms: float,
    target_percentile: str,
    provider: Any,
) -> dict[str, Any]:
    source = _source(fixture)
    source_name = f"{fixture['id']}.hocus"
    if fixture["profile"] == "preview":
        baseline = _baseline_for(fixture)
        baseline_digest = content_digest(canonical_json(baseline))
        if fixture.get("baselineDigest") != baseline_digest:
            raise ValueError(
                "Preview benchmark baseline differs from its fixed fixture digest."
            )
        operation = lambda: _preview(source, source_name, provider, baseline)
        pipeline = (
            "source-to-structural-compile-to-semantic-resolution-to-authenticated-"
            "bundle-to-document-lowering-and-diff"
        )
    else:
        baseline_digest = None
        operation = lambda: _compile(source, source_name, provider)
        pipeline = "source-to-semantic-graph"
    samples = _samples(operation, warmups=warmups, repetitions=repetitions)
    summary = {
        "minimumMs": min(samples),
        "medianMs": statistics.median(samples),
        "p50Ms": _percentile(samples, 0.50),
        "p95Ms": _percentile(samples, 0.95),
        "maximumMs": max(samples),
    }
    measured = summary[target_percentile]
    result = {
        "fixtureId": fixture["id"],
        "pipeline": pipeline,
        "nodeCount": fixture["nodeCount"],
        "sourceBytes": len(source.encode("utf-8")),
        "sourceDigest": content_digest(source),
        "warmupCount": warmups,
        "repetitionCount": repetitions,
        "samplesMs": samples,
        "summary": summary,
        "target": {
            "metric": target_percentile,
            "maximumMs": target_ms,
            "passed": measured <= target_ms,
        },
    }
    if baseline_digest is not None:
        result["baselineDigest"] = baseline_digest
    return result


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    fixture_document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixtures = {item["profile"]: item for item in fixture_document["fixtures"]}
    provider = _provider()
    houdini = _houdini_identity(arguments.hython)
    measurements = [
        _measurement(
            fixtures["preview"],
            repetitions=arguments.preview_repetitions,
            warmups=arguments.warmups,
            target_ms=250.0,
            target_percentile="p95Ms",
            provider=provider,
        ),
        _measurement(
            fixtures["compile"],
            repetitions=arguments.compile_repetitions,
            warmups=arguments.warmups,
            target_ms=2000.0,
            target_percentile="medianMs",
            provider=provider,
        ),
    ]
    evidence = {
        "cataloguePolicy": {
            "catalogueConstruction": "once-before-warmups",
            "sampleMode": "warm",
            "catalogueFingerprint": provider.catalog.fingerprint,
        },
        "measurements": measurements,
        "passed": all(item["target"]["passed"] for item in measurements),
    }
    return receipt(
        "hocus_performance_benchmark_receipt",
        evidence,
        fixture_digests={"performance-fixtures.json": file_digest(FIXTURE_PATH)},
        houdini_identity=houdini,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hython", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--preview-repetitions", type=int, default=20)
    parser.add_argument("--compile-repetitions", type=int, default=7)
    arguments = parser.parse_args()
    if min(
        arguments.warmups,
        arguments.preview_repetitions,
        arguments.compile_repetitions,
    ) < 1:
        parser.error("warmups and repetition counts must be positive")
    value = run(arguments)
    write_receipt(arguments.output, value)
    print(json.dumps(value["evidence"], indent=2, sort_keys=True))
    return 0 if value["evidence"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

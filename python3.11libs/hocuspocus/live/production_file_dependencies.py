"""Fail-closed file-reference classification for production observation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_KNOWN_INTERNAL_OUTPUT_FILE_PARMS = frozenset({
    ("Lop", "configurelayer", "Lop/configurelayer", ("configurelayer",), "savepath"),
})


def collect_file_dependencies(
    node: Any,
    *,
    required: Callable[[Callable[[], Any], str], Any],
    error_type: type[RuntimeError],
) -> list[tuple[tuple[str, str, str], dict[str, Any]]]:
    """Reject ambient input references while ignoring exact known outputs."""

    node_path = str(required(
        node.path,
        "Could not inspect a file parameter's node path.",
    ))
    parms = required(
        node.parms,
        f"Could not enumerate parameters at {node_path}.",
    )
    for parm in parms or ():
        parm_path = str(required(
            parm.path,
            f"Could not inspect a file parameter path at {node_path}.",
        ))
        template = required(
            parm.parmTemplate,
            f"Could not inspect parameter template at {parm_path}.",
        )
        template_type = str(required(
            lambda template=template: template.type().name(),
            f"Could not inspect parameter type at {parm_path}.",
        ))
        if template_type != "String":
            continue
        string_type = str(required(
            lambda template=template: template.stringType().name(),
            f"Could not inspect parameter string type at {parm_path}.",
        ))
        if "FileReference" not in string_type:
            continue
        if _known_output_file_parm(node, parm, required, node_path):
            continue
        value = str(required(
            parm.unexpandedString,
            f"Could not inspect file dependency at {parm_path}.",
        ) or "")
        if not value:
            continue
        raise error_type(
            "Ambient file dependency lacks an approved bounded byte receipt "
            f"at {parm_path}."
        )
    return []


def _known_output_file_parm(
    node: Any,
    parm: Any,
    required: Callable[[Callable[[], Any], str], Any],
    node_path: str,
) -> bool:
    node_type = required(
        node.type,
        f"Could not inspect node type at {node_path}.",
    )
    identity = (
        str(required(
            lambda: node_type.category().name(),
            f"Could not inspect node category at {node_path}.",
        )),
        str(required(
            node_type.name,
            f"Could not inspect node type name at {node_path}.",
        )),
        str(required(
            node_type.nameWithCategory,
            f"Could not inspect qualified node type name at {node_path}.",
        )),
        required(
            lambda: tuple(node_type.namespaceOrder()),
            f"Could not inspect node type namespace order at {node_path}.",
        ),
        str(required(
            parm.name,
            f"Could not inspect file parameter name at {node_path}.",
        )),
    )
    if identity not in _KNOWN_INTERNAL_OUTPUT_FILE_PARMS:
        return False
    definition = required(
        node_type.definition,
        f"Could not inspect node type definition at {node_path}.",
    )
    source = required(
        node_type.source,
        f"Could not inspect node type source at {node_path}.",
    )
    source_name = str(required(
        source.name,
        f"Could not inspect node type source name at {node_path}.",
    ))
    source_path = str(required(
        node_type.sourcePath,
        f"Could not inspect node type source path at {node_path}.",
    ))
    return definition is None and source_name == "Internal" and source_path == "Internal"

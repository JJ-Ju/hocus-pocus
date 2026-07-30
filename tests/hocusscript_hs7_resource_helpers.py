"""Focused assertions for the static HS7 fidelity resource."""

from __future__ import annotations

import json
from typing import Any

from hocuspocus.live.context import RequestContext


def assert_hs7_fidelity_resource(case: Any, resources: Any) -> None:
    uri = "houdini://documents/hocusscript/fidelity/hs7"
    definition = resources.get(uri)
    case.assertIsNotNone(definition)
    discovered = {item["uri"]: item for item in resources.list_payload()}
    case.assertIn(uri, discovered)
    case.assertNotIn("requiredCapabilities", discovered[uri])
    case.assertEqual(definition.mime_type, "application/json")
    case.assertTrue(definition.payload_summary)
    case.assertTrue(definition.examples)
    content = definition.reader(RequestContext())["contents"][0]
    case.assertEqual(content["uri"], uri)
    payload = json.loads(content["text"])
    case.assertEqual(payload["kind"], "hocus_fidelity_matrix")
    case.assertEqual(payload["phase"], "HS7")
    case.assertEqual(
        payload["statuses"],
        ["preserved-opaque", "read-only", "rejected", "supported"],
    )
    case.assertNotIn("\\", content["text"])
    case.assertNotIn("file://", content["text"])

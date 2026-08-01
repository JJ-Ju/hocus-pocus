from __future__ import annotations

import copy
import hashlib
import json
import logging

from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import LiveDocumentService


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def assert_checkout_delivery(testcase, tools, document: dict) -> None:
    tools._documents = LiveDocumentService(logging.getLogger("test.checkout-delivery"))
    tools._document_current_network_payload = lambda _root: copy.deepcopy(document)

    inline = tools.document_checkout(
        {"scope": "network", "root_path": document["rootPath"]},
        RequestContext(),
    )["structuredContent"]
    expected = tools._documents.working_document(inline["checkoutId"])
    encoded = _canonical(expected)
    testcase.assertEqual(inline["document"], expected)
    testcase.assertEqual(inline["documentDelivery"]["mode"], "inline")
    testcase.assertEqual(inline["documentDelivery"]["byteLength"], len(encoded))
    testcase.assertEqual(
        inline["documentDelivery"]["contentDigest"],
        f"sha256:{hashlib.sha256(encoded).hexdigest()}",
    )
    testcase.assertEqual(
        inline["resourceUri"],
        f"houdini://documents/checkouts/{inline['checkoutId']}",
    )

    tools._MAX_INLINE_CHECKOUT_PAYLOAD_BYTES = 512
    resource_document = copy.deepcopy(document)
    resource_document.setdefault("metadata", {})["large"] = "x" * 512
    tools._document_current_network_payload = lambda _root: copy.deepcopy(resource_document)
    resource = tools.document_checkout(
        {"scope": "network", "root_path": document["rootPath"]},
        RequestContext(),
    )["structuredContent"]
    expected_resource = tools._documents.working_document(resource["checkoutId"])
    encoded_resource = _canonical(expected_resource)
    testcase.assertNotIn("document", resource)
    testcase.assertEqual(resource["documentDelivery"]["mode"], "resource")
    testcase.assertEqual(
        resource["documentDelivery"]["reason"],
        "document_exceeds_inline_limit",
    )
    testcase.assertEqual(resource["documentDelivery"]["byteLength"], len(encoded_resource))
    testcase.assertEqual(
        resource["documentDelivery"]["contentDigest"],
        f"sha256:{hashlib.sha256(encoded_resource).hexdigest()}",
    )
    testcase.assertEqual(
        json.loads(
            tools.read_document_checkout(resource["checkoutId"], RequestContext())[
                "contents"
            ][0]["text"]
        ),
        expected_resource,
    )

# HocusPocus Compatibility Policy

Status: active

Applies to:

- HocusPocus `0.9.x`
- Houdini `21.x`
- the Streamable HTTP MCP surface served by HocusPocus

## 1. Supported Houdini Range

HocusPocus currently targets Houdini `21.x`.

Compatibility expectations:

- supported and actively validated: Houdini `21.0`
- intended compatibility target: other Houdini `21.x` builds where HOM, LOP, PDG, and viewport APIs remain materially compatible
- not guaranteed: Houdini `20.x`, Houdini `22.x`, or Engine-only/headless deployments that do not expose the same UI/runtime APIs

If a Houdini `21.x` point release changes HOM or UI behavior in a way that breaks an existing tool, HocusPocus should treat that as a compatibility regression and fix it in a patch release where practical.

## 2. MCP Compatibility Contract

HocusPocus currently serves:

- protocol version: `2025-11-25`
- transport: localhost Streamable HTTP
- auth model: bearer token by default

Compatibility expectations:

- existing tool names should remain stable within a minor line unless clearly deprecated first
- existing resource URIs and URI templates should remain stable within a minor line unless clearly deprecated first
- payload fields may expand, but existing documented fields should not be silently removed from stable tools without a version bump and release note

## 3. Stability Levels

### Stable

These are expected to remain materially compatible within the `0.9.x` line:

- server status and health payload shape
- core node, parm, scene, task, graph, export, render, Solaris, and PDG tool names
- documented resource URI schemes
- task result envelope fields such as `state`, `progress`, `result`, `error`, `outcome`, and `recoveryNotes`

### Provisional

These may evolve more rapidly while the product surface is still maturing:

- macro-style modeling helpers
- panel/chat/operator UX
- worker-plane and headless execution features
- event streaming transport and replay semantics
- newly introduced phase 5+ usability or recipe surfaces

Provisional features should still document their intended contract, but clients should expect faster iteration.

## 4. Change Rules

Allowed in patch or minor updates:

- adding new tools, resources, payload fields, or examples
- improving descriptions, examples, and output summaries
- tightening validation where previous behavior was ambiguous or unsafe
- expanding structured error data while preserving existing error meaning

Requires explicit release note and migration note:

- renaming tools or resources
- removing documented payload fields
- changing default auth or policy behavior
- changing output semantics in a way that can break existing clients

## 5. Deprecation Policy

Before removing or materially changing a stable tool or resource:

1. mark it as deprecated in docs and release notes
2. keep the older surface available for at least one minor release when feasible
3. provide the preferred replacement and any key migration differences

## 6. Error Contract Expectations

HocusPocus should distinguish at least these error families in a stable way:

- validation errors
- policy or permission errors
- authentication or authorization errors
- runtime Houdini failures
- unsupported or unavailable operation errors

Even where specific numeric codes evolve, the high-level family and intent should remain clear and machine-interpretable.

## 7. Release Validation Rule

A build should not be treated as release-ready until:

- the package installs cleanly
- Houdini auto-start works
- the live smoke script passes against a real Houdini session
- the installed package behavior matches the committed branch state

See [release-validation.md](C:\Users\jujun\Documents\Source\Houdini\HocusPocus_mcp\docs\release-validation.md).

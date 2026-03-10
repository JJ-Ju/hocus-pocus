# HocusPocus Panel Terminal Design

Status: initial design

Purpose:

- define a lightweight path toward launching agent-oriented terminal workflows from inside Houdini without destabilizing the core MCP runtime

## 1. Design Goal

The in-Houdini operator panel should eventually be able to launch a controlled terminal or agent session that inherits the Houdini environment and can talk to the local HocusPocus MCP server.

This is intended to support workflows such as:

- launching Codex CLI in the current project directory
- launching a shell with Houdini-aware environment variables already present
- copying or pre-populating the current MCP endpoint and bearer token

## 2. Constraints

- the default MCP server must remain usable without any embedded terminal feature
- process launch should stay behind existing policy controls
- terminal integration should not block or destabilize the UI-thread execution lane
- the first usable version should prefer safe external process launch over embedding a full terminal emulator widget

## 3. Recommended Implementation Stages

### Stage A. Launch Helpers

- add panel actions to:
  - copy endpoint
  - copy token
  - copy a prebuilt Codex MCP config snippet
  - open a shell or terminal in the current working directory

This gives a practical bridge without embedding terminal IO into the panel.

### Stage B. Controlled External Agent Launch

- add a panel action to launch an agent CLI such as Codex with:
  - explicit working directory
  - inherited Houdini environment
  - MCP endpoint and token available through environment variables

This should only be available when policy allows process launching.

### Stage C. Embedded Terminal View

- evaluate embedding a terminal component in the panel only after stages A and B are stable
- the embedded view should remain optional and should not become a hard dependency for the server package

## 4. Policy Model

Terminal or agent launch should depend on explicit policy support, for example:

- current default:
  - no process launch from the panel
- future explicit enablement:
  - `launch_processes`
  - `run_code`

The panel should expose disabled state clearly rather than failing silently.

## 5. Operational Notes

- the panel should never require the terminal feature to remain usable
- launch failures should appear in the panel diagnostics area
- the operator should be able to copy connection details manually even if launch is disabled

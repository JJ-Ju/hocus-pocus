> **Status: audit record.** HocusPocus 2.1 stream B (`docs/redesign/plan-2.1.md` §3), written against `release/2.1` at `b6a5b53` plus the stream B commits, 2026-10-24. See [`../README.md`](../README.md).

# 27: Linux and macOS portability audit

**Scope.** Every place in `src/hocuspocus/` that touches paths, the state dir, Houdini pref
dirs, the Houdini install and its executables, process launch, signals, lifetime and
termination, the instance registry and its file handling, the SQLite ledger, file
permissions, line endings, case sensitivity, and the CLI's `install-houdini`, `doctor` and
`launch`. The targets are Linux (`~/houdini22.0`, `/opt/hfs22.0.466`) and macOS
(`~/Library/Preferences/houdini/22.0`,
`/Applications/Houdini/Houdini22.0.466/Frameworks/Houdini.framework/Versions/Current/Resources`).

**Method.** This machine runs Windows 11 only, with no Linux or macOS Houdini, no WSL
(`wsl -l -v`: not installed) and no Docker. The audit is a static read of the code. Every
fix comes with unit tests that fake `sys.platform` (and `os` calls) where the code reads
them, plus POSIX-only tests that run for real on the CI runners. The new workflow
`.github/workflows/unit.yml` runs ruff and the unit tier on `ubuntu-latest`,
`macos-latest` and `windows-latest` for Python 3.11, 3.12 and 3.13. Actions are disabled on
the repository, so that matrix has not run yet.

## Findings

Severity: **medium** means wrong behaviour an agent or user would hit; **low** means an edge
case or wrong wording; **info** means it works but differs from Windows, or needs checking
on a real system.

| # | Where | Issue | Severity | Status |
|---|---|---|---|---|
| 1 | `host/registry.py:52` `pid_alive` | On POSIX, `os.kill(pid, 0)` succeeds for a zombie (a process that exited but was not reaped). The bridge never waits on a Houdini it launched, so after that Houdini exits or crashes it stays a zombie child of the bridge, and the bridge takes it for alive. The result is `delivery_unknown` instead of "exited while running" `houdini_offline`, no `instance_lost`, and an orphan launch record that is never reported. | medium | **Fixed** (`78b47b2`). `_is_zombie`: `waitid(P_PID, pid, WEXITED\|WNOHANG\|WNOWAIT)` finds our own exited child and leaves it for `Popen` to reap (Linux; macOS from Python 3.13). The state letter in `/proc/<pid>/stat` finds any zombie (Linux). Tests: `test_host_registry.py::test_pid_alive_treats_an_unreaped_child_as_dead` (real zombie, POSIX CI only), `test_pid_alive_zombie_detection_with_fakes`, `test_proc_state_parses_a_command_name_with_spaces_and_parens`. |
| 2 | `bridge/launch.py:523` `Launcher.wait` | A headless launch accepted only a registration from the spawned pid. On Linux and macOS, `$HFS/bin/hython` is a wrapper script. If it starts `hython-bin` as a child instead of `exec`ing it, the host registers under a pid the launcher never sees, and the launch times out after 90 s. | medium (unverified: depends on SideFX's wrapper) | **Fixed defensively** (`32b67bb`). A new registration also counts when its entry's `launched_by` is this bridge's pid. Only owned launches set that, so a Houdini the user starts meanwhile is still never taken for the launched one (review 10 §1.9). Test: `test_bridge_launch.py::test_headless_launch_accepts_a_wrapper_child_that_names_this_bridge`. |
| 3 | `host/__main__.py:25` | The headless host stopped cleanly on SIGINT and SIGTERM only. On SIGHUP (the terminal of a hand-started `hython -m hocuspocus.host` closing), hython died without removing its registry entry. | low | **Fixed** (`b25a21f`). `SHUTDOWN_SIGNALS` adds SIGHUP, installed where the platform has it. Test: `test_portability.py::test_headless_host_stops_cleanly_on_hangup_where_there_is_one`. |
| 4 | `bridge/ledger.py:142` | The ledger opens with `PRAGMA journal_mode=WAL`. SQLite's WAL mode needs shared memory and does not work on network filesystems, and Linux studios often put `$HOME` (so `~/.local/state/hocuspocus`) on NFS. The ledger falls back to memory on an `sqlite3.Error`, but WAL over NFS can also fail silently: locks not honoured between two bridges on different hosts. | medium (Linux studio setups) | Not fixed. Recommendation: document `HOCUSPOCUS_STATE_DIR` on a local disk for NFS homes, or detect a network filesystem (`statfs` magic on Linux) and use `journal_mode=DELETE`. Needs a real NFS mount to test. |
| 5 | `tools/paths.py:15` `state_dir` | macOS uses the XDG location `~/.local/state/hocuspocus`, not `~/Library/Application Support/HocusPocus`. It works and BIBLE §3.2 says so ("elsewhere"). | info | Kept. Pinned by `test_portability.py::test_state_dir_per_platform`. |
| 6 | `bridge/config.py:148` `same_dir_key`, `host/tools/hip.py:71` `_real` | `os.path.normcase` folds case only on Windows. macOS volumes are case-insensitive by default, so two spellings of one pref dir that differ only in case are not deduplicated (install writes the same file twice, which is harmless). Under `approved_roots`, a path that differs from its root only in case is refused (fails closed). | low | Not fixed. A fix would compare `os.stat` identities (`st_dev`, `st_ino`) where both paths exist. |
| 7 | `host/tools/hip.py:57` `_norm`, and about 16 other `replace("\\", "/")` | On POSIX a backslash is a legal filename character, so a path that contains one is rewritten into a different path. | low | Not fixed (rare in Houdini projects). |
| 8 | `cli.py:316` `package_python_dir` | Splits a package JSON `PYTHONPATH` value on `;` only. A hand-edited JSON on Linux or macOS that uses `:` would be read as one long path, and `doctor` would report `no-python`. `install-houdini` writes a single entry, so its own output is fine. | low | Not fixed. |
| 9 | `cli.py:663` | `doctor`'s "pref dirs disagree" warning talks about the Start menu and `HOME`, which is Windows wording, on every platform. | low (wording) | Not fixed. |
| 10 | `bridge/launch.py:231` | The launch log directory `logs/` is created with the default mode; the host later makes it 0700. It sits inside the state dir, which the ledger (on the bridge's first use of it) and `install-houdini` make 0700. hython's output holds no token, only the registry file's path, so nothing secret leaks even before then. | info | Kept. |
| 11 | `bridge/launch.py:89` `gui_executable` | On macOS the GUI is started as `$HFS/bin/houdinifx`, the binary inside the framework, not the `.app` through `open`. Whether that gets a normal window, Dock entry and licence dialog on macOS is unverified. | info | Needs qualification (below). |
| 12 | `bridge/launch.py:244` | POSIX launches start a new session (`start_new_session=True`), so a launched Houdini outlives the bridge (`launched.outlives_server: true`). On Windows it usually dies with the bridge (BIBLE §15 "Known limitation: launch lifetime"). A GUI launch inherits `DISPLAY` or `WAYLAND_DISPLAY` from the MCP client's environment. A client started outside a desktop session cannot open the GUI, and the launch fails as "exited with code N before HocusPocus registered". | info | Kept. Pinned by `test_portability.py::test_posix_spawn_starts_a_new_session_without_windows_flags`. The BIBLE limitation is Windows-specific and should say so once Linux is qualified. |
| 13 | `host/tools/session.py:180` `_posix_memory` | On macOS there is no `/proc/self/statm`, so `rss_mb` is `null` and only `peak_mb` (`ru_maxrss` in bytes) is reported. Linux reports both (`ru_maxrss` in KiB is scaled). | low | Kept (documented in the code). |
| 14 | `bridge/instances.py:260` `set_name` | A read-modify-write of a host's registry entry with no lock, racing the host's own rewrite. The same on every platform. | low | Not fixed. |
| 15 | `bridge/launch.py:247` | A launched Houdini's `Popen` object is dropped after the wait, so on POSIX an exited Houdini stays a zombie until the bridge starts another process or exits. Finding 1 makes liveness right; the zombie itself is a small resource leak. | low | Not fixed. |
| 16 | Line endings | `.gitattributes` pins `eol=lf` for `*.py`, `*.json`, `*.md`, `*.toml` and `*.yml`. The `tools/list` goldens are single-line JSON compared as bytes. Files the CLI and registry write use `\n` or bytes. `houdini/hocuspocus.json.template` (eol `auto`, CRLF in a Windows checkout) is read with `read_text`, so either ending works. | none | No change. |
| 17 | Permissions | Registry entries are created with `os.open(..., 0o600)` and replaced atomically. `ensure_private_dir` chmods `instances/`, `logs/`, `captures/`, `launches/` and the state dir to 0700 off Windows; on Windows the per-user `%LOCALAPPDATA%` ACL applies. The ledger file gets the umask mode inside the 0700 state dir. | none | Pinned by `test_portability.py::test_private_dir_is_chmod_0700_off_windows` (faked) and `test_private_dir_mode_is_real_on_posix`, plus the existing `test_host_registry.py::test_entry_is_user_private` (POSIX CI only). |
| 18 | Install locations | `/opt/hfs22.*` (a `/opt/hfs22.0` link next to `/opt/hfs22.0.466` resolves to the longer version) and the macOS framework `Resources` dir with its `bin/hython` and `bin/houdinifx`; `houdini` is the fallback when there is no `houdinifx`. | none | Pinned by `test_portability.py::test_candidate_install_globs_per_platform`, `test_detect_hfs_finds_a_macos_framework_install` and `test_detect_hfs_prefers_the_full_linux_version`. |
| 19 | Pref dirs | Linux `~/houdini22.0` and macOS `~/Library/Preferences/houdini/22.0` from `$HOME`, with no Documents variant and no second "without HOME" hython query off Windows. `__HVER__` takes `major.minor` from hython's answer, also on macOS where the answer ends in `/houdini/22.0`. | none | Pinned by `test_default_pref_dirs_linux_and_macos`, `test_install_houdini_on_macos_writes_the_library_pref_dir` and `test_pref_dir_candidates_linux_ask_hython_once_and_expand_hver`. |
| 20 | `tests/integration/test_parity_gui.py` | The GUI tier closes Houdini's own message windows through Win32 `WM_CLOSE` (`_close_native_dialogs`, G5's user-dialog test), and `_kill` on POSIX signals only the pid, not its children. On Linux and macOS the `hou_ui` cases of `test_executor_while_a_user_dialog_is_open` would leave the dialog open. | info (test infrastructure) | Not fixed. A POSIX runner needs an `xdotool` or AppleScript closer. |
| 21 | `tests/unit/test_host_tools.py:391` | The thumbnail test needs Pillow, which the `dev` extra does not install, so it skips on CI everywhere. | low | Not fixed (it is a dev dependency question, not a portability one). |

## What ran where

| Run | Platform | Result |
|---|---|---|
| ruff check, ruff format --check | Windows 11, ruff from the dev venv | clean |
| Unit tier | Windows 11, CPython 3.12.14 (dev venv) | 897 passed, 3 skipped (the POSIX-only permission and zombie tests) |
| Unit tier | Windows 11, CPython 3.13.14 (throwaway venv in the scratch dir) | 896 passed, 4 skipped (the POSIX-only tests and the Pillow test) |
| Unit tier | CPython 3.11 | not run locally (not installed; the CI matrix covers it) |
| Unit tier | Linux, macOS | not run: no WSL, no Docker, Actions disabled. `unit.yml` is ready |
| Integration (hython, fast), GUI parity (`--rungui`), e2e | Windows 11, Houdini 22.0.466 Indie | 538 passed (104 deselected: slow and GUI); 20 passed; 11 passed |
| Any Houdini tier | Linux, macOS | not run: no licensed Houdini on those systems |

## What qualification on real Linux and macOS Houdini still needs

1. **Install and autostart.** `hocuspocus install-houdini --dev` writes `~/houdini22.0/packages/hocuspocus.json` (Linux) or `~/Library/Preferences/houdini/22.0/packages/hocuspocus.json` (macOS). `houdinifx` then runs `uiready.py` and registers `ui: true`. `hocuspocus doctor` gets `hou.homeHoudiniDirectory()` from hython and reports every check as ok.
2. **Headless launch.** `houdini_connect {launch: {mode: headless}}` registers with the spawned pid. Find out whether `bin/hython` `exec`s `hython-bin`, which decides whether finding 2's fallback ever fires. Registry entries are 0600 in 0700 directories.
3. **GUI launch.** On Linux, X11 and Wayland, with the MCP client started inside and outside a desktop session. On macOS: the framework binary against `open -a`, Gatekeeper quarantine on a fresh install, and the login licence dialog.
4. **Lifetime and signals.** A launched Houdini outlives the bridge (new session). SIGTERM and SIGHUP to a headless host remove its registry entry. After `kill -9` of a launched Houdini, the bridge answers `instance_lost` or `houdini_offline`, not `delivery_unknown` (finding 1).
5. **The hython tiers.** Integration fast and `--runslow`, with hython's cwd on `HOUDINI_PATH` as on Windows. The slow tier's child-hython Flipbook and OpenGL renders need a GL context: on a Linux box with no display, check offscreen rendering (EGL), or the `look` draft chain falls through to Karma. Also iconvert and Karma.
6. **The GUI parity tier**, with a POSIX dialog closer (finding 20). Re-measure G5 there, because the event loops differ by platform: on macOS a `hou.ui` dialog may be a native window, and whether Houdini's event-loop callbacks (the executor pump) run inside it must be checked again. Also check whether a parm callback's exception again shows a blocking error window unless it is a `SystemExit`.
7. **The ledger on NFS** (finding 4), and two bridges on one state dir.
8. **The e2e tier**: the stdio bridge spawning hython, two instances, and `hocuspocus launch` outliving its terminal.

## Files

- Fixes: `src/hocuspocus/host/registry.py`, `src/hocuspocus/bridge/launch.py`,
  `src/hocuspocus/host/__main__.py`.
- Tests: `tests/unit/test_portability.py` (new), `tests/unit/test_host_registry.py`,
  `tests/unit/test_bridge_launch.py`.
- CI: `.github/workflows/unit.yml` (new). `ci.yml` keeps its docs-freshness step on
  Windows and Ubuntu with Python 3.12.

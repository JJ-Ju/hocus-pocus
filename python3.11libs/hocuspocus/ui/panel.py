"""Qt operator panel for HocusPocus."""

from __future__ import annotations

import json
from typing import Any

try:  # pragma: no cover - exercised inside Houdini
    from PySide2 import QtCore, QtWidgets
except ImportError:  # pragma: no cover - Houdini may ship PySide6 in future builds
    from PySide6 import QtCore, QtWidgets  # type: ignore[no-redef]

try:  # pragma: no cover - exercised inside Houdini
    import hou  # type: ignore
except ImportError:  # pragma: no cover
    hou = None  # type: ignore

from hocuspocus import startup

_PANEL_INSTANCE: "HocusPocusPanel | None" = None


class HocusPocusPanel(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("HocusPocus")
        self.resize(960, 760)
        self._build_ui()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        button_row = QtWidgets.QHBoxLayout()
        self._start_button = QtWidgets.QPushButton("Start")
        self._stop_button = QtWidgets.QPushButton("Stop")
        self._restart_button = QtWidgets.QPushButton("Restart")
        self._refresh_button = QtWidgets.QPushButton("Refresh")
        self._copy_endpoint_button = QtWidgets.QPushButton("Copy Endpoint")
        self._copy_token_button = QtWidgets.QPushButton("Copy Token")
        for button in (
            self._start_button,
            self._stop_button,
            self._restart_button,
            self._refresh_button,
            self._copy_endpoint_button,
            self._copy_token_button,
        ):
            button_row.addWidget(button)
        button_row.addStretch(1)
        root.addLayout(button_row)

        self._summary_label = QtWidgets.QLabel("")
        self._summary_label.setWordWrap(True)
        root.addWidget(self._summary_label)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        root.addWidget(splitter, 1)

        self._status_view = self._make_json_view("Status")
        self._tasks_view = self._make_json_view("Recent Tasks")
        self._events_view = self._make_json_view("Recent Events")
        self._logs_view = self._make_log_view("Recent Logs")

        for widget in (
            self._status_view["container"],
            self._tasks_view["container"],
            self._events_view["container"],
            self._logs_view["container"],
        ):
            splitter.addWidget(widget)
        splitter.setSizes([240, 180, 180, 160])

        self._start_button.clicked.connect(self._start_server)
        self._stop_button.clicked.connect(self._stop_server)
        self._restart_button.clicked.connect(self._restart_server)
        self._refresh_button.clicked.connect(self.refresh)
        self._copy_endpoint_button.clicked.connect(self._copy_endpoint)
        self._copy_token_button.clicked.connect(self._copy_token)

    def _make_json_view(self, title: str) -> dict[str, Any]:
        container = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(container)
        editor = QtWidgets.QPlainTextEdit()
        editor.setReadOnly(True)
        layout.addWidget(editor)
        return {"container": container, "editor": editor}

    def _make_log_view(self, title: str) -> dict[str, Any]:
        container = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(container)
        editor = QtWidgets.QPlainTextEdit()
        editor.setReadOnly(True)
        layout.addWidget(editor)
        return {"container": container, "editor": editor}

    def refresh(self) -> None:
        payload = startup.panel_snapshot()
        status = payload["status"]
        self._status_view["editor"].setPlainText(json.dumps(status, indent=2, sort_keys=True))
        self._tasks_view["editor"].setPlainText(json.dumps(payload["tasks"], indent=2, sort_keys=True))
        self._events_view["editor"].setPlainText(json.dumps(payload["events"], indent=2, sort_keys=True))
        self._logs_view["editor"].setPlainText("\n".join(payload["logs"]))

        running = bool(status.get("running"))
        endpoint = status.get("mcpUrl", "")
        profile = status.get("policyProfile", "unknown")
        dispatcher = status.get("dispatcherMode", "inactive")
        self._summary_label.setText(
            f"Running: {running} | Profile: {profile} | Dispatcher: {dispatcher} | Endpoint: {endpoint}"
        )
        self._start_button.setEnabled(not running)
        self._stop_button.setEnabled(running)
        self._restart_button.setEnabled(running)
        self._copy_token_button.setEnabled(bool(status.get("token")))

    def _start_server(self) -> None:
        startup.start_server()
        self.refresh()

    def _stop_server(self) -> None:
        startup.stop_server()
        self.refresh()

    def _restart_server(self) -> None:
        startup.restart_server()
        self.refresh()

    def _copy_endpoint(self) -> None:
        QtWidgets.QApplication.clipboard().setText(startup.server_status().get("mcpUrl", ""))

    def _copy_token(self) -> None:
        QtWidgets.QApplication.clipboard().setText(startup.server_status().get("token", ""))

    def closeEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802
        global _PANEL_INSTANCE
        self._timer.stop()
        _PANEL_INSTANCE = None
        super().closeEvent(event)


def show_panel() -> HocusPocusPanel:
    global _PANEL_INSTANCE
    if _PANEL_INSTANCE is not None:
        _PANEL_INSTANCE.show()
        _PANEL_INSTANCE.raise_()
        _PANEL_INSTANCE.activateWindow()
        _PANEL_INSTANCE.refresh()
        return _PANEL_INSTANCE

    parent = None
    if hou is not None and hou.isUIAvailable():
        try:
            parent = hou.qt.mainWindow()
        except Exception:
            parent = None
    _PANEL_INSTANCE = HocusPocusPanel(parent)
    _PANEL_INSTANCE.show()
    return _PANEL_INSTANCE

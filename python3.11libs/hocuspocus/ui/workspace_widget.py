"""Reusable Houdini approval widget for HocusScript source workspaces."""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - exercised inside Houdini
    from PySide2 import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtWidgets  # type: ignore[no-redef]

from hocuspocus import startup

_USER_ROLE = int(QtCore.Qt.UserRole)


class WorkspaceApprovalWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._external_roots: dict[str, str] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(self._project_group(), 3)
        root.addWidget(self._grant_group(), 2)
        self._status = QtWidgets.QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

    def _project_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Host-approved HocusScript projects")
        layout = QtWidgets.QVBoxLayout(group)
        self._projects = QtWidgets.QTreeWidget()
        self._projects.setHeaderLabels(
            ["Label", "Project ID", "Root", "Language", "Authority"]
        )
        self._projects.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._projects.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self._projects)
        row = QtWidgets.QHBoxLayout()
        for label, callback, attribute in (
            ("Add Project…", self._add_project, None),
            ("Reapprove", self._reapprove, "_reapprove_button"),
            ("Remove", self._remove_project, "_remove_button"),
            ("Refresh", self.refresh, None),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
            if attribute is not None:
                setattr(self, attribute, button)
        row.addStretch(1)
        layout.addLayout(row)
        return group

    def _grant_group(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Connection/session grant")
        layout = QtWidgets.QGridLayout(group)
        layout.addWidget(QtWidgets.QLabel("Session"), 0, 0)
        self._sessions = QtWidgets.QComboBox()
        layout.addWidget(self._sessions, 0, 1, 1, 4)
        self._read = QtWidgets.QCheckBox("Source read")
        self._read.setChecked(True)
        self._write = QtWidgets.QCheckBox("Source write")
        self._lock = QtWidgets.QCheckBox("Generated lock")
        self._external = QtWidgets.QCheckBox("External read")
        for column, widget in enumerate(
            (self._read, self._write, self._lock, self._external), start=1
        ):
            layout.addWidget(widget, 1, column)
        layout.addWidget(QtWidgets.QLabel("Permissions"), 1, 0)

        self._persistent = QtWidgets.QCheckBox("Persist for this bearer principal")
        self._persistent.toggled.connect(self._persistence_changed)
        layout.addWidget(self._persistent, 2, 1, 1, 2)
        layout.addWidget(QtWidgets.QLabel("Expiry (hours)"), 2, 3)
        self._expiry = QtWidgets.QSpinBox()
        self._expiry.setRange(1, 24 * 365)
        self._expiry.setValue(8)
        layout.addWidget(self._expiry, 2, 4)
        self._until_revoked = QtWidgets.QCheckBox("Until explicitly revoked")
        self._until_revoked.setEnabled(False)
        self._until_revoked.toggled.connect(self._until_revoked_changed)
        layout.addWidget(self._until_revoked, 3, 1, 1, 2)

        self._external_summary = QtWidgets.QLabel("No external roots approved.")
        self._external_summary.setWordWrap(True)
        layout.addWidget(self._external_summary, 4, 1, 1, 3)
        external_button = QtWidgets.QPushButton("Set External Root…")
        external_button.clicked.connect(self._set_external_root)
        layout.addWidget(external_button, 4, 4)

        grant_button = QtWidgets.QPushButton("Grant")
        grant_button.clicked.connect(self._grant_project)
        revoke_button = QtWidgets.QPushButton("Revoke")
        revoke_button.clicked.connect(self._revoke_project)
        layout.addWidget(grant_button, 5, 3)
        layout.addWidget(revoke_button, 5, 4)
        return group

    def refresh(self) -> None:
        snapshot = startup.workspace_snapshot()
        selected_id = self._selected_project_id()
        self._projects.clear()
        for project in snapshot.get("projects", []):
            item = QtWidgets.QTreeWidgetItem(
                [
                    str(project.get("label", "")),
                    str(project.get("projectId", "")),
                    str(project.get("root", "")),
                    str(project.get("languageVersion", "")),
                    _project_authority_label(project),
                ]
            )
            item.setData(0, _USER_ROLE, project)
            self._projects.addTopLevelItem(item)
            if project.get("projectId") == selected_id:
                self._projects.setCurrentItem(item)
        self._projects.resizeColumnToContents(0)
        self._projects.resizeColumnToContents(1)
        self._sessions.clear()
        for session in snapshot.get("sessions", []):
            client = session.get("clientInfo", {})
            label = client.get("name") or "MCP client"
            session_id = str(session.get("sessionId", ""))
            self._sessions.addItem(f"{label} — {session_id[-12:]}", session_id)
        self._status.setText(
            f"{len(snapshot.get('projects', []))} approved projects, "
            f"{len(snapshot.get('sessions', []))} active sessions, "
            f"{len(snapshot.get('grants', []))} grants."
        )
        self._selection_changed()

    def _add_project(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Approve HocusScript Project Directory"
        )
        if not directory:
            return
        self._call(lambda: startup.register_workspace_project(directory))

    def _reapprove(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        self._call(
            lambda: startup.register_workspace_project(
                str(project["root"]),
                label=str(project.get("label", "")),
                reapprove=True,
            )
        )

    def _remove_project(self) -> None:
        project_id = self._selected_project_id()
        if project_id is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Remove Project Approval",
            "Remove this project from the host registry and invalidate its access?",
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self._call(lambda: startup.remove_workspace_project(project_id))

    def _grant_project(self) -> None:
        project_id = self._selected_project_id()
        if project_id is None:
            return
        persistent = self._persistent.isChecked()
        session_id = None if persistent else self._sessions.currentData()
        if not persistent and not session_id:
            self._show_error("Select an active MCP session or choose explicit persistence.")
            return
        grants = ["source_read"]
        for checked, name in (
            (self._write.isChecked(), "source_write"),
            (self._lock.isChecked(), "generated_lock"),
            (self._external.isChecked(), "external_read"),
        ):
            if checked:
                grants.append(name)
        if self._external.isChecked() and not self._external_roots:
            self._show_error("External read requires at least one separately selected root.")
            return
        self._call(
            lambda: startup.grant_workspace_project(
                project_id,
                session_id=str(session_id) if session_id else None,
                grants=tuple(grants),
                external_roots=dict(self._external_roots),
                persistent=persistent,
                expires_in_seconds=(
                    None
                    if self._until_revoked.isChecked()
                    else float(self._expiry.value() * 60 * 60)
                ),
                until_revoked=self._until_revoked.isChecked(),
            )
        )

    def _revoke_project(self) -> None:
        project_id = self._selected_project_id()
        if project_id is None:
            return
        persistent = self._persistent.isChecked()
        session_id = None if persistent else self._sessions.currentData()
        self._call(
            lambda: startup.revoke_workspace_project(
                project_id,
                session_id=str(session_id) if session_id else None,
                persistent=persistent,
            )
        )

    def _set_external_root(self) -> None:
        project = self._selected_project()
        if project is None:
            return
        aliases = [
            str(item.get("alias"))
            for item in project.get("externalAliases", [])
            if isinstance(item, dict) and item.get("alias")
        ]
        if not aliases:
            self._show_error("The selected project declares no external aliases.")
            return
        alias, accepted = QtWidgets.QInputDialog.getItem(
            self, "External Alias", "Alias", aliases, 0, False
        )
        if not accepted:
            return
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, f"Approve read-only root for {alias}"
        )
        if directory:
            self._external_roots[str(alias)] = directory
            self._refresh_external_summary()

    def _selection_changed(self) -> None:
        self._external_roots.clear()
        self._refresh_external_summary()
        project = self._selected_project()
        mutable = project is not None and not project.get("configOwned", False)
        self._reapprove_button.setEnabled(mutable)
        self._remove_button.setEnabled(mutable)

    def _persistence_changed(self, persistent: bool) -> None:
        self._sessions.setEnabled(not persistent)
        self._until_revoked.setEnabled(persistent)
        if not persistent:
            self._until_revoked.setChecked(False)
        self._expiry.setEnabled(not self._until_revoked.isChecked())

    def _until_revoked_changed(self, until_revoked: bool) -> None:
        self._expiry.setEnabled(not until_revoked)

    def _selected_project(self) -> dict[str, Any] | None:
        items = self._projects.selectedItems()
        if not items:
            return None
        value = items[0].data(0, _USER_ROLE)
        return value if isinstance(value, dict) else None

    def _selected_project_id(self) -> str | None:
        project = self._selected_project()
        if project is None:
            return None
        value = project.get("projectId")
        return str(value) if value else None

    def _refresh_external_summary(self) -> None:
        if not self._external_roots:
            self._external_summary.setText("No external roots approved.")
            return
        self._external_summary.setText(
            ", ".join(f"{alias}: {root}" for alias, root in self._external_roots.items())
        )

    def _call(self, callback) -> None:
        try:
            callback()
        except Exception as exc:
            self._show_error(f"{type(exc).__name__}: {exc}")
            return
        self.refresh()

    def _show_error(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "HocusPocus Workspace Approval", message)


__all__ = ["WorkspaceApprovalWidget"]


def _project_authority_label(project: dict[str, Any]) -> str:
    if project.get("configOwned"):
        return "configured — restart to change"
    if project.get("requiresReapproval"):
        return "reapproval required"
    return "approved"

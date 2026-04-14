import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QFileDialog, QMessageBox,
    QTabWidget, QWidget, QLabel, QLineEdit, QApplication,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor


def _fmt(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class StatsDialog(QDialog):
    """
    Statistics and data-management dialog.

    Parameters
    ----------
    persistence : PersistenceManager
    tracker     : TimeTracker | None
    """

    def __init__(self, persistence, tracker=None, parent=None):
        super().__init__(parent)
        self._db      = persistence
        self._tracker = tracker
        self.setWindowTitle("Time Tracker – Statistics")
        self.setMinimumSize(800, 560)
        self._build_ui()
        self._load_data()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Projects tab ──────────────────────────────────────────────────────
        proj_tab    = QWidget()
        proj_layout = QVBoxLayout(proj_tab)

        # Barra de filtro
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("🔍"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by name or path…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._filter_projects)
        filter_row.addWidget(self._filter_edit)
        proj_layout.addLayout(filter_row)

        self._proj_tbl = QTableWidget(0, 5)
        self._proj_tbl.setHorizontalHeaderLabels(
            ["Project Name", "Path", "Total Time", "Sessions", "Last Access"]
        )
        hdr = self._proj_tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._proj_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self._proj_tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self._proj_tbl.setSelectionMode(QTableWidget.SingleSelection)
        self._proj_tbl.setAlternatingRowColors(True)
        self._proj_tbl.verticalHeader().setVisible(False)
        self._proj_tbl.setSortingEnabled(True)
        self._proj_tbl.itemSelectionChanged.connect(self._on_proj_selection)
        self._proj_tbl.itemDoubleClicked.connect(self._copy_project_time)
        proj_layout.addWidget(self._proj_tbl)

        # Action bar – Projects
        proj_actions = QHBoxLayout()

        self._lbl_proj_total = QLabel("")
        self._lbl_proj_total.setStyleSheet("color:#555; font-size:11px;")
        proj_actions.addWidget(self._lbl_proj_total)
        proj_actions.addStretch()

        self._btn_copy_time = QPushButton("📋 Copy Time")
        self._btn_copy_time.setToolTip(
            "Copies the total time of the selected project to the clipboard."
        )
        self._btn_copy_time.setEnabled(False)
        self._btn_copy_time.clicked.connect(self._copy_project_time)
        proj_actions.addWidget(self._btn_copy_time)

        self._btn_reset_proj = QPushButton("↺  Reset Time")
        self._btn_reset_proj.setToolTip(
            "Resets the time counter of the selected project to 00:00:00.\n"
            "The project and its sessions are NOT removed."
        )
        self._btn_reset_proj.setEnabled(False)
        self._btn_reset_proj.clicked.connect(self._reset_project_time)
        proj_actions.addWidget(self._btn_reset_proj)

        self._btn_del_proj = QPushButton("🗑  Delete Record")
        self._btn_del_proj.setToolTip(
            "Removes the selected project and all its sessions from the database.\n"
            "This action cannot be undone."
        )
        self._btn_del_proj.setEnabled(False)
        self._btn_del_proj.clicked.connect(self._delete_project)
        proj_actions.addWidget(self._btn_del_proj)

        proj_layout.addLayout(proj_actions)
        tabs.addTab(proj_tab, "Projects")

        # ── Sessions tab ──────────────────────────────────────────────────────
        sess_tab    = QWidget()
        sess_layout = QVBoxLayout(sess_tab)

        self._sess_tbl = QTableWidget(0, 5)
        self._sess_tbl.setHorizontalHeaderLabels(
            ["Project", "Start", "End", "Duration", "Recovered"]
        )
        shdr = self._sess_tbl.horizontalHeader()
        shdr.setSectionResizeMode(0, QHeaderView.Stretch)
        shdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        shdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        shdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        shdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._sess_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self._sess_tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self._sess_tbl.setSelectionMode(QTableWidget.SingleSelection)
        self._sess_tbl.setAlternatingRowColors(True)
        self._sess_tbl.verticalHeader().setVisible(False)
        self._sess_tbl.setSortingEnabled(True)
        self._sess_tbl.itemSelectionChanged.connect(self._on_sess_selection)
        sess_layout.addWidget(self._sess_tbl)

        sess_actions = QHBoxLayout()

        self._lbl_sess_total = QLabel("")
        self._lbl_sess_total.setStyleSheet("color:#555; font-size:11px;")
        sess_actions.addWidget(self._lbl_sess_total)
        sess_actions.addStretch()

        self._btn_del_sess = QPushButton("🗑  Delete Session")
        self._btn_del_sess.setToolTip(
            "Removes the selected session and recalculates the total time of the project\n"
            "based on the remaining sessions."
        )
        self._btn_del_sess.setEnabled(False)
        self._btn_del_sess.clicked.connect(self._delete_session)
        sess_actions.addWidget(self._btn_del_sess)

        sess_layout.addLayout(sess_actions)
        tabs.addTab(sess_tab, "Session History")

        root.addWidget(tabs)

        # ── bottom bar ────────────────────────────────────────────────────────
        bottom = QHBoxLayout()

        self._lbl_grand_total = QLabel("")
        self._lbl_grand_total.setStyleSheet(
            "font-weight:600; color:#1a3a5c; font-size:12px; padding:2px 6px;"
        )
        bottom.addWidget(self._lbl_grand_total)
        bottom.addStretch()

        btn_refresh = QPushButton("↻  Update")
        btn_refresh.setToolTip("Reloads the data from the database.")
        btn_refresh.clicked.connect(self._load_data)
        bottom.addWidget(btn_refresh)

        btn_csv = QPushButton("Export CSV")
        btn_csv.clicked.connect(self._export_csv)
        bottom.addWidget(btn_csv)

        btn_json = QPushButton("Export JSON")
        btn_json.clicked.connect(self._export_json)
        bottom.addWidget(btn_json)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)

        root.addLayout(bottom)

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_data(self):
        self._load_projects()
        self._load_sessions()
        self._update_grand_total()

    def _load_projects(self):
        selected_path = self._selected_project_path()
        self._all_projects = self._db.get_all_projects()   # cache para filtro
        active_key = self._tracker.project_key if self._tracker else None

        self._proj_tbl.setSortingEnabled(False)
        self._proj_tbl.setRowCount(len(self._all_projects))
        for r, p in enumerate(self._all_projects):
            self._set_project_row(r, p, active_key)

        total_secs = sum(p["total_seconds"] for p in self._all_projects)
        self._lbl_proj_total.setText(
            f"{len(self._all_projects)} project(s) · Total accumulated: {_fmt(total_secs)}"
        )

        self._btn_reset_proj.setEnabled(False)
        self._btn_del_proj.setEnabled(False)
        self._btn_copy_time.setEnabled(False)
        self._proj_tbl.setSortingEnabled(True)

        if selected_path:
            for r in range(self._proj_tbl.rowCount()):
                item = self._proj_tbl.item(r, 0)
                if item and item.data(Qt.UserRole) == selected_path:
                    self._proj_tbl.selectRow(r)
                    break

        # Reaplicar filtro se houver texto
        if self._filter_edit.text():
            self._filter_projects(self._filter_edit.text())

    def _set_project_row(self, r, p, active_key):
        name_item = QTableWidgetItem(p["project_name"] or "—")
        name_item.setData(Qt.UserRole, p["project_path"])

        if p["project_path"] == active_key:
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
            name_item.setToolTip("Project in active tracking")

        self._proj_tbl.setItem(r, 0, name_item)
        self._proj_tbl.setItem(r, 1, QTableWidgetItem(p["project_path"]))

        ti = QTableWidgetItem(_fmt(p["total_seconds"]))
        ti.setTextAlignment(Qt.AlignCenter)
        # Dado numérico para ordenação correta
        ti.setData(Qt.UserRole + 1, p["total_seconds"])
        self._proj_tbl.setItem(r, 2, ti)

        sc = QTableWidgetItem(str(p["session_count"]))
        sc.setTextAlignment(Qt.AlignCenter)
        self._proj_tbl.setItem(r, 3, sc)

        self._proj_tbl.setItem(
            r, 4, QTableWidgetItem(str(p["last_accessed"])[:16])
        )

    def _load_sessions(self):
        selected_id = self._selected_session_id()
        sessions = self._db.get_sessions()

        self._sess_tbl.setSortingEnabled(False)
        self._sess_tbl.setRowCount(len(sessions))

        for r, s in enumerate(sessions):
            name = s["project_name"] or os.path.basename(s["project_path"])
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, s["id"])

            if s["recovered"]:
                name_item.setForeground(QColor("#c0392b"))
                name_item.setToolTip("Session recovered after QGIS crash")

            self._sess_tbl.setItem(r, 0, name_item)
            self._sess_tbl.setItem(r, 1, QTableWidgetItem(str(s["start_time"])[:19]))
            self._sess_tbl.setItem(
                r, 2, QTableWidgetItem(str(s["end_time"] or "—")[:19])
            )

            di = QTableWidgetItem(_fmt(s["duration_seconds"]))
            di.setTextAlignment(Qt.AlignCenter)
            self._sess_tbl.setItem(r, 3, di)

            rec_item = QTableWidgetItem("✓" if s["recovered"] else "")
            rec_item.setTextAlignment(Qt.AlignCenter)
            self._sess_tbl.setItem(r, 4, rec_item)

        total_secs = sum(s["duration_seconds"] for s in sessions)
        self._lbl_sess_total.setText(
            f"{len(sessions)} session(s) · Total sum: {_fmt(total_secs)}"
        )

        self._btn_del_sess.setEnabled(False)
        self._sess_tbl.setSortingEnabled(True)

        if selected_id is not None:
            for r in range(self._sess_tbl.rowCount()):
                item = self._sess_tbl.item(r, 0)
                if item and item.data(Qt.UserRole) == selected_id:
                    self._sess_tbl.selectRow(r)
                    break

    def _update_grand_total(self):
        projects = self._db.get_all_projects()
        grand = sum(p["total_seconds"] for p in projects)
        count = len(projects)
        self._lbl_grand_total.setText(
            f"⏱  Total time recorded: {_fmt(grand)}  ({count} project(s))"
        )

    # ── filtro de projetos ────────────────────────────────────────────────────

    def _filter_projects(self, text: str):
        """Mostra/oculta linhas conforme o texto no campo de filtro."""
        text = text.strip().lower()
        for r in range(self._proj_tbl.rowCount()):
            name_item = self._proj_tbl.item(r, 0)
            path_item = self._proj_tbl.item(r, 1)
            if not name_item:
                continue
            name = (name_item.text() or "").lower()
            path = (path_item.text() if path_item else "").lower()
            visible = (not text) or (text in name) or (text in path)
            self._proj_tbl.setRowHidden(r, not visible)

    # ── selection helpers ─────────────────────────────────────────────────────

    def _selected_project_path(self):
        row = self._proj_tbl.currentRow()
        if row < 0:
            return None
        item = self._proj_tbl.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _selected_session_id(self):
        row = self._sess_tbl.currentRow()
        if row < 0:
            return None
        item = self._sess_tbl.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _on_proj_selection(self):
        has_sel = len(self._proj_tbl.selectedItems()) > 0
        self._btn_reset_proj.setEnabled(has_sel)
        self._btn_del_proj.setEnabled(has_sel)
        self._btn_copy_time.setEnabled(has_sel)

    def _on_sess_selection(self):
        self._btn_del_sess.setEnabled(len(self._sess_tbl.selectedItems()) > 0)

    # ── copiar tempo ──────────────────────────────────────────────────────────

    def _copy_project_time(self, *_):
        """Copia tempo total do projeto selecionado para o clipboard."""
        row = self._proj_tbl.currentRow()
        if row < 0:
            return
        time_item = self._proj_tbl.item(row, 2)
        if not time_item:
            return
        QApplication.clipboard().setText(time_item.text())

    # ── active-project guard ──────────────────────────────────────────────────

    def _is_active_project(self, project_path: str) -> bool:
        if not self._tracker:
            return False
        return (
            self._tracker.project_key == project_path
            and self._tracker.state.value != "stopped"
        )

    # ── tracker sync helper ───────────────────────────────────────────────────

    def _sync_tracker_if_needed(self, affected_project_path: str):
        if not self._tracker:
            return
        if self._tracker.project_key == affected_project_path:
            self._tracker.sync_base_seconds()

    # ── management actions ────────────────────────────────────────────────────

    def _reset_project_time(self):
        project_path = self._selected_project_path()
        if not project_path:
            return

        if self._is_active_project(project_path):
            QMessageBox.warning(
                self,
                "Project in Active Tracking",
                "This project is currently being tracked.\n\n"
                "Please stop the tracking before resetting the time.",
            )
            return

        name_item = self._proj_tbl.item(self._proj_tbl.currentRow(), 0)
        project_name = name_item.text() if name_item else project_path

        reply = QMessageBox.question(
            self,
            "Reset Project Time",
            f"Do you want to reset the accumulated time for the project:\n\n"
            f"<b>{project_name}</b>\n\n"
            f"The project and its sessions will be kept. "
            f"Only the time counter will be reset to 00:00:00.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        self._db.reset_project_seconds(project_path)
        self._sync_tracker_if_needed(project_path)
        self._load_data()

    def _delete_project(self):
        project_path = self._selected_project_path()
        if not project_path:
            return

        if self._is_active_project(project_path):
            QMessageBox.warning(
                self,
                "Project in Active Tracking",
                "This project is currently being tracked.\n\n"
                "Please stop the tracking before deleting the record.",
            )
            return

        row = self._proj_tbl.currentRow()
        project_name  = self._proj_tbl.item(row, 0).text()
        total_time    = self._proj_tbl.item(row, 2).text()
        session_count = self._proj_tbl.item(row, 3).text()

        reply = QMessageBox.warning(
            self,
            "Delete Project Record",
            f"Are you sure you want to permanently delete the record for:\n\n"
            f"<b>{project_name}</b>\n"
            f"Accumulated time: {total_time}\n"
            f"NNumber of sessions: {session_count}\n\n"
            f"<b>All sessions for this project will be removed.\n"
            f"This action cannot be undone.</b>\n\n"
            f"The QGIS project file will NOT be affected.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        self._db.delete_project(project_path)
        self._sync_tracker_if_needed(project_path)
        self._load_data()

    def _delete_session(self):
        row = self._sess_tbl.currentRow()
        if row < 0:
            return

        name_item  = self._sess_tbl.item(row, 0)
        session_id = name_item.data(Qt.UserRole)
        proj_name  = name_item.text()
        start_time = self._sess_tbl.item(row, 1).text()
        duration   = self._sess_tbl.item(row, 3).text()

        reply = QMessageBox.question(
            self,
            "Remove Session",
            f"Do you want to remove this session?\n\n"
            f"Project: <b>{proj_name}</b>\n"
            f"Start: {start_time}\n"
            f"Duration: {duration}\n\n"
            f"The total time for the project will be recalculated "
            f"based on the remaining sessions.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        self._db.delete_session(session_id)
        if self._tracker and self._tracker.project_key:
            self._tracker.sync_base_seconds()
        self._load_data()

    # ── export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV",
            os.path.expanduser("~/time_tracker.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            self._db.export_csv(path)
            QMessageBox.information(self, "Export CSV", f"File saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error Exporting", str(exc))

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export JSON",
            os.path.expanduser("~/time_tracker.json"),
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            self._db.export_json(path)
            QMessageBox.information(self, "Export JSON", f"File saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error Exporting JSON", str(exc))
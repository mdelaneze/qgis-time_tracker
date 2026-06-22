"""
StatsDialog – statistics and data-management dialog.

"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# ── Qt5 / Qt6 enum compat ──────────────────────────────────────────────────────


def _qt(root, *chain, fallback=None):
    obj = root
    for attr in chain:
        obj = getattr(obj, attr, None)
        if obj is None:
            return fallback
    return obj if obj is not None else fallback


def _user_role():
    return _qt(Qt, "ItemDataRole", "UserRole") or _qt(Qt, "UserRole")


def _align_center():
    return _qt(Qt, "AlignmentFlag", "AlignCenter") or _qt(Qt, "AlignCenter")


def _align_right():
    return _qt(Qt, "AlignmentFlag", "AlignRight") or _qt(Qt, "AlignRight")


def _no_edit():
    if hasattr(QAbstractItemView, "NoEditTriggers"):
        return QAbstractItemView.NoEditTriggers
    if hasattr(QAbstractItemView, "EditTrigger"):
        return QAbstractItemView.EditTrigger.NoEditTriggers
    raise AttributeError("Could not resolve NoEditTriggers")


def _select_rows():
    return _qt(QAbstractItemView, "SelectionBehavior", "SelectRows") or _qt(
        QTableWidget, "SelectRows"
    )


def _single_sel():
    return _qt(QAbstractItemView, "SelectionMode", "SingleSelection") or _qt(
        QTableWidget, "SingleSelection"
    )


def _resize_contents():
    return _qt(QHeaderView, "ResizeMode", "ResizeToContents") or _qt(
        QHeaderView, "ResizeToContents"
    )


def _stretch():
    return _qt(QHeaderView, "ResizeMode", "Stretch") or _qt(QHeaderView, "Stretch")


def _interactive():
    return _qt(QHeaderView, "ResizeMode", "Interactive") or _qt(
        QHeaderView, "Interactive"
    )


def _mb_yes():
    return _qt(QMessageBox, "StandardButton", "Yes") or _qt(QMessageBox, "Yes")


def _mb_cancel():
    return _qt(QMessageBox, "StandardButton", "Cancel") or _qt(QMessageBox, "Cancel")


def _mb_warning():
    return _qt(QMessageBox, "Icon", "Warning") or _qt(QMessageBox, "Warning")


def _mb_question():
    return _qt(QMessageBox, "Icon", "Question") or _qt(QMessageBox, "Question")


# ── helpers ─────────────────────────────────────────────────────────────────────


def _fmt(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_short(secs: int) -> str:
    """Format as Xh Ym for compact display."""
    h, rem = divmod(int(secs), 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


# ── summary tab helpers ─────────────────────────────────────────────────────────

_HEAT_COLOURS = [
    "#ebedf0",  # 0  – no activity
    "#9be9a8",  # 1  – light
    "#40c463",  # 2  – moderate
    "#30a14e",  # 3  – active
    "#216e39",  # 4  – very active
]


def _heat_colour(secs: int) -> str:
    if secs <= 0:
        return _HEAT_COLOURS[0]
    h = secs / 3600
    if h < 1:
        return _HEAT_COLOURS[1]
    if h < 3:
        return _HEAT_COLOURS[2]
    if h < 6:
        return _HEAT_COLOURS[3]
    return _HEAT_COLOURS[4]


# ── dialog ─────────────────────────────────────────────────────────────────────


class StatsDialog(QDialog):

    def __init__(self, persistence, tracker=None, parent=None):
        super().__init__(parent)
        self._db = persistence
        self._tracker = tracker
        self.setWindowTitle("Time Tracker – Statistics")
        self.setMinimumSize(860, 600)
        self._build_ui()
        self._load_data()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        tabs = QTabWidget()

        # ── Summary tab ───────────────────────────────────────────────────────
        tabs.addTab(self._build_summary_tab(), "Summary")

        # ── Projects tab ──────────────────────────────────────────────────────
        tabs.addTab(self._build_projects_tab(), "Projects")

        # ── Sessions tab ──────────────────────────────────────────────────────
        tabs.addTab(self._build_sessions_tab(), "Session History")

        root.addWidget(tabs)

        # ── bottom bar ────────────────────────────────────────────────────────
        bottom = QHBoxLayout()

        self._lbl_grand_total = QLabel("")
        self._lbl_grand_total.setStyleSheet(
            "font-weight:700; color:#1a3a5c; font-size:12px; padding:2px 6px;"
        )
        bottom.addWidget(self._lbl_grand_total)
        bottom.addStretch()

        btn_refresh = QPushButton("↻  Refresh")
        btn_refresh.setToolTip("Reload data from the database.")
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

    # ── Summary tab ───────────────────────────────────────────────────────────

    def _build_summary_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setSpacing(10)

        # KPI cards row
        self._kpi_row = QHBoxLayout()
        self._kpi_row.setSpacing(8)

        self._kpi_today = self._make_kpi("Today", "00:00:00", "#2980b9")
        self._kpi_week = self._make_kpi("This Week", "00:00:00", "#27ae60")
        self._kpi_total = self._make_kpi("All Time", "00:00:00", "#8e44ad")
        self._kpi_streak = self._make_kpi("Day Streak", "0 days", "#e67e22")
        self._kpi_projects = self._make_kpi("Projects", "0", "#16a085")

        for w in [
            self._kpi_today,
            self._kpi_week,
            self._kpi_total,
            self._kpi_streak,
            self._kpi_projects,
        ]:
            self._kpi_row.addWidget(w)

        lay.addLayout(self._kpi_row)

        # Divider
        div = QFrame()
        div.setFrameShape(
            QFrame.Shape.HLine if hasattr(QFrame.Shape, "HLine") else QFrame.HLine
        )
        div.setStyleSheet("color:#ddd;")
        lay.addWidget(div)

        # Activity heatmap (last 12 weeks, Mon–Sun grid)
        lbl_heat = QLabel("Activity – last 12 weeks")
        lbl_heat.setStyleSheet("font-weight:600; color:#444; font-size:11px;")
        lay.addWidget(lbl_heat)

        self._heat_container = QWidget()
        self._heat_container.setFixedHeight(92)
        lay.addWidget(self._heat_container)

        # Recent sessions mini-table
        lbl_recent = QLabel("Recent sessions")
        lbl_recent.setStyleSheet("font-weight:600; color:#444; font-size:11px;")
        lay.addWidget(lbl_recent)

        self._recent_tbl = QTableWidget(0, 4)
        self._recent_tbl.setHorizontalHeaderLabels(
            ["Project", "Start", "Duration", "Rcv"]
        )
        hdr = self._recent_tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, _stretch())
        hdr.setSectionResizeMode(1, _resize_contents())
        hdr.setSectionResizeMode(2, _resize_contents())
        hdr.setSectionResizeMode(3, _resize_contents())
        self._recent_tbl.setEditTriggers(_no_edit())
        self._recent_tbl.setSelectionBehavior(_select_rows())
        self._recent_tbl.setAlternatingRowColors(True)
        self._recent_tbl.verticalHeader().setVisible(False)
        self._recent_tbl.setMaximumHeight(180)
        lay.addWidget(self._recent_tbl)

        lay.addStretch()
        return tab

    def _make_kpi(self, label: str, value: str, accent: str) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame{{background:#fafafa;border:1px solid #e0e0e0;"
            f"border-left:4px solid {accent};"
            f"border-radius:6px;padding:6px 10px;}}"
        )
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        v = QVBoxLayout(card)
        v.setSpacing(2)
        v.setContentsMargins(6, 6, 6, 6)

        lbl_title = QLabel(label)
        lbl_title.setStyleSheet(
            f"font-size:10px;color:#888;font-weight:600;border:none;background:transparent;"
        )
        v.addWidget(lbl_title)

        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(
            f"font-size:16px;font-weight:700;color:{accent};border:none;background:transparent;"
        )
        v.addWidget(lbl_val)

        # Store reference to value label so we can update it
        card._value_label = lbl_val
        return card

    # ── Projects tab ──────────────────────────────────────────────────────────

    def _build_projects_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("🔍"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by name or path…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._filter_projects)
        filter_row.addWidget(self._filter_edit)
        lay.addLayout(filter_row)

        self._proj_tbl = QTableWidget(0, 5)
        self._proj_tbl.setHorizontalHeaderLabels(
            ["Project", "Path", "Total Time", "Sessions", "Last Access"]
        )
        hdr = self._proj_tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, _resize_contents())
        hdr.setSectionResizeMode(1, _stretch())
        hdr.setSectionResizeMode(2, _resize_contents())
        hdr.setSectionResizeMode(3, _resize_contents())
        hdr.setSectionResizeMode(4, _resize_contents())
        self._proj_tbl.setEditTriggers(_no_edit())
        self._proj_tbl.setSelectionBehavior(_select_rows())
        self._proj_tbl.setSelectionMode(_single_sel())
        self._proj_tbl.setAlternatingRowColors(True)
        self._proj_tbl.verticalHeader().setVisible(False)
        self._proj_tbl.setSortingEnabled(True)
        self._proj_tbl.itemSelectionChanged.connect(self._on_proj_selection)
        self._proj_tbl.itemDoubleClicked.connect(self._copy_project_time)
        lay.addWidget(self._proj_tbl)

        # Action bar
        proj_actions = QHBoxLayout()

        self._lbl_proj_total = QLabel("")
        self._lbl_proj_total.setStyleSheet("color:#666; font-size:11px;")
        proj_actions.addWidget(self._lbl_proj_total)
        proj_actions.addStretch()

        self._btn_copy_time = QPushButton("📋  Copy Time")
        self._btn_copy_time.setToolTip(
            "Copy the selected project's total time to the clipboard."
        )
        self._btn_copy_time.setEnabled(False)
        self._btn_copy_time.clicked.connect(self._copy_project_time)
        proj_actions.addWidget(self._btn_copy_time)

        self._btn_reset_proj = QPushButton("↺  Reset Time")
        self._btn_reset_proj.setToolTip(
            "Reset the selected project's time counter to 00:00:00.\n"
            "The project record and its sessions are kept."
        )
        self._btn_reset_proj.setEnabled(False)
        self._btn_reset_proj.clicked.connect(self._reset_project_time)
        proj_actions.addWidget(self._btn_reset_proj)

        self._btn_del_proj = QPushButton("🗑  Delete Record")
        self._btn_del_proj.setToolTip(
            "Permanently remove the selected project and all its sessions.\n"
            "This cannot be undone."
        )
        self._btn_del_proj.setEnabled(False)
        self._btn_del_proj.clicked.connect(self._delete_project)
        proj_actions.addWidget(self._btn_del_proj)

        lay.addLayout(proj_actions)
        return tab

    # ── Sessions tab ──────────────────────────────────────────────────────────

    def _build_sessions_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)

        self._sess_tbl = QTableWidget(0, 5)
        self._sess_tbl.setHorizontalHeaderLabels(
            ["Project", "Start", "End", "Duration", "Rcv"]
        )
        shdr = self._sess_tbl.horizontalHeader()
        shdr.setSectionResizeMode(0, _stretch())
        shdr.setSectionResizeMode(1, _resize_contents())
        shdr.setSectionResizeMode(2, _resize_contents())
        shdr.setSectionResizeMode(3, _resize_contents())
        shdr.setSectionResizeMode(4, _resize_contents())
        self._sess_tbl.setEditTriggers(_no_edit())
        self._sess_tbl.setSelectionBehavior(_select_rows())
        self._sess_tbl.setSelectionMode(_single_sel())
        self._sess_tbl.setAlternatingRowColors(True)
        self._sess_tbl.verticalHeader().setVisible(False)
        self._sess_tbl.setSortingEnabled(True)
        self._sess_tbl.itemSelectionChanged.connect(self._on_sess_selection)
        lay.addWidget(self._sess_tbl)

        sess_actions = QHBoxLayout()

        self._lbl_sess_total = QLabel("")
        self._lbl_sess_total.setStyleSheet("color:#666; font-size:11px;")
        sess_actions.addWidget(self._lbl_sess_total)
        sess_actions.addStretch()

        self._btn_del_sess = QPushButton("🗑  Delete Session")
        self._btn_del_sess.setToolTip(
            "Remove the selected session and recalculate the project total."
        )
        self._btn_del_sess.setEnabled(False)
        self._btn_del_sess.clicked.connect(self._delete_session)
        sess_actions.addWidget(self._btn_del_sess)

        lay.addLayout(sess_actions)
        return tab

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_data(self):
        self._load_summary()
        self._load_projects()
        self._load_sessions()
        self._update_grand_total()

    # ── summary loading ───────────────────────────────────────────────────────

    def _load_summary(self):
        # KPI values
        today_secs = self._db.get_today_seconds()
        if self._tracker and self._tracker.state.value == "running":
            import time as _time

            if self._tracker._session_start_ts is not None:
                today_secs += int(_time.monotonic() - self._tracker._session_start_ts)

        weekly = self._db.get_weekly_totals(weeks=1)
        week_secs = weekly[0]["total_seconds"] if weekly else 0

        all_projects = self._db.get_all_projects()
        total_secs = sum(p["total_seconds"] for p in all_projects)
        proj_count = len(all_projects)
        streak = self._db.get_streak_days()

        self._kpi_today._value_label.setText(_fmt(today_secs))
        self._kpi_week._value_label.setText(_fmt(week_secs))
        self._kpi_total._value_label.setText(_fmt(total_secs))
        self._kpi_streak._value_label.setText(
            f"{streak} day{'s' if streak != 1 else ''}"
        )
        self._kpi_projects._value_label.setText(str(proj_count))

        # Heatmap (last 12 weeks)
        self._build_heatmap()

        # Recent sessions (last 10)
        sessions = self._db.get_sessions()[:10]
        self._recent_tbl.setSortingEnabled(False)
        self._recent_tbl.setRowCount(len(sessions))
        for r, s in enumerate(sessions):
            name = s["project_name"] or os.path.basename(s["project_path"])
            ni = QTableWidgetItem(name)
            if s["recovered"]:
                ni.setForeground(QColor("#c0392b"))
                ni.setToolTip("Recovered after crash")
            self._recent_tbl.setItem(r, 0, ni)
            self._recent_tbl.setItem(r, 1, QTableWidgetItem(str(s["start_time"])[:16]))
            di = QTableWidgetItem(_fmt(s["duration_seconds"]))
            di.setTextAlignment(_align_center())
            self._recent_tbl.setItem(r, 2, di)
            ri = QTableWidgetItem("✓" if s["recovered"] else "")
            ri.setTextAlignment(_align_center())
            self._recent_tbl.setItem(r, 3, ri)
        self._recent_tbl.setSortingEnabled(True)

    def _build_heatmap(self):
        """Build a GitHub-style activity heatmap using coloured QLabel cells."""
        from datetime import date, timedelta

        daily = {
            row["work_date"]: row["total_seconds"]
            for row in self._db.get_daily_totals(84)
        }

        # Clear previous heatmap
        old_lay = self._heat_container.layout()
        if old_lay:
            while old_lay.count():
                item = old_lay.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            try:
                import sip

                sip.delete(old_lay)
            except Exception:
                pass

        grid_lay = QHBoxLayout(self._heat_container)
        grid_lay.setContentsMargins(0, 0, 0, 0)
        grid_lay.setSpacing(2)

        today = date.today()
        # Start on Monday 12 weeks ago
        start = today - timedelta(weeks=12)
        start -= timedelta(days=start.weekday())  # snap to Monday

        current = start
        week_col = QVBoxLayout()
        week_col.setSpacing(2)
        week_col.setContentsMargins(0, 0, 0, 0)

        while current <= today:
            iso = current.isoformat()
            secs = daily.get(iso, 0)
            colour = _heat_colour(secs)

            cell = QLabel()
            cell.setFixedSize(10, 10)
            cell.setStyleSheet(
                f"background:{colour};border-radius:2px;"
                f"border:1px solid rgba(0,0,0,0.08);"
            )
            tip = f"{iso}  {_fmt_short(secs)}" if secs > 0 else iso
            cell.setToolTip(tip)
            week_col.addWidget(cell)

            # After Sunday, start new column
            if current.weekday() == 6:
                grid_lay.addLayout(week_col)
                week_col = QVBoxLayout()
                week_col.setSpacing(2)
                week_col.setContentsMargins(0, 0, 0, 0)

            current += timedelta(days=1)

        if week_col.count() > 0:
            grid_lay.addLayout(week_col)

        grid_lay.addStretch()

        # Legend
        legend = QHBoxLayout()
        legend.setSpacing(4)
        legend.addStretch()
        legend.addWidget(QLabel("Less"))
        for c in _HEAT_COLOURS:
            lc = QLabel()
            lc.setFixedSize(10, 10)
            lc.setStyleSheet(
                f"background:{c};border-radius:2px;border:1px solid rgba(0,0,0,0.1);"
            )
            legend.addWidget(lc)
        legend.addWidget(QLabel("More"))
        grid_lay.addLayout(legend)

    # ── projects loading ──────────────────────────────────────────────────────

    def _load_projects(self):
        selected_path = self._selected_project_path()
        self._all_projects = self._db.get_all_projects()
        active_key = self._tracker.project_key if self._tracker else None

        self._proj_tbl.setSortingEnabled(False)
        self._proj_tbl.setRowCount(len(self._all_projects))
        for r, p in enumerate(self._all_projects):
            self._set_project_row(r, p, active_key)

        total_secs = sum(p["total_seconds"] for p in self._all_projects)
        self._lbl_proj_total.setText(
            f"{len(self._all_projects)} project(s) · Total: {_fmt(total_secs)}"
        )

        self._btn_reset_proj.setEnabled(False)
        self._btn_del_proj.setEnabled(False)
        self._btn_copy_time.setEnabled(False)
        self._proj_tbl.setSortingEnabled(True)

        if selected_path:
            for r in range(self._proj_tbl.rowCount()):
                item = self._proj_tbl.item(r, 0)
                if item and item.data(_user_role()) == selected_path:
                    self._proj_tbl.selectRow(r)
                    break

        if self._filter_edit.text():
            self._filter_projects(self._filter_edit.text())

    def _set_project_row(self, r, p, active_key):
        name_item = QTableWidgetItem(p["project_name"] or "—")
        name_item.setData(_user_role(), p["project_path"])

        if p["project_path"] == active_key:
            f = name_item.font()
            f.setBold(True)
            name_item.setFont(f)
            name_item.setForeground(QColor("#0a3d22"))
            name_item.setToolTip("Currently tracked")

        self._proj_tbl.setItem(r, 0, name_item)
        self._proj_tbl.setItem(r, 1, QTableWidgetItem(p["project_path"]))

        ti = QTableWidgetItem(_fmt(p["total_seconds"]))
        ti.setTextAlignment(_align_center())
        ti.setData(_user_role() + 1, p["total_seconds"])
        self._proj_tbl.setItem(r, 2, ti)

        sc = QTableWidgetItem(str(p["session_count"]))
        sc.setTextAlignment(_align_center())
        self._proj_tbl.setItem(r, 3, sc)

        self._proj_tbl.setItem(r, 4, QTableWidgetItem(str(p["last_accessed"])[:16]))

    # ── sessions loading ──────────────────────────────────────────────────────

    def _load_sessions(self):
        selected_id = self._selected_session_id()
        sessions = self._db.get_sessions()

        self._sess_tbl.setSortingEnabled(False)
        self._sess_tbl.setRowCount(len(sessions))

        for r, s in enumerate(sessions):
            name = s["project_name"] or os.path.basename(s["project_path"])
            name_item = QTableWidgetItem(name)
            name_item.setData(_user_role(), s["id"])

            if s["recovered"]:
                name_item.setForeground(QColor("#c0392b"))
                name_item.setToolTip("Session recovered after QGIS crash")

            self._sess_tbl.setItem(r, 0, name_item)
            self._sess_tbl.setItem(r, 1, QTableWidgetItem(str(s["start_time"])[:19]))
            self._sess_tbl.setItem(
                r, 2, QTableWidgetItem(str(s["end_time"] or "—")[:19])
            )

            di = QTableWidgetItem(_fmt(s["duration_seconds"]))
            di.setTextAlignment(_align_center())
            self._sess_tbl.setItem(r, 3, di)

            ri = QTableWidgetItem("✓" if s["recovered"] else "")
            ri.setTextAlignment(_align_center())
            self._sess_tbl.setItem(r, 4, ri)

        total_secs = sum(s["duration_seconds"] for s in sessions)
        self._lbl_sess_total.setText(
            f"{len(sessions)} session(s) · Total: {_fmt(total_secs)}"
        )

        self._btn_del_sess.setEnabled(False)
        self._sess_tbl.setSortingEnabled(True)

        if selected_id is not None:
            for r in range(self._sess_tbl.rowCount()):
                item = self._sess_tbl.item(r, 0)
                if item and item.data(_user_role()) == selected_id:
                    self._sess_tbl.selectRow(r)
                    break

    def _update_grand_total(self):
        projects = self._db.get_all_projects()
        grand = sum(p["total_seconds"] for p in projects)
        count = len(projects)
        self._lbl_grand_total.setText(
            f"⏱  Total tracked: {_fmt(grand)}  ·  {count} project(s)"
        )

    # ── filter ────────────────────────────────────────────────────────────────

    def _filter_projects(self, text: str):
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
        row = self._proj_tbl.currentRow() if hasattr(self, "_proj_tbl") else -1
        if row < 0:
            return None
        item = self._proj_tbl.item(row, 0)
        return item.data(_user_role()) if item else None

    def _selected_session_id(self):
        row = self._sess_tbl.currentRow() if hasattr(self, "_sess_tbl") else -1
        if row < 0:
            return None
        item = self._sess_tbl.item(row, 0)
        return item.data(_user_role()) if item else None

    def _on_proj_selection(self):
        has = len(self._proj_tbl.selectedItems()) > 0
        self._btn_reset_proj.setEnabled(has)
        self._btn_del_proj.setEnabled(has)
        self._btn_copy_time.setEnabled(has)

    def _on_sess_selection(self):
        self._btn_del_sess.setEnabled(len(self._sess_tbl.selectedItems()) > 0)

    # ── copy time ─────────────────────────────────────────────────────────────

    def _copy_project_time(self, *_):
        row = self._proj_tbl.currentRow()
        if row < 0:
            return
        item = self._proj_tbl.item(row, 2)
        if item:
            QApplication.clipboard().setText(item.text())

    # ── active project guard ──────────────────────────────────────────────────

    def _is_active_project(self, project_path: str) -> bool:
        if not self._tracker:
            return False
        return (
            self._tracker.project_key == project_path
            and self._tracker.state.value != "stopped"
        )

    def _sync_tracker_if_needed(self, project_path: str):
        if self._tracker and self._tracker.project_key == project_path:
            self._tracker.sync_base_seconds()

    # ── management actions ────────────────────────────────────────────────────

    def _reset_project_time(self):
        project_path = self._selected_project_path()
        if not project_path:
            return

        if self._is_active_project(project_path):
            QMessageBox.warning(
                self,
                "Project Currently Tracked",
                "This project is being tracked.\n\n" "Stop tracking before resetting.",
            )
            return

        row = self._proj_tbl.currentRow()
        name = (
            self._proj_tbl.item(row, 0).text()
            if self._proj_tbl.item(row, 0)
            else project_path
        )

        reply = QMessageBox.question(
            self,
            "Reset Project Time",
            f"Reset the accumulated time for:\n\n<b>{name}</b>\n\n"
            f"The project record and its sessions are kept. "
            f"Only the time counter is reset to 00:00:00.",
            _mb_yes() | _mb_cancel(),
            _mb_cancel(),
        )
        if reply != _mb_yes():
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
                "Project Currently Tracked",
                "This project is being tracked.\n\n" "Stop tracking before deleting.",
            )
            return

        row = self._proj_tbl.currentRow()
        project_name = self._proj_tbl.item(row, 0).text()
        total_time = self._proj_tbl.item(row, 2).text()
        session_count = self._proj_tbl.item(row, 3).text()

        reply = QMessageBox.warning(
            self,
            "Delete Project Record",
            f"Permanently delete the record for:\n\n<b>{project_name}</b>\n"
            f"Total time: {total_time}\n"
            f"Sessions: {session_count}\n\n"
            f"<b>All sessions for this project will be removed. "
            f"This cannot be undone.</b>\n\n"
            f"The QGIS project file is not affected.",
            _mb_yes() | _mb_cancel(),
            _mb_cancel(),
        )
        if reply != _mb_yes():
            return

        self._db.delete_project(project_path)
        self._sync_tracker_if_needed(project_path)
        self._load_data()

    def _delete_session(self):
        row = self._sess_tbl.currentRow()
        if row < 0:
            return

        name_item = self._sess_tbl.item(row, 0)
        session_id = name_item.data(_user_role())
        proj_name = name_item.text()
        start_time = self._sess_tbl.item(row, 1).text()
        duration = self._sess_tbl.item(row, 3).text()

        reply = QMessageBox.question(
            self,
            "Remove Session",
            f"Remove this session?\n\n"
            f"Project: <b>{proj_name}</b>\n"
            f"Start: {start_time}\n"
            f"Duration: {duration}\n\n"
            f"The project total will be recalculated from remaining sessions.",
            _mb_yes() | _mb_cancel(),
            _mb_cancel(),
        )
        if reply != _mb_yes():
            return

        self._db.delete_session(session_id)
        if self._tracker and self._tracker.project_key:
            self._tracker.sync_base_seconds()
        self._load_data()

    # ── export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            os.path.expanduser("~/time_tracker.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            self._db.export_csv(path)
            QMessageBox.information(self, "Export CSV", f"Saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export JSON",
            os.path.expanduser("~/time_tracker.json"),
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            self._db.export_json(path)
            QMessageBox.information(self, "Export JSON", f"Saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

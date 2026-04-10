import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QFileDialog, QMessageBox,
    QTabWidget, QWidget,
)
from qgis.PyQt.QtCore import Qt


def _fmt(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class StatsDialog(QDialog):

    def __init__(self, persistence, parent=None):
        super().__init__(parent)
        self._db = persistence
        self.setWindowTitle("Time Tracker – Statistics")
        self.setMinimumSize(680, 480)
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        root = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Projects tab ──────────────────────────────────────────────────────
        proj_tab    = QWidget()
        proj_layout = QVBoxLayout(proj_tab)

        self._proj_tbl = QTableWidget(0, 4)
        self._proj_tbl.setHorizontalHeaderLabels(
            ["Project Name", "Path", "Total Time", "Last Accessed"]
        )
        hdr = self._proj_tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._proj_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self._proj_tbl.setSelectionBehavior(QTableWidget.SelectRows)
        self._proj_tbl.setAlternatingRowColors(True)
        self._proj_tbl.verticalHeader().setVisible(False)
        proj_layout.addWidget(self._proj_tbl)
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
        self._sess_tbl.setAlternatingRowColors(True)
        self._sess_tbl.verticalHeader().setVisible(False)
        sess_layout.addWidget(self._sess_tbl)
        tabs.addTab(sess_tab, "Sessions")

        root.addWidget(tabs)

        # ── button bar ────────────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.addStretch()

        btn_csv = QPushButton("Export CSV")
        btn_csv.clicked.connect(self._export_csv)
        bar.addWidget(btn_csv)

        btn_json = QPushButton("Export JSON")
        btn_json.clicked.connect(self._export_json)
        bar.addWidget(btn_json)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bar.addWidget(btn_close)

        root.addLayout(bar)

    def _load_data(self):
        projects = self._db.get_all_projects()
        self._proj_tbl.setRowCount(len(projects))
        for r, p in enumerate(projects):
            self._proj_tbl.setItem(r, 0, QTableWidgetItem(p["project_name"] or "—"))
            self._proj_tbl.setItem(r, 1, QTableWidgetItem(p["project_path"]))
            ti = QTableWidgetItem(_fmt(p["total_seconds"]))
            ti.setTextAlignment(Qt.AlignCenter)
            self._proj_tbl.setItem(r, 2, ti)
            self._proj_tbl.setItem(r, 3, QTableWidgetItem(str(p["last_accessed"])[:16]))

        sessions = self._db.get_sessions()
        self._sess_tbl.setRowCount(len(sessions))
        for r, s in enumerate(sessions):
            name = s["project_name"] or os.path.basename(s["project_path"])
            self._sess_tbl.setItem(r, 0, QTableWidgetItem(name))
            self._sess_tbl.setItem(r, 1, QTableWidgetItem(str(s["start_time"])[:19]))
            self._sess_tbl.setItem(r, 2, QTableWidgetItem(str(s["end_time"] or "—")[:19]))
            di = QTableWidgetItem(_fmt(s["duration_seconds"]))
            di.setTextAlignment(Qt.AlignCenter)
            self._sess_tbl.setItem(r, 3, di)
            rec_item = QTableWidgetItem("✓" if s["recovered"] else "")
            rec_item.setTextAlignment(Qt.AlignCenter)
            self._sess_tbl.setItem(r, 4, rec_item)

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
            QMessageBox.information(self, "Export", f"Saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

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
            QMessageBox.information(self, "Export", f"Saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
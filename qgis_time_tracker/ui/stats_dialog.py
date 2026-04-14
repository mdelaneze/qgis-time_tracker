import os

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QFileDialog, QMessageBox,
    QTabWidget, QWidget, QLabel,
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
        When provided, used to guard against modifying the project that is
        currently being tracked.
    """

    def __init__(self, persistence, tracker=None, parent=None):
        super().__init__(parent)
        self._db      = persistence
        self._tracker = tracker
        self.setWindowTitle("Time Tracker – Estatísticas")
        self.setMinimumSize(760, 540)
        self._build_ui()
        self._load_data()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        tabs = QTabWidget()

        # ── Projects tab ──────────────────────────────────────────────────────
        proj_tab    = QWidget()
        proj_layout = QVBoxLayout(proj_tab)

        self._proj_tbl = QTableWidget(0, 5)
        self._proj_tbl.setHorizontalHeaderLabels(
            ["Nome do Projeto", "Caminho", "Tempo Total", "Sessões", "Último Acesso"]
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
        self._proj_tbl.itemSelectionChanged.connect(self._on_proj_selection)
        proj_layout.addWidget(self._proj_tbl)

        # Action bar – Projects
        proj_actions = QHBoxLayout()

        self._lbl_proj_total = QLabel("")
        self._lbl_proj_total.setStyleSheet("color:#555; font-size:11px;")
        proj_actions.addWidget(self._lbl_proj_total)
        proj_actions.addStretch()

        self._btn_reset_proj = QPushButton("↺  Zerar Tempo")
        self._btn_reset_proj.setToolTip(
            "Reseta o contador de tempo do projeto selecionado para 00:00:00.\n"
            "O projeto e suas sessões NÃO são removidos."
        )
        self._btn_reset_proj.setEnabled(False)
        self._btn_reset_proj.clicked.connect(self._reset_project_time)
        proj_actions.addWidget(self._btn_reset_proj)

        self._btn_del_proj = QPushButton("🗑  Excluir Registro")
        self._btn_del_proj.setToolTip(
            "Remove permanentemente o registro do projeto e TODAS as suas sessões.\n"
            "Esta ação não pode ser desfeita."
        )
        self._btn_del_proj.setEnabled(False)
        self._btn_del_proj.clicked.connect(self._delete_project)
        proj_actions.addWidget(self._btn_del_proj)

        proj_layout.addLayout(proj_actions)
        tabs.addTab(proj_tab, "Projetos")

        # ── Sessions tab ──────────────────────────────────────────────────────
        sess_tab    = QWidget()
        sess_layout = QVBoxLayout(sess_tab)

        self._sess_tbl = QTableWidget(0, 5)
        self._sess_tbl.setHorizontalHeaderLabels(
            ["Projeto", "Início", "Fim", "Duração", "Recuperada"]
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
        self._sess_tbl.itemSelectionChanged.connect(self._on_sess_selection)
        sess_layout.addWidget(self._sess_tbl)

        # Action bar – Sessions
        sess_actions = QHBoxLayout()

        self._lbl_sess_total = QLabel("")
        self._lbl_sess_total.setStyleSheet("color:#555; font-size:11px;")
        sess_actions.addWidget(self._lbl_sess_total)
        sess_actions.addStretch()

        self._btn_del_sess = QPushButton("🗑  Remover Sessão")
        self._btn_del_sess.setToolTip(
            "Remove a sessão selecionada e recalcula o tempo total do projeto\n"
            "com base nas sessões restantes."
        )
        self._btn_del_sess.setEnabled(False)
        self._btn_del_sess.clicked.connect(self._delete_session)
        sess_actions.addWidget(self._btn_del_sess)

        sess_layout.addLayout(sess_actions)
        tabs.addTab(sess_tab, "Sessões")

        root.addWidget(tabs)

        # ── bottom bar – grand total + export + actions ───────────────────────
        bottom = QHBoxLayout()

        self._lbl_grand_total = QLabel("")
        self._lbl_grand_total.setStyleSheet(
            "font-weight:600; color:#1a3a5c; font-size:12px; padding:2px 6px;"
        )
        bottom.addWidget(self._lbl_grand_total)
        bottom.addStretch()

        btn_refresh = QPushButton("↻  Atualizar")
        btn_refresh.setToolTip("Recarrega os dados do banco de dados.")
        btn_refresh.clicked.connect(self._load_data)
        bottom.addWidget(btn_refresh)

        btn_csv = QPushButton("Exportar CSV")
        btn_csv.clicked.connect(self._export_csv)
        bottom.addWidget(btn_csv)

        btn_json = QPushButton("Exportar JSON")
        btn_json.clicked.connect(self._export_json)
        bottom.addWidget(btn_json)

        btn_close = QPushButton("Fechar")
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)

        root.addLayout(bottom)

    # ── data loading ──────────────────────────────────────────────────────────

    def _load_data(self):
        self._load_projects()
        self._load_sessions()
        self._update_grand_total()

    def _load_projects(self):
        """Populate the Projects table; stores project_path as Qt.UserRole."""
        # Remember current selection to restore it after reload
        selected_path = self._selected_project_path()

        projects = self._db.get_all_projects()
        active_key = self._tracker.project_key if self._tracker else None

        self._proj_tbl.setRowCount(len(projects))
        for r, p in enumerate(projects):
            name_item = QTableWidgetItem(p["project_name"] or "—")
            name_item.setData(Qt.UserRole, p["project_path"])

            # Highlight the currently tracked project
            if p["project_path"] == active_key:
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
                name_item.setToolTip("Projeto em rastreamento ativo")

            self._proj_tbl.setItem(r, 0, name_item)
            self._proj_tbl.setItem(r, 1, QTableWidgetItem(p["project_path"]))

            ti = QTableWidgetItem(_fmt(p["total_seconds"]))
            ti.setTextAlignment(Qt.AlignCenter)
            self._proj_tbl.setItem(r, 2, ti)

            sc = QTableWidgetItem(str(p["session_count"]))
            sc.setTextAlignment(Qt.AlignCenter)
            self._proj_tbl.setItem(r, 3, sc)

            self._proj_tbl.setItem(
                r, 4, QTableWidgetItem(str(p["last_accessed"])[:16])
            )

        # Footer summary
        total_secs = sum(p["total_seconds"] for p in projects)
        self._lbl_proj_total.setText(
            f"{len(projects)} projeto(s) · Total acumulado: {_fmt(total_secs)}"
        )

        # Restore selection
        self._btn_reset_proj.setEnabled(False)
        self._btn_del_proj.setEnabled(False)
        if selected_path:
            for r in range(self._proj_tbl.rowCount()):
                item = self._proj_tbl.item(r, 0)
                if item and item.data(Qt.UserRole) == selected_path:
                    self._proj_tbl.selectRow(r)
                    break

    def _load_sessions(self):
        """Populate the Sessions table; stores session id as Qt.UserRole."""
        selected_id = self._selected_session_id()

        sessions = self._db.get_sessions()
        self._sess_tbl.setRowCount(len(sessions))

        for r, s in enumerate(sessions):
            name = s["project_name"] or os.path.basename(s["project_path"])
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.UserRole, s["id"])

            if s["recovered"]:
                name_item.setForeground(QColor("#c0392b"))
                name_item.setToolTip("Sessão recuperada após crash do QGIS")

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
            f"{len(sessions)} sessão(ões) · Soma total: {_fmt(total_secs)}"
        )

        self._btn_del_sess.setEnabled(False)
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
            f"⏱  Tempo total registrado: {_fmt(grand)}  ({count} projeto(s))"
        )

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

    def _on_sess_selection(self):
        self._btn_del_sess.setEnabled(len(self._sess_tbl.selectedItems()) > 0)

    # ── active-project guard ──────────────────────────────────────────────────

    def _is_active_project(self, project_path: str) -> bool:
        """Return True if this project is currently being tracked."""
        if not self._tracker:
            return False
        return (
            self._tracker.project_key == project_path
            and self._tracker.state.value != "stopped"
        )

    # ── management actions ────────────────────────────────────────────────────

    def _reset_project_time(self):
        """
        Zero the selected project's accumulated time.
        The project row and all sessions are kept intact.
        """
        project_path = self._selected_project_path()
        if not project_path:
            return

        if self._is_active_project(project_path):
            QMessageBox.warning(
                self,
                "Projeto em Rastreamento",
                "Este projeto está sendo rastreado no momento.\n\n"
                "Pare o rastreamento antes de zerar o tempo.",
            )
            return

        name_item = self._proj_tbl.item(self._proj_tbl.currentRow(), 0)
        project_name = name_item.text() if name_item else project_path

        reply = QMessageBox.question(
            self,
            "Zerar Tempo do Projeto",
            f"Deseja zerar o tempo acumulado do projeto:\n\n"
            f"<b>{project_name}</b>\n\n"
            f"O projeto e suas sessões serão mantidos. "
            f"Apenas o contador de tempo será resetado para 00:00:00.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        self._db.reset_project_seconds(project_path)
        self._load_data()

    def _delete_project(self):
        """
        Permanently remove the project row and ALL its sessions.
        The QGIS project file itself is not touched.
        """
        project_path = self._selected_project_path()
        if not project_path:
            return

        if self._is_active_project(project_path):
            QMessageBox.warning(
                self,
                "Projeto em Rastreamento",
                "Este projeto está sendo rastreado no momento.\n\n"
                "Pare o rastreamento antes de excluir o registro.",
            )
            return

        row = self._proj_tbl.currentRow()
        project_name  = self._proj_tbl.item(row, 0).text()
        total_time    = self._proj_tbl.item(row, 2).text()
        session_count = self._proj_tbl.item(row, 3).text()

        reply = QMessageBox.warning(
            self,
            "Excluir Registro do Projeto",
            f"Tem certeza que deseja excluir permanentemente o registro de:\n\n"
            f"<b>{project_name}</b>\n"
            f"Tempo acumulado: {total_time}\n"
            f"Número de sessões: {session_count}\n\n"
            f"<b>Todas as sessões deste projeto serão removidas.\n"
            f"Esta ação não pode ser desfeita.</b>\n\n"
            f"O arquivo de projeto do QGIS NÃO será afetado.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        self._db.delete_project(project_path)
        self._load_data()

    def _delete_session(self):
        """
        Remove the selected session and recalculate the project's total_seconds
        as the sum of the remaining sessions.
        """
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
            "Remover Sessão",
            f"Deseja remover esta sessão?\n\n"
            f"Projeto: <b>{proj_name}</b>\n"
            f"Início: {start_time}\n"
            f"Duração: {duration}\n\n"
            f"O tempo total do projeto será recalculado "
            f"com base nas sessões restantes.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        self._db.delete_session(session_id)
        # Reload both tabs – project totals change after session deletion
        self._load_data()

    # ── export ────────────────────────────────────────────────────────────────

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar CSV",
            os.path.expanduser("~/time_tracker.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            self._db.export_csv(path)
            QMessageBox.information(self, "Exportação", f"Arquivo salvo em:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Erro na Exportação", str(exc))

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar JSON",
            os.path.expanduser("~/time_tracker.json"),
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            self._db.export_json(path)
            QMessageBox.information(self, "Exportação", f"Arquivo salvo em:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Erro na Exportação", str(exc))
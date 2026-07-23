"""
StatsDialog – statistics and data-management dialog.

"""

import os
from datetime import datetime

from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtGui import QColor
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


def _mb_yes():
    return _qt(QMessageBox, "StandardButton", "Yes") or _qt(QMessageBox, "Yes")


def _mb_cancel():
    return _qt(QMessageBox, "StandardButton", "Cancel") or _qt(QMessageBox, "Cancel")


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


def _display_datetime(value) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%d/%m/%Y %H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


def _datetime_sort_value(value) -> float:
    if not value:
        return 0
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.timestamp()
    except (TypeError, ValueError):
        return 0


class _SortItem(QTableWidgetItem):
    def __init__(self, text, sort_value):
        super().__init__(text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, _SortItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


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

    def __init__(self, persistence, tracker=None, settings=None, parent=None):
        super().__init__(parent)
        self._db = persistence
        self._tracker = tracker
        self._cfg = settings
        self.setWindowTitle("Controle de Tempo – Estatísticas")
        self.setMinimumSize(860, 600)
        self._build_ui()
        self._load_data()
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._refresh_live_kpis)
        if self._tracker is not None:
            self._live_timer.start()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        tabs = QTabWidget()

        # ── Summary tab ───────────────────────────────────────────────────────
        tabs.addTab(self._build_summary_tab(), "Resumo")

        # ── Projects tab ──────────────────────────────────────────────────────
        tabs.addTab(self._build_projects_tab(), "Projetos")

        # ── Sessions tab ──────────────────────────────────────────────────────
        tabs.addTab(self._build_sessions_tab(), "Histórico de sessões")

        root.addWidget(tabs)

        # ── bottom bar ────────────────────────────────────────────────────────
        bottom = QHBoxLayout()

        self._lbl_grand_total = QLabel("")
        self._lbl_grand_total.setStyleSheet(
            "font-weight:700; color:#1a3a5c; font-size:12px; padding:2px 6px;"
        )
        bottom.addWidget(self._lbl_grand_total)
        bottom.addStretch()

        btn_refresh = QPushButton("Atualizar")
        btn_refresh.setToolTip("Recarrega os dados do banco local.")
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

    # ── Summary tab ───────────────────────────────────────────────────────────

    def _build_summary_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setSpacing(10)

        # KPI cards row
        self._kpi_row = QHBoxLayout()
        self._kpi_row.setSpacing(8)

        self._kpi_today = self._make_kpi("Hoje", "00:00:00", "#2980b9")
        self._kpi_week = self._make_kpi("Esta semana", "00:00:00", "#27ae60")
        self._kpi_total = self._make_kpi("Total geral", "00:00:00", "#8e44ad")
        self._kpi_streak = self._make_kpi("Dias consecutivos", "0 dias", "#e67e22")
        self._kpi_projects = self._make_kpi("Projetos", "0", "#16a085")

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
        lbl_heat = QLabel("Atividade – últimas 12 semanas")
        lbl_heat.setStyleSheet("font-weight:600; color:#444; font-size:11px;")
        lay.addWidget(lbl_heat)

        self._heat_container = QWidget()
        self._heat_container.setFixedHeight(92)
        lay.addWidget(self._heat_container)

        self._lbl_recovery = QLabel()
        self._lbl_recovery.setStyleSheet(
            "color:#8a3b12;background:#fff3cd;border:1px solid #e0b65c;"
            "border-radius:4px;padding:5px;"
        )
        self._lbl_recovery.setWordWrap(True)
        self._lbl_recovery.hide()
        lay.addWidget(self._lbl_recovery)

        # Recent sessions mini-table
        lbl_recent = QLabel("Sessões recentes")
        lbl_recent.setStyleSheet("font-weight:600; color:#444; font-size:11px;")
        lay.addWidget(lbl_recent)

        self._recent_tbl = QTableWidget(0, 4)
        self._recent_tbl.setHorizontalHeaderLabels(
            ["Projeto", "Início", "Duração", "Rec."]
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
            "font-size:10px;color:#888;font-weight:600;border:none;background:transparent;"
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
        filter_row.addWidget(QLabel("Filtrar:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filtrar por nome ou caminho…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._filter_projects)
        filter_row.addWidget(self._filter_edit)
        lay.addLayout(filter_row)

        self._proj_tbl = QTableWidget(0, 5)
        self._proj_tbl.setHorizontalHeaderLabels(
            ["Projeto", "Caminho", "Tempo total", "Sessões", "Último acesso"]
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

        self._btn_copy_time = QPushButton("Copiar tempo")
        self._btn_copy_time.setToolTip(
            "Copia o tempo total do projeto selecionado."
        )
        self._btn_copy_time.setEnabled(False)
        self._btn_copy_time.clicked.connect(self._copy_project_time)
        proj_actions.addWidget(self._btn_copy_time)

        self._btn_reset_proj = QPushButton("Zerar contador")
        self._btn_reset_proj.setToolTip(
            "Zera o contador do projeto selecionado.\n"
            "O projeto e o histórico de sessões são preservados."
        )
        self._btn_reset_proj.setEnabled(False)
        self._btn_reset_proj.clicked.connect(self._reset_project_time)
        proj_actions.addWidget(self._btn_reset_proj)

        self._btn_del_proj = QPushButton("Excluir registro")
        self._btn_del_proj.setToolTip(
            "Remove permanent o projeto selecionado e todas as sessões.\n"
            "Esta ação não pode ser desfeita."
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
            ["Projeto", "Início", "Fim", "Duração", "Rec."]
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

        self._btn_del_sess = QPushButton("Excluir sessão")
        self._btn_del_sess.setToolTip(
            "Remove a sessão selecionada e recalcula o total do projeto."
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
        self._refresh_live_kpis()
        all_projects = self._db.get_all_projects()
        proj_count = len(all_projects)
        streak = self._db.get_streak_days()
        self._kpi_streak._value_label.setText(
            f"{streak} dia{'s' if streak != 1 else ''}"
        )
        self._kpi_projects._value_label.setText(str(proj_count))

        recovery_errors = self._db.get_recovery_errors()
        if recovery_errors:
            latest = recovery_errors[0]
            self._lbl_recovery.setText(
                f"Atenção: {len(recovery_errors)} sessão(ões) não puderam ser "
                "recuperadas automaticamente. Os registros foram preservados "
                "para diagnóstico."
            )
            self._lbl_recovery.setToolTip(
                f"Último projeto: {latest['project_path']}\n"
                f"Erro: {latest['error_message']}"
            )
            self._lbl_recovery.show()
        else:
            self._lbl_recovery.hide()

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
                ni.setToolTip("Recuperada após encerramento inesperado")
            self._recent_tbl.setItem(r, 0, ni)
            self._recent_tbl.setItem(
                r,
                1,
                _SortItem(
                    _display_datetime(s["start_time"]),
                    _datetime_sort_value(s["start_time"]),
                ),
            )
            di = _SortItem(_fmt(s["duration_seconds"]), s["duration_seconds"])
            di.setTextAlignment(_align_center())
            self._recent_tbl.setItem(r, 2, di)
            ri = QTableWidgetItem("✓" if s["recovered"] else "")
            ri.setTextAlignment(_align_center())
            self._recent_tbl.setItem(r, 3, ri)
        self._recent_tbl.setSortingEnabled(True)

    def _refresh_live_kpis(self):
        today_secs = (
            self._tracker.today_seconds()
            if self._tracker
            else self._db.get_today_seconds()
        )
        week_secs = (
            self._tracker.current_week_seconds()
            if self._tracker
            else self._db.get_current_week_seconds()
        )

        all_projects = self._db.get_all_projects()
        total_secs = sum(p["total_seconds"] for p in all_projects)
        if self._tracker:
            total_secs += self._tracker.running_elapsed_seconds()

        self._kpi_today._value_label.setText(_fmt(today_secs))
        self._kpi_week._value_label.setText(_fmt(week_secs))
        self._kpi_total._value_label.setText(_fmt(total_secs))

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
            except (ImportError, RuntimeError, TypeError):
                # O Qt assume a propriedade do layout quando sip não está disponível.
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
        legend.addWidget(QLabel("Menos"))
        for c in _HEAT_COLOURS:
            lc = QLabel()
            lc.setFixedSize(10, 10)
            lc.setStyleSheet(
                f"background:{c};border-radius:2px;border:1px solid rgba(0,0,0,0.1);"
            )
            legend.addWidget(lc)
        legend.addWidget(QLabel("Mais"))
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
        if self._tracker:
            total_secs += self._tracker.running_elapsed_seconds()
        self._lbl_proj_total.setText(
            f"{len(self._all_projects)} projeto(s) · Total: {_fmt(total_secs)}"
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

        is_active = p["project_path"] == active_key
        if is_active:
            f = name_item.font()
            f.setBold(True)
            name_item.setFont(f)
            name_item.setForeground(QColor("#0a3d22"))
            name_item.setToolTip("Projeto atual")

        self._proj_tbl.setItem(r, 0, name_item)
        self._proj_tbl.setItem(r, 1, QTableWidgetItem(p["project_path"]))

        displayed_total = p["total_seconds"]
        if is_active and self._tracker:
            displayed_total += self._tracker.running_elapsed_seconds()
        ti = _SortItem(_fmt(displayed_total), displayed_total)
        ti.setTextAlignment(_align_center())
        self._proj_tbl.setItem(r, 2, ti)

        sc = _SortItem(str(p["session_count"]), p["session_count"])
        sc.setTextAlignment(_align_center())
        self._proj_tbl.setItem(r, 3, sc)

        self._proj_tbl.setItem(
            r,
            4,
            _SortItem(
                _display_datetime(p["last_accessed"]),
                _datetime_sort_value(p["last_accessed"]),
            ),
        )

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
                name_item.setToolTip("Sessão recuperada após falha do QGIS")

            self._sess_tbl.setItem(r, 0, name_item)
            self._sess_tbl.setItem(
                r,
                1,
                _SortItem(
                    _display_datetime(s["start_time"]),
                    _datetime_sort_value(s["start_time"]),
                ),
            )
            self._sess_tbl.setItem(
                r,
                2,
                _SortItem(
                    _display_datetime(s["end_time"]),
                    _datetime_sort_value(s["end_time"]),
                ),
            )

            di = _SortItem(_fmt(s["duration_seconds"]), s["duration_seconds"])
            di.setTextAlignment(_align_center())
            self._sess_tbl.setItem(r, 3, di)

            ri = QTableWidgetItem("✓" if s["recovered"] else "")
            ri.setTextAlignment(_align_center())
            self._sess_tbl.setItem(r, 4, ri)

        total_secs = sum(s["duration_seconds"] for s in sessions)
        self._lbl_sess_total.setText(
            f"{len(sessions)} sessão(ões) · Total: {_fmt(total_secs)}"
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
        if self._tracker:
            grand += self._tracker.running_elapsed_seconds()
        count = len(projects)
        self._lbl_grand_total.setText(
            f"Total registrado: {_fmt(grand)}  ·  {count} projeto(s)"
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
                "Projeto em registro",
                "Este projeto está sendo registrado.\n\n"
                "Encerre a sessão antes de zerar o contador.",
            )
            return

        row = self._proj_tbl.currentRow()
        name = (
            self._proj_tbl.item(row, 0).text()
            if self._proj_tbl.item(row, 0)
            else project_path
        )

        if self._cfg is None or self._cfg.confirm_on_reset:
            reply = QMessageBox.question(
                self,
                "Zerar tempo do projeto",
                f"Zerar o tempo acumulado de:\n\n<b>{name}</b>\n\n"
                f"O projeto e as sessões serão preservados como histórico. "
                f"Somente o contador será reiniciado em 00:00:00.",
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
                "Projeto em registro",
                "Este projeto está sendo registrado.\n\n"
                "Encerre a sessão antes de excluir.",
            )
            return

        row = self._proj_tbl.currentRow()
        project_name = self._proj_tbl.item(row, 0).text()
        total_time = self._proj_tbl.item(row, 2).text()
        session_count = self._proj_tbl.item(row, 3).text()

        reply = QMessageBox.warning(
            self,
            "Excluir registro do projeto",
            f"Excluir permanentemente o registro de:\n\n<b>{project_name}</b>\n"
            f"Tempo total: {total_time}\n"
            f"Sessões: {session_count}\n\n"
            f"<b>Todas as sessões serão removidas. "
            f"Esta ação não pode ser desfeita.</b>\n\n"
            f"O arquivo do projeto QGIS não será alterado.",
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
            "Excluir sessão",
            f"Excluir esta sessão?\n\n"
            f"Projeto: <b>{proj_name}</b>\n"
            f"Início: {start_time}\n"
            f"Duração: {duration}\n\n"
            f"O total do projeto será recalculado com as sessões contabilizadas.",
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
            "Exportar CSV",
            os.path.expanduser("~/time_tracker.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            self._db.export_csv(path)
            QMessageBox.information(self, "Exportar CSV", f"Arquivo salvo em:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Erro de exportação", str(exc))

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar JSON",
            os.path.expanduser("~/time_tracker.json"),
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            self._db.export_json(path)
            QMessageBox.information(
                self, "Exportar JSON", f"Arquivo salvo em:\n{path}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Erro de exportação", str(exc))

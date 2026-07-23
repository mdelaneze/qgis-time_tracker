"""
SettingsDialog – Time Tracker preferences.

"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

# ── Qt5 / Qt6 enum compat helpers ─────────────────────────────────────────────


def _qt(cls, *chain, fallback=None):
    """Walk attribute chain on cls, return first match or fallback."""
    obj = cls
    for attr in chain:
        obj = getattr(obj, attr, None)
        if obj is None:
            return fallback
    return obj if obj is not None else fallback


def _horizontal():
    return _qt(Qt, "Orientation", "Horizontal") or _qt(Qt, "Horizontal")


def _ticks_below():
    return _qt(QSlider, "TickPosition", "TicksBelow") or _qt(QSlider, "TicksBelow")


def _btn(*names):
    """Resolve QDialogButtonBox standard button flags for PyQt5 and PyQt6."""
    result = None
    for name in names:
        v = _qt(QDialogButtonBox, "StandardButton", name) or _qt(QDialogButtonBox, name)
        if v is not None:
            result = v if result is None else (result | v)
    return result


# ── dialog ─────────────────────────────────────────────────────────────────────


class SettingsDialog(QDialog):

    def __init__(self, settings, tracker, parent=None):
        super().__init__(parent)
        self._cfg = settings
        self._tracker = tracker
        self.setWindowTitle("Controle de Tempo – Configurações")
        self.setMinimumWidth(460)
        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Auto-Pause ────────────────────────────────────────────────────────
        grp_pause = QGroupBox("Pausa automática")
        form = QFormLayout(grp_pause)

        self._spin_idle = QSpinBox()
        self._spin_idle.setRange(0, 480)
        self._spin_idle.setSuffix(" min")
        self._spin_idle.setSpecialValueText("Desativado")
        self._spin_idle.setToolTip(
            "Pausa após este período sem atividade no QGIS.\n"
            "Use 0 para desativar."
        )
        form.addRow("Tempo de inatividade:", self._spin_idle)

        self._chk_focus = QCheckBox(
            "Pausar quando o QGIS for minimizado ou perder o foco"
        )
        form.addRow(self._chk_focus)
        root.addWidget(grp_pause)

        # ── Auto-Start ────────────────────────────────────────────────────────
        grp_start = QGroupBox("Início automático")
        form2 = QFormLayout(grp_start)
        self._chk_autostart = QCheckBox(
            "Iniciar a contagem automaticamente ao abrir um projeto"
        )
        form2.addRow(self._chk_autostart)
        root.addWidget(grp_start)

        # ── Sessions ──────────────────────────────────────────────────────────
        grp_sess = QGroupBox("Sessões")
        form3 = QFormLayout(grp_sess)

        self._spin_min_session = QSpinBox()
        self._spin_min_session.setRange(0, 300)
        self._spin_min_session.setSuffix(" s")
        self._spin_min_session.setSpecialValueText("Registrar todas")
        self._spin_min_session.setToolTip(
            "Sessões menores que este valor são descartadas ao pausar ou encerrar.\n"
            "Útil para ignorar acionamentos acidentais.\n"
            "Use 0 para registrar todas."
        )
        form3.addRow("Duração mínima:", self._spin_min_session)

        slider_row = QHBoxLayout()
        self._sld_min_session = QSlider(_horizontal())
        self._sld_min_session.setRange(0, 300)
        self._sld_min_session.setTickInterval(60)
        self._sld_min_session.setTickPosition(_ticks_below())
        self._sld_min_session.setToolTip("Arraste para ajustar a duração mínima.")
        self._spin_min_session.valueChanged.connect(self._sld_min_session.setValue)
        self._sld_min_session.valueChanged.connect(self._spin_min_session.setValue)
        slider_row.addWidget(QLabel("0 s"))
        slider_row.addWidget(self._sld_min_session, 1)
        slider_row.addWidget(QLabel("5 min"))
        form3.addRow(slider_row)

        self._chk_notify_session = QCheckBox(
            "Exibir notificação ao finalizar uma sessão"
        )
        self._chk_notify_session.setToolTip(
            "Exibe na barra de mensagens do QGIS a duração\n"
            "da sessão quando ela é pausada ou encerrada."
        )
        form3.addRow(self._chk_notify_session)
        root.addWidget(grp_sess)

        # ── Daily Goal ────────────────────────────────────────────────────────
        grp_goal = QGroupBox("Meta diária")
        form4 = QFormLayout(grp_goal)

        self._spin_goal = QSpinBox()
        self._spin_goal.setRange(0, 16)
        self._spin_goal.setSuffix(" h")
        self._spin_goal.setSpecialValueText("Sem meta")
        self._spin_goal.setToolTip(
            "Defina uma meta diária de trabalho.\n"
            "A barra integrada mostrará o progresso do dia.\n"
            "Use 0 para desativar."
        )
        form4.addRow("Meta diária:", self._spin_goal)

        self._chk_show_progress = QCheckBox(
            "Exibir o progresso diário na barra de ferramentas"
        )
        self._chk_show_progress.setToolTip(
            "Exibe abaixo do contador quanto da meta de hoje foi concluído."
        )
        form4.addRow(self._chk_show_progress)
        root.addWidget(grp_goal)

        # ── Interface ─────────────────────────────────────────────────────────
        grp_ui = QGroupBox("Interface")
        form5 = QFormLayout(grp_ui)

        self._chk_confirm_reset = QCheckBox(
            "Pedir confirmação antes de zerar o tempo de um projeto"
        )
        self._chk_confirm_reset.setToolTip(
            "Quando marcado, solicita confirmação antes de zerar o contador."
        )
        form5.addRow(self._chk_confirm_reset)

        self._chk_project_name = QCheckBox(
            "Exibir o nome do projeto na barra de ferramentas"
        )
        self._chk_project_name.setToolTip(
            "Exibe o nome do projeto ativo ao lado do contador."
        )
        form5.addRow(self._chk_project_name)
        root.addWidget(grp_ui)

        # ── Buttons ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(_btn("Ok", "Cancel"))
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _load(self):
        self._spin_idle.setValue(self._cfg.idle_timeout_minutes)
        self._chk_focus.setChecked(self._cfg.pause_on_focus_loss)
        self._chk_autostart.setChecked(self._cfg.auto_start_on_open)
        self._spin_min_session.setValue(self._cfg.min_session_seconds)
        self._sld_min_session.setValue(self._cfg.min_session_seconds)
        self._chk_notify_session.setChecked(self._cfg.notify_on_session_end)
        self._chk_confirm_reset.setChecked(self._cfg.confirm_on_reset)
        self._chk_project_name.setChecked(self._cfg.show_project_name)
        self._spin_goal.setValue(self._cfg.daily_goal_hours)
        self._chk_show_progress.setChecked(self._cfg.show_daily_progress)

    def _save(self):
        self._cfg.idle_timeout_minutes = self._spin_idle.value()
        self._cfg.pause_on_focus_loss = self._chk_focus.isChecked()
        self._cfg.auto_start_on_open = self._chk_autostart.isChecked()
        self._cfg.min_session_seconds = self._spin_min_session.value()
        self._cfg.notify_on_session_end = self._chk_notify_session.isChecked()
        self._cfg.confirm_on_reset = self._chk_confirm_reset.isChecked()
        self._cfg.show_project_name = self._chk_project_name.isChecked()
        self._cfg.daily_goal_hours = self._spin_goal.value()
        self._cfg.show_daily_progress = self._chk_show_progress.isChecked()

        self._tracker.apply_idle_setting()

        if hasattr(self._tracker, "apply_project_name_setting"):
            self._tracker.apply_project_name_setting()

        self.accept()

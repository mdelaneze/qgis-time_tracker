from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QSpinBox, QCheckBox,
    QDialogButtonBox, QGroupBox,
)
from ..core.tracker import TrackerState


class SettingsDialog(QDialog):

    def __init__(self, settings, tracker, parent=None):
        super().__init__(parent)
        self._cfg     = settings
        self._tracker = tracker
        self.setWindowTitle("Time Tracker – Settings")
        self.setMinimumWidth(400)
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── Auto-Pause ────────────────────────────────────────────────────────
        grp_pause = QGroupBox("Auto-Pause")
        form = QFormLayout(grp_pause)

        self._spin_idle = QSpinBox()
        self._spin_idle.setRange(0, 480)
        self._spin_idle.setSuffix(" min")
        self._spin_idle.setSpecialValueText("Desativado")
        self._spin_idle.setToolTip(
            "Pausa automaticamente após este número de minutos sem atividade.\n"
            "Defina como 0 para desativar."
        )
        form.addRow("Timeout de inatividade:", self._spin_idle)

        self._chk_focus = QCheckBox(
            "Pausar quando o QGIS perder foco ou for minimizado"
        )
        form.addRow(self._chk_focus)
        root.addWidget(grp_pause)

        # ── Auto-Start ────────────────────────────────────────────────────────
        grp_start = QGroupBox("Auto-Start")
        form2 = QFormLayout(grp_start)
        self._chk_autostart = QCheckBox(
            "Iniciar rastreamento automaticamente ao abrir um projeto"
        )
        form2.addRow(self._chk_autostart)
        root.addWidget(grp_start)

        # ── Interface ─────────────────────────────────────────────────────────
        grp_ui = QGroupBox("Interface")
        form3 = QFormLayout(grp_ui)

        self._chk_confirm_reset = QCheckBox(
            "Solicitar confirmação antes de zerar o tempo de um projeto"
        )
        self._chk_confirm_reset.setToolTip(
            "Quando marcado, um diálogo de confirmação será exibido antes de\n"
            "qualquer operação de reset no Time Tracker e na janela de Estatísticas."
        )
        form3.addRow(self._chk_confirm_reset)

        self._chk_project_name = QCheckBox(
            "Exibir nome do projeto na barra de ferramentas"
        )
        self._chk_project_name.setToolTip(
            "Mostra um rótulo com o nome do projeto ativo ao lado do contador de tempo."
        )
        form3.addRow(self._chk_project_name)
        root.addWidget(grp_ui)

        # ── Buttons ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _load(self):
        self._spin_idle.setValue(self._cfg.idle_timeout_minutes)
        self._chk_focus.setChecked(self._cfg.pause_on_focus_loss)
        self._chk_autostart.setChecked(self._cfg.auto_start_on_open)
        self._chk_confirm_reset.setChecked(self._cfg.confirm_on_reset)
        self._chk_project_name.setChecked(self._cfg.show_project_name)

    def _save(self):
        self._cfg.idle_timeout_minutes = self._spin_idle.value()
        self._cfg.pause_on_focus_loss  = self._chk_focus.isChecked()
        self._cfg.auto_start_on_open   = self._chk_autostart.isChecked()
        self._cfg.confirm_on_reset     = self._chk_confirm_reset.isChecked()
        self._cfg.show_project_name    = self._chk_project_name.isChecked()

        # Apply idle setting immediately via public tracker API (no private access)
        self._tracker.apply_idle_setting()

        self.accept()
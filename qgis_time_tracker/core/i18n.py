"""Small runtime translation catalogue for the plugin user interface."""

SUPPORTED_LANGUAGES = ("en", "pt")
LANGUAGE_NAMES = {
    "en": "English",
    "pt": "Português",
}

_PT = {
    "Time Tracker": "Controle de Tempo",
    "Time Tracker – Settings": "Controle de Tempo – Configurações",
    "Time Tracker – Statistics": "Controle de Tempo – Estatísticas",
    "Language": "Idioma",
    "Auto-pause": "Pausa automática",
    "Idle timeout:": "Tempo de inatividade:",
    "Disabled": "Desativado",
    "Pause after this period without activity in QGIS.\nUse 0 to disable.":
        "Pausa após este período sem atividade no QGIS.\nUse 0 para desativar.",
    "Pause when QGIS is minimized or loses focus":
        "Pausar quando o QGIS for minimizado ou perder o foco",
    "Automatic start": "Início automático",
    "Start tracking automatically when a project is opened":
        "Iniciar a contagem automaticamente ao abrir um projeto",
    "Sessions": "Sessões",
    "Minimum duration:": "Duração mínima:",
    "Record all": "Registrar todas",
    "Sessions shorter than this value are discarded when paused or stopped.\n"
    "This helps ignore accidental starts.\nUse 0 to record all.":
        "Sessões menores que este valor são descartadas ao pausar ou encerrar.\n"
        "Útil para ignorar acionamentos acidentais.\nUse 0 para registrar todas.",
    "Drag to adjust the minimum duration.": "Arraste para ajustar a duração mínima.",
    "Show a notification when a session ends":
        "Exibir notificação ao finalizar uma sessão",
    "Shows the session duration in the QGIS message bar when it is paused or stopped.":
        "Exibe na barra de mensagens do QGIS a duração da sessão quando ela é pausada ou encerrada.",
    "Daily goal": "Meta diária",
    "No goal": "Sem meta",
    "Set a daily work goal.\nThe integrated bar will show today's progress.\n"
    "Use 0 to disable.":
        "Defina uma meta diária de trabalho.\nA barra integrada mostrará o progresso do dia.\n"
        "Use 0 para desativar.",
    "Show daily progress in the toolbar":
        "Exibir o progresso diário na barra de ferramentas",
    "Shows below the timer how much of today's goal has been completed.":
        "Exibe abaixo do contador quanto da meta de hoje foi concluído.",
    "Interface": "Interface",
    "Ask for confirmation before resetting a project's time":
        "Pedir confirmação antes de zerar o tempo de um projeto",
    "When enabled, asks for confirmation before resetting the timer.":
        "Quando marcado, solicita confirmação antes de zerar o contador.",
    "Show the project name in the toolbar":
        "Exibir o nome do projeto na barra de ferramentas",
    "Shows the active project name next to the timer.":
        "Exibe o nome do projeto ativo ao lado do contador.",
    "Stopped": "Parado",
    "Tracking": "Registrando",
    "Paused": "Pausado",
    "Unsaved project": "Projeto não salvo",
    "Time Tracker status": "Estado do Controle de Tempo",
    "Start or pause time tracking": "Iniciar ou pausar o registro de tempo",
    "End the time session": "Encerrar a sessão de tempo",
    "Open Time Tracker statistics": "Abrir estatísticas do Controle de Tempo",
    "Open Time Tracker settings": "Abrir configurações do Controle de Tempo",
    "Start  (Ctrl+Alt+T)": "Iniciar  (Ctrl+Alt+T)",
    "Pause  (Ctrl+Alt+T)": "Pausar  (Ctrl+Alt+T)",
    "Resume  (Ctrl+Alt+T)": "Retomar  (Ctrl+Alt+T)",
    "End session": "Encerrar sessão",
    "Statistics and history": "Estatísticas e histórico",
    "Settings": "Configurações",
    "Daily progress: 0%": "Progresso diário: 0%",
    "State: {state}\nProject total: {total}\nRight-click to copy · Ctrl+Alt+T to toggle":
        "Estado: {state}\nTotal do projeto: {total}\n"
        "Clique com o botão direito para copiar · Ctrl+Alt+T para alternar",
    "Session ended – duration: {duration}": "Sessão finalizada – duração: {duration}",
    "Today: {today} / {goal}\nProgress: {percent}%":
        "Hoje: {today} / {goal}\nProgresso: {percent}%",
    "Remaining: {remaining}": "Restante: {remaining}",
    "Daily goal reached!": "Meta diária alcançada!",
    "Current state: {state}": "Estado atual: {state}",
    "Pause: {reason}": "Pausa: {reason}",
    "inactivity": "inatividade",
    "QGIS out of focus": "QGIS sem foco",
    "manual": "manual",
    "Copy time": "Copiar tempo",
    "Pause": "Pausar",
    "Start": "Iniciar",
    "End": "Encerrar",
    "Summary": "Resumo",
    "Projects": "Projetos",
    "Session history": "Histórico de sessões",
    "Refresh": "Atualizar",
    "Reloads data from the local database.": "Recarrega os dados do banco local.",
    "Export CSV": "Exportar CSV",
    "Export JSON": "Exportar JSON",
    "Close": "Fechar",
    "Today": "Hoje",
    "This week": "Esta semana",
    "All time": "Total geral",
    "Consecutive days": "Dias consecutivos",
    "{count} day": "{count} dia",
    "{count} days": "{count} dias",
    "Activity – last 12 weeks": "Atividade – últimas 12 semanas",
    "Recent sessions": "Sessões recentes",
    "Project": "Projeto",
    "Started": "Início",
    "Duration": "Duração",
    "Recovered": "Rec.",
    "Filter:": "Filtrar:",
    "Filter by name or path…": "Filtrar por nome ou caminho…",
    "Path": "Caminho",
    "Total time": "Tempo total",
    "Last accessed": "Último acesso",
    "Copies the selected project's total time.":
        "Copia o tempo total do projeto selecionado.",
    "Reset timer": "Zerar contador",
    "Resets the selected project's timer.\nThe project and session history are preserved.":
        "Zera o contador do projeto selecionado.\n"
        "O projeto e o histórico de sessões são preservados.",
    "Delete record": "Excluir registro",
    "Permanently removes the selected project and all sessions.\n"
    "This action cannot be undone.":
        "Remove permanentemente o projeto selecionado e todas as sessões.\n"
        "Esta ação não pode ser desfeita.",
    "Ended": "Fim",
    "Delete session": "Excluir sessão",
    "Removes the selected session and recalculates the project total.":
        "Remove a sessão selecionada e recalcula o total do projeto.",
    "{count} project(s) · Total: {total}": "{count} projeto(s) · Total: {total}",
    "{count} session(s) · Total: {total}": "{count} sessão(ões) · Total: {total}",
    "Total tracked: {total}  ·  {count} project(s)":
        "Total registrado: {total}  ·  {count} projeto(s)",
    "Current project": "Projeto atual",
    "Session recovered after a QGIS failure":
        "Sessão recuperada após falha do QGIS",
    "Recovered after an unexpected shutdown":
        "Recuperada após encerramento inesperado",
    "Warning: {count} session(s) could not be recovered automatically. "
    "The records were preserved for diagnosis.":
        "Atenção: {count} sessão(ões) não puderam ser recuperadas automaticamente. "
        "Os registros foram preservados para diagnóstico.",
    "Last project: {project}\nError: {error}":
        "Último projeto: {project}\nErro: {error}",
    "Less": "Menos",
    "More": "Mais",
    "Project is being tracked": "Projeto em registro",
    "This project is currently being tracked.\n\nEnd the session before resetting the timer.":
        "Este projeto está sendo registrado.\n\n"
        "Encerre a sessão antes de zerar o contador.",
    "Reset project time": "Zerar tempo do projeto",
    "Reset the accumulated time for:\n\n<b>{name}</b>\n\n"
    "The project and sessions will be preserved as history. "
    "Only the timer will be reset to 00:00:00.":
        "Zerar o tempo acumulado de:\n\n<b>{name}</b>\n\n"
        "O projeto e as sessões serão preservados como histórico. "
        "Somente o contador será reiniciado em 00:00:00.",
    "This project is currently being tracked.\n\nEnd the session before deleting it.":
        "Este projeto está sendo registrado.\n\nEncerre a sessão antes de excluir.",
    "Delete project record": "Excluir registro do projeto",
    "Permanently delete the record for:\n\n<b>{name}</b>\n"
    "Total time: {total}\nSessions: {sessions}\n\n"
    "<b>All sessions will be removed. This action cannot be undone.</b>\n\n"
    "The QGIS project file will not be changed.":
        "Excluir permanentemente o registro de:\n\n<b>{name}</b>\n"
        "Tempo total: {total}\nSessões: {sessions}\n\n"
        "<b>Todas as sessões serão removidas. Esta ação não pode ser desfeita.</b>\n\n"
        "O arquivo do projeto QGIS não será alterado.",
    "Delete this session?\n\nProject: <b>{project}</b>\nStarted: {started}\n"
    "Duration: {duration}\n\nThe project total will be recalculated from "
    "the counted sessions.":
        "Excluir esta sessão?\n\nProjeto: <b>{project}</b>\nInício: {started}\n"
        "Duração: {duration}\n\n"
        "O total do projeto será recalculado com as sessões contabilizadas.",
    "File saved to:\n{path}": "Arquivo salvo em:\n{path}",
    "Export error": "Erro de exportação",
    "{count} session(s) could not be recovered and were preserved for diagnosis. "
    "See the QGIS message log.":
        "{count} sessão(ões) não puderam ser recuperadas e foram preservadas para "
        "diagnóstico. Consulte o painel de mensagens do QGIS.",
}


def normalize_language(language) -> str:
    """Return a supported language code, defaulting to English."""
    value = str(language or "").lower().replace("-", "_")
    if value.startswith("pt"):
        return "pt"
    return "en"


def tr(text: str, language="en", **values) -> str:
    """Translate an English source string and interpolate named values."""
    translated = _PT.get(text, text) if normalize_language(language) == "pt" else text
    return translated.format(**values) if values else translated

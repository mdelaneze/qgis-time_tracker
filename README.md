# QGIS Time Tracker Plugin

Track how long you spend on each QGIS project — automatically, persistently,
and crash-safely.



## Status

This plugin is in an early stage of development.

Core features (time tracking, persistence, crash recovery) are implemented and functional,  
but additional features and edge-case handling are still being refined.

Feedback and bug reports are welcome.
---

## Installation

### Option A – QGIS Plugin Manager (recommended)

1. In QGIS go to **Plugins → Manage and Install Plugins → Install from ZIP**.
2. Select `qgis_time_tracker.zip`.
3. Click **Install Plugin**.

### Option B – Manual

1. Locate your QGIS plugins directory:
   | OS      | Default path |
   |---------|-------------|
   | Linux   | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |
   | macOS   | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |
   | Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` |

2. Copy the `qgis_time_tracker/` folder into that directory.
3. Restart QGIS.
4. Enable the plugin via **Plugins → Manage and Install Plugins → Installed**.

---

## Quick Start

After enabling the plugin a **Time Tracker** toolbar appears:

```
[ 00:00:00 ] [ ▶ ] [ ⏸ ] [ ⏹ ] [ 📊 ] [ ⚙ ]
```

| Button | Action |
|--------|--------|
| ▶      | Start or resume tracking for the current project |
| ⏸      | Pause – time stops but is not lost |
| ⏹      | Stop – saves the session and resets the running counter |
| 📊     | Open the Statistics / Export dialog |
| ⚙      | Open Settings |

The timer label changes colour:
- **Grey** → stopped
- **Green** → running
- **Amber** → paused

---

## Settings

| Option | Description |
|--------|-------------|
| Idle timeout | Automatically pause after N minutes of no mouse/keyboard activity. Set to 0 to disable. |
| Pause on focus loss | Pause when QGIS is minimised or loses focus (e.g., you switch to another application). |
| Auto-start on open | Start tracking automatically every time a project is opened. |

---

## Statistics & Export

Click 📊 to open the **Statistics** dialog.

**Projects tab** – total accumulated time per project, last accessed date.  
**Sessions tab** – individual work sessions with start/end time and duration.
Sessions marked **✓** in the Recovered column were rescued from a crash.

Use **Export CSV** or **Export JSON** to save a full report.

---

## Data Storage

All data is stored in a SQLite database:

```
{QGIS profile dir}/time_tracker/time_tracker.db
```

The database is opened in **WAL mode** (Write-Ahead Logging), which means:
- SQLite never writes a partial page to the main DB file.
- A hard kill or power loss cannot corrupt the database.
- A heartbeat writes `active_session.last_heartbeat` every **5 seconds**, so
  at most 5 s of tracking time is lost in a crash.

---

## Architecture

```
qgis_time_tracker/
├── __init__.py                 # classFactory – QGIS entry point
├── metadata.txt
├── time_tracker_plugin.py      # Plugin lifecycle (initGui / unload)
│                               # Event filters for idle + focus detection
│                               # QgsProject signal connections
├── core/
│   ├── settings.py             # QSettings wrapper (idle timeout, auto-pause, …)
│   ├── persistence.py          # SQLite: projects, sessions, active_session tables
│   │                           # Crash recovery on startup
│   └── tracker.py              # 3-state machine (STOPPED ↔ RUNNING ↔ PAUSED)
│                               # display timer (1 s) + heartbeat timer (5 s)
│                               # idle detection via time.monotonic()
├── ui/
│   ├── toolbar_widget.py       # Compact toolbar strip with colour-coded timer
│   ├── settings_dialog.py      # QDialog for user preferences
│   └── stats_dialog.py         # QDialog: Projects + Sessions tabs + export
└── resources/
    └── clock.svg               # Plugin icon
```

### Key design decisions

**Why SQLite instead of JSON?**  
SQLite is ACID-compliant: a crash mid-write leaves the DB in a consistent
state because WAL mode keeps incomplete writes in the journal, never in the
main file.  JSON has no such guarantee.

**Why `time.monotonic()` for elapsed time?**  
`time.time()` is affected by NTP adjustments and DST switches.
`time.monotonic()` always moves forward and is ideal for measuring durations.
The DB stores wall-clock ISO timestamps (UTC) for display purposes only —
no duration arithmetic ever touches those values.

**Why a single `active_session` row?**  
There can only be one active tracker session at a time.  Using `id=1` as a
constraint means `INSERT OR REPLACE` is an atomic upsert, eliminating the
risk of duplicate rows even if the heartbeat and a stop() call race.

**Why not update `projects.total_seconds` on every heartbeat?**  
It would produce unnecessary write amplification.  The heartbeat only
touches `active_session.last_heartbeat` (one small write).  The project
total is updated once per session: on pause(), stop(), or load_project().
Crash recovery reads `last_heartbeat` to reconstruct the lost interval.

**Unsaved project tracking**  
QGIS returns `""` for `absoluteFilePath()` before a project is saved.
The plugin maps this to the sentinel key `__unsaved__`.  When the user
saves the project for the first time (`writeProject` signal), the plugin
calls `PersistenceManager.migrate_project_path()` which re-parents both
the `projects` row and all `sessions` rows to the real file path — no data
is lost.
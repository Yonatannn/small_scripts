# logs_grabber

Collects log files from predefined locations on a machine, packages them,
and produces three artifacts plus a separate dated backup in `%TEMP%`.
Comes with a GUI (`gui.py`) and a headless CLI (`grab_logs.py`).

Target platform: **Windows 11, Python 3.10** (standard library only; the
GUI uses `tkinter`, which ships with the standard Python.org installer).

## What it does

1. Reads `config.json` for the list of source locations and the output
   destination.
2. Copies **everything** from each *selected* source (files or whole
   folders) into a freshly organized package, grouped by source name.
3. Zips that package.
4. Runs `../transfer/add_data.py` on the zip to produce a padded `.bin`.
5. Keeps all **three** artifacts — plus an `info.txt` description — together
   in a folder named **`Logs - <date>`**, and opens it in Explorer.
6. In parallel, writes a **backup of everything to `%TEMP%`**, mirroring
   the *original* folder layout, under a top-level `Logs - <date>` folder.
   That backup is finally kept **only as a single zip**.

## GUI

```bat
python gui.py
```

- Lists every log source with a checkbox. **All are checked by default**
  (everything is collected); uncheck anything you don't want this run.
- A free-text box for a **Hebrew description** of the logs. It is saved to
  `info.txt` (UTF-8, opens correctly in Notepad) inside the `Logs - <date>`
  folder and inside the temp backup, together with the list of which
  sources were included/excluded.
- Lets you override the output directory, shows live progress, and opens
  the result folder when finished.

`python grab_logs.py --gui` launches the same GUI.

## Output layout

Main output (path from `output_dir`, defaults to the Desktop):

```
Logs - <YYYY-MM-DD>/
├── logs/                          <- organized package (by source name)
│   ├── windows_logs/...
│   └── myapp_local/...
├── Logs - <YYYY-MM-DD>.zip        <- zip of logs/
├── Logs - <YYYY-MM-DD>.zip.bin    <- add_data.py output
└── info.txt                       <- Hebrew description + what was collected
```

(If a folder for today already exists, a `(HH-MM-SS)` suffix is added.)

Temp backup (mirrors the original paths, kept only as a zip):

```
%TEMP%/LogsGrabber/Logs - <YYYY-MM-DD>.zip
   (inside: Logs - <date>/C/Windows/Logs/..., plus info.txt)
```

## Configuration (`config.json`)

| Key               | Meaning                                                            |
|-------------------|-------------------------------------------------------------------|
| `sources`         | List of `{ "name", "path" }`. `path` may be a file or a folder.   |
| `output_dir`      | Where the main bundle is created (env vars expanded). Optional.   |
| `add_data_kb`     | KB of random padding for `add_data.py` (default 4).               |
| `add_data_script` | Override path to `add_data.py` (default: `../transfer/add_data.py`). |

Environment variables in paths (e.g. `%LOCALAPPDATA%`, `%USERPROFILE%`)
are expanded.

## CLI usage

```bat
python grab_logs.py                          :: collect everything
python grab_logs.py --only windows_logs,cbs  :: only specific sources
python grab_logs.py -d "תיאור בעברית"        :: description -> info.txt
python grab_logs.py -o D:\exports            :: override output dir
python grab_logs.py --no-open                :: don't open Explorer
python grab_logs.py --gui                    :: launch the GUI
```

Log files that are locked / in use are skipped with a warning rather than
aborting the run.

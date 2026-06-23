# logs_grabber

Collects log files from predefined locations on a machine, packages them,
and produces three artifacts plus a separate dated backup in `%TEMP%`.

Target platform: **Windows 11, Python 3.10**.

- `grab_logs.py` — the collection logic (standard library only).
- `add_data.py` — bundled padding tool used to produce the `.bin`.
- `gui.py` — a PyQt5 interface. Requires `pip install PyQt5`.

## What it does

1. Reads `config.json` for the source locations and the output folder.
2. **Backup first:** copies everything from each selected source to `%TEMP%`,
   mirroring the original folder layout under a top-level
   `Logs_<date>_<time>` folder, and saves it **as a single zip** -- before
   touching the originals.
3. **Then moves** everything from each source into a freshly organized
   package (grouped by source name) in the output folder. The files are
   **removed from their original location** (the top source folder itself is
   kept, just emptied).
4. Zips that package and runs the bundled `add_data.py` to produce a padded
   `.bin`.
5. Keeps all **three** artifacts -- plus an `info.txt` description -- in a
   folder named **`Logs_<date>_<time>`**, and opens it in Explorer.

The `%TEMP%` zip is the safety copy: it is written and verified before any
file is moved out of its original location. Files that are locked / in use
can't be moved; they are left in place and skipped with a warning.

## Run it

GUI (recommended):

```bat
pip install PyQt5
python gui.py
```

- One checkbox per log source, **all checked by default** (collect
  everything); uncheck anything you don't want this run.
- A description box, saved to `info.txt`.
- A big button, a progress bar with a live time-remaining estimate, and the
  result folder opens automatically when finished.

Headless (collect everything, no options):

```bat
python grab_logs.py
```

## Output layout

Main output (path from `output_dir`, defaults to the Desktop):

```
Logs_<YYYY-MM-DD>_<HH-MM-SS>/
├── logs/                                <- organized package (by source name)
├── Logs_<YYYY-MM-DD>_<HH-MM-SS>.zip     <- zip of logs/
├── Logs_<YYYY-MM-DD>_<HH-MM-SS>.zip.bin <- add_data.py output
└── info.txt                             <- description + what was collected
```

Temp backup -- same name as the output folder, kept only as a zip:

```
%TEMP%/LogsGrabber/Logs_<YYYY-MM-DD>_<HH-MM-SS>.zip
```

## Configuration (`config.json`)

| Key               | Meaning                                                            |
|-------------------|-------------------------------------------------------------------|
| `sources`         | List of `{ "name", "path" }`. `path` may be a file or a folder.   |
| `output_dir`      | Where the main folder is created (env vars expanded). Optional.   |
| `add_data_kb`     | KB of random padding for `add_data.py` (default 4).               |
| `add_data_script` | Override path to `add_data.py` (default: the bundled `add_data.py`). |

Subfolders inside a source folder are collected too, preserving their
structure. Environment variables in paths (e.g. `%LOCALAPPDATA%`,
`%USERPROFILE%`) are expanded.

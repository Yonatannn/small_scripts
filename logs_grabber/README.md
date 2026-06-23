# logs_grabber

Collects log files from predefined locations on a machine, packages them,
and produces three artifacts plus a separate dated backup in `%TEMP%`.

Target platform: **Windows 11, Python 3.10** (standard library only).

## What it does

When you run `grab_logs.py` it:

1. Reads `config.json` for the list of source locations and the output
   destination.
2. Copies **everything** from each configured source (files or whole
   folders) into a freshly organized package, grouped by source name.
3. Zips that package.
4. Runs `../transfer/add_data.py` on the zip to produce a padded `.bin`.
5. Keeps all **three** artifacts together in the output folder and opens
   that folder in Explorer.
6. In parallel, writes a **backup of everything to `%TEMP%`**, mirroring
   the *original* folder layout, under a top-level folder named by the
   backup date. That backup is finally kept **only as a single zip**.

## Output layout

Main output (path from `output_dir`, defaults to the Desktop):

```
LogsGrabber_<YYYY-MM-DD_HH-MM-SS>/
├── logs/                              <- organized package (by source name)
│   ├── windows_logs/...
│   └── myapp_local/...
├── LogsGrabber_<stamp>.zip            <- zip of logs/
└── LogsGrabber_<stamp>.zip.bin        <- add_data.py output
```

Temp backup (mirrors the original paths, kept only as a zip):

```
%TEMP%/LogsGrabber/<YYYY-MM-DD>.zip
   (inside: <YYYY-MM-DD>/C/Windows/Logs/..., etc.)
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

## Usage

```bat
python grab_logs.py
python grab_logs.py -c custom_config.json
python grab_logs.py --no-open
```

Log files that are locked / in use are skipped with a warning rather than
aborting the run.

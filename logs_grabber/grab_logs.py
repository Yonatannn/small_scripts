#!/usr/bin/env python3
"""Logs grabber: collect log files from predefined locations, package them,
zip the package, run transfer/add_data.py on the zip, and keep all three
artifacts. A mirrored backup of everything (by original folder layout) is
also written to %TEMP% and kept there only as a zip.

Target platform: Windows 11, Python 3.10.
"""
import argparse
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def load_config(config_path):
    try:
        return json.loads(pathlib.Path(config_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Error: config not found: {config_path!r}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in config: {e}", file=sys.stderr)
        sys.exit(1)


def validate_config(config):
    sources = config.get("sources", [])
    if not sources:
        print("Error: config has no 'sources' to collect.", file=sys.stderr)
        sys.exit(1)
    seen = set()
    for src in sources:
        name = src.get("name")
        if not name:
            print("Error: a source entry is missing 'name'.", file=sys.stderr)
            sys.exit(1)
        if not src.get("path"):
            print(f"Error: source '{name}' is missing 'path'.", file=sys.stderr)
            sys.exit(1)
        if name in seen:
            print(f"Error: duplicate source name: {name!r}", file=sys.stderr)
            sys.exit(1)
        seen.add(name)


def copy_tree_safe(src, dst):
    """Copy a directory tree, skipping files that can't be read (e.g. locked
    log files in use). Returns (copied, skipped)."""
    copied = skipped = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for f in files:
            s = os.path.join(root, f)
            d = os.path.join(target_root, f)
            try:
                shutil.copy2(s, d)
                copied += 1
            except OSError as e:
                print(f"    [skip] {s}: {e}")
                skipped += 1
    return copied, skipped


def copy_source(path, dest_dir):
    """Copy a source (file or directory) into dest_dir. Returns (copied, skipped)."""
    p = pathlib.Path(path)
    if not p.exists():
        print(f"  [WARN] source not found, skipping: {path}")
        return 0, 0
    if p.is_dir():
        os.makedirs(dest_dir, exist_ok=True)
        return copy_tree_safe(str(p), str(dest_dir))
    os.makedirs(dest_dir, exist_ok=True)
    try:
        shutil.copy2(str(p), str(pathlib.Path(dest_dir) / p.name))
        return 1, 0
    except OSError as e:
        print(f"    [skip] {p}: {e}")
        return 0, 1


def mirror_relpath(abs_path):
    """Turn an absolute Windows path into a relative path that preserves the
    original folder layout, e.g. C:\\Windows\\Logs -> C\\Windows\\Logs and
    \\\\server\\share\\x -> UNC\\server\\share\\x."""
    p = pathlib.PureWindowsPath(abs_path)
    parts = list(p.parts)
    if not parts:
        return pathlib.Path("unknown")
    anchor = parts[0]
    rest = parts[1:]
    if p.drive.startswith("\\\\"):
        # UNC: anchor like \\server\share
        unc = p.drive.strip("\\").replace("\\", os.sep)
        return pathlib.Path("UNC", unc, *rest)
    drive = anchor.rstrip(":\\/") or "ROOT"
    return pathlib.Path(drive, *rest)


def make_zip(folder, zip_path):
    """Zip the contents of `folder` into `zip_path` (a .zip path)."""
    zip_path = pathlib.Path(zip_path)
    base = zip_path.with_suffix("") if zip_path.suffix == ".zip" else zip_path
    shutil.make_archive(str(base), "zip", root_dir=str(folder))
    return pathlib.Path(str(base) + ".zip")


def run_add_data(add_data_script, zip_path, bin_path, kb):
    """Run transfer/add_data.py on the zip to produce the .bin artifact."""
    cmd = [
        sys.executable, str(add_data_script),
        str(zip_path),
        "-k", str(kb),
        "-o", str(bin_path),
    ]
    print(f"  Running add_data.py ({kb} KB padding)...")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"  [ERROR] add_data.py failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(1)


def open_folder(path):
    try:
        os.startfile(str(path))  # Windows only
    except AttributeError:
        # Non-Windows fallback (dev/testing)
        subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as e:
        print(f"  [WARN] could not open folder: {e}")


def main():
    parser = argparse.ArgumentParser(
        prog="grab_logs.py",
        description="Collect logs from predefined locations, package, zip, "
                    "pad with add_data.py, and back up to %TEMP%.",
    )
    parser.add_argument("-c", "--config", default="config.json", metavar="FILE",
                        help="Path to config JSON (default: config.json next to this script)")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open the output folder when finished")
    args = parser.parse_args()

    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = pathlib.Path(__file__).parent / config_path

    config = load_config(config_path)
    validate_config(config)

    sources = config["sources"]
    kb = int(config.get("add_data_kb", 4))

    # Locate transfer/add_data.py (repo-relative by default, overridable).
    script_dir = pathlib.Path(__file__).resolve().parent
    add_data_script = config.get("add_data_script")
    if add_data_script:
        add_data_script = pathlib.Path(add_data_script)
        if not add_data_script.is_absolute():
            add_data_script = script_dir / add_data_script
    else:
        add_data_script = script_dir.parent / "transfer" / "add_data.py"
    if not add_data_script.is_file():
        print(f"Error: add_data.py not found at {add_data_script}", file=sys.stderr)
        sys.exit(1)

    # Output destination from config (fall back to Desktop).
    output_dir = config.get("output_dir")
    if output_dir:
        output_dir = pathlib.Path(os.path.expandvars(output_dir))
    else:
        output_dir = pathlib.Path.home() / "Desktop"
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    date_only = now.strftime("%Y-%m-%d")

    # --- Layout ---------------------------------------------------------
    # Main output folder (opened at the end), holding the three artifacts:
    #   <output_dir>/LogsGrabber_<stamp>/
    #       logs/                       (the freshly organized package)
    #       LogsGrabber_<stamp>.zip
    #       LogsGrabber_<stamp>.zip.bin
    bundle_name = f"LogsGrabber_{stamp}"
    bundle_dir = output_dir / bundle_name
    organized_dir = bundle_dir / "logs"
    organized_dir.mkdir(parents=True, exist_ok=True)

    # Temp backup mirroring the original folder layout under a date folder.
    temp_root = pathlib.Path(tempfile.gettempdir()) / "LogsGrabber"
    temp_date_dir = temp_root / date_only
    temp_date_dir.mkdir(parents=True, exist_ok=True)

    section("Collecting logs")
    total_copied = total_skipped = 0
    for src in sources:
        name = src["name"]
        path = os.path.expandvars(src["path"])
        print(f"\n  [{name}] {path}")

        # 1) organized package, grouped by source name
        organized_target = organized_dir / name
        copied, skipped = copy_source(path, organized_target)
        total_copied += copied
        total_skipped += skipped
        print(f"    copied {copied} file(s){', skipped %d' % skipped if skipped else ''}")

        # 2) temp backup, mirroring the original folder layout.
        # Copy from the organized copy we just made (avoids re-reading the
        # source, and keeps both copies consistent).
        if copied:
            mirror_target = temp_date_dir / mirror_relpath(path)
            src_path = pathlib.Path(path)
            if src_path.is_dir():
                # organized_target holds the folder's contents -> place them
                # directly under the mirrored folder path.
                shutil.copytree(organized_target, mirror_target, dirs_exist_ok=True)
            else:
                # File source: mirror path already ends with the file name.
                mirror_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(organized_target / src_path.name, mirror_target)

    print(f"\n  Total: {total_copied} file(s) copied, {total_skipped} skipped.")

    # --- Main bundle: zip + add_data --------------------------------------
    section("Packaging main bundle")
    zip_path = bundle_dir / f"{bundle_name}.zip"
    print(f"  Zipping organized folder -> {zip_path.name}")
    make_zip(organized_dir, zip_path)

    bin_path = bundle_dir / f"{bundle_name}.zip.bin"
    run_add_data(add_data_script, zip_path, bin_path, kb)

    print(f"\n  Bundle artifacts in {bundle_dir}:")
    print(f"    - logs/                 (organized folder)")
    print(f"    - {zip_path.name}")
    print(f"    - {bin_path.name}")

    # --- Temp backup: zip and keep only the zip ---------------------------
    section("Backing up to %TEMP%")
    temp_zip = temp_root / f"{date_only}.zip"
    if temp_zip.exists():
        # Don't clobber an earlier backup from the same day.
        temp_zip = temp_root / f"{date_only}_{now.strftime('%H-%M-%S')}.zip"
    print(f"  Zipping backup -> {temp_zip}")
    make_zip(temp_date_dir, temp_zip)
    # Keep only the zip in temp.
    shutil.rmtree(temp_date_dir, ignore_errors=True)
    print(f"  Backup saved (zip only): {temp_zip}")

    section("Done")
    print(f"\n  Output folder: {bundle_dir}")
    print(f"  Temp backup  : {temp_zip}\n")

    if not args.no_open:
        open_folder(bundle_dir)


if __name__ == "__main__":
    main()

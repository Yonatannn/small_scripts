#!/usr/bin/env python3
"""Logs grabber core + CLI.

Collect log files from predefined locations, package them into a folder
named "Logs - <date>", zip the package, run transfer/add_data.py on the
zip, and keep all three artifacts. A mirrored backup of everything (by
original folder layout) is also written to %TEMP% and kept there only as a
zip. An optional Hebrew description is saved as info.txt inside the main
folder.

The collection logic lives in run_grab() so it can be driven from both
this CLI and the GUI (gui.py).

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


class GrabError(Exception):
    """Raised on a fatal problem; callers decide how to report it."""


def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def load_config(config_path):
    try:
        return json.loads(pathlib.Path(config_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GrabError(f"config not found: {config_path!r}")
    except json.JSONDecodeError as e:
        raise GrabError(f"invalid JSON in config: {e}")


def validate_config(config):
    sources = config.get("sources", [])
    if not sources:
        raise GrabError("config has no 'sources' to collect.")
    seen = set()
    for src in sources:
        name = src.get("name")
        if not name:
            raise GrabError("a source entry is missing 'name'.")
        if not src.get("path"):
            raise GrabError(f"source '{name}' is missing 'path'.")
        if name in seen:
            raise GrabError(f"duplicate source name: {name!r}")
        seen.add(name)


def path_size(path):
    """Total size in bytes of a file or directory tree (best effort)."""
    p = pathlib.Path(path)
    if not p.exists():
        return 0
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def copy_tree_safe(src, dst, log=print, on_bytes=None):
    """Copy a directory tree, skipping files that can't be read (e.g. locked
    log files in use). Returns (copied, skipped). on_bytes(n) is called with
    the size of each file successfully copied."""
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
                if on_bytes:
                    try:
                        on_bytes(os.path.getsize(d))
                    except OSError:
                        pass
            except OSError as e:
                log(f"    [skip] {s}: {e}")
                skipped += 1
    return copied, skipped


def copy_source(path, dest_dir, log=print, on_bytes=None):
    """Copy a source (file or directory) into dest_dir. Returns (copied, skipped)."""
    p = pathlib.Path(path)
    if not p.exists():
        log(f"  [WARN] source not found, skipping: {path}")
        return 0, 0
    if p.is_dir():
        os.makedirs(dest_dir, exist_ok=True)
        return copy_tree_safe(str(p), str(dest_dir), log=log, on_bytes=on_bytes)
    os.makedirs(dest_dir, exist_ok=True)
    try:
        dest = pathlib.Path(dest_dir) / p.name
        shutil.copy2(str(p), str(dest))
        if on_bytes:
            try:
                on_bytes(os.path.getsize(dest))
            except OSError:
                pass
        return 1, 0
    except OSError as e:
        log(f"    [skip] {p}: {e}")
        return 0, 1


def _counting_copy2(on_bytes):
    """A copy_function for shutil.copytree that reports bytes copied."""
    def _cp(src, dst, *, follow_symlinks=True):
        shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
        if on_bytes:
            try:
                on_bytes(os.path.getsize(dst))
            except OSError:
                pass
    return _cp


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
        unc = p.drive.strip("\\").replace("\\", os.sep)
        return pathlib.Path("UNC", unc, *rest)
    drive = anchor.rstrip(":\\/") or "ROOT"
    return pathlib.Path(drive, *rest)


def make_zip(src_dir, zip_path, base_dir=None):
    """Zip a directory into zip_path. With base_dir set, the archive contains
    that folder as its top-level entry; otherwise just the contents."""
    zip_path = pathlib.Path(zip_path)
    base = zip_path.with_suffix("") if zip_path.suffix == ".zip" else zip_path
    if base_dir:
        shutil.make_archive(str(base), "zip", root_dir=str(src_dir), base_dir=base_dir)
    else:
        shutil.make_archive(str(base), "zip", root_dir=str(src_dir))
    return pathlib.Path(str(base) + ".zip")


def run_add_data(add_data_script, zip_path, bin_path, kb, log=print):
    """Run transfer/add_data.py on the zip to produce the .bin artifact."""
    cmd = [
        sys.executable, str(add_data_script),
        str(zip_path),
        "-k", str(kb),
        "-o", str(bin_path),
    ]
    log(f"  Running add_data.py ({kb} KB padding)...")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise GrabError(f"add_data.py failed (exit {result.returncode})")


def open_folder(path, log=print):
    try:
        os.startfile(str(path))  # Windows only
    except AttributeError:
        subprocess.run(["xdg-open", str(path)], check=False)  # dev/testing fallback
    except OSError as e:
        log(f"  [WARN] could not open folder: {e}")


def resolve_add_data_script(config):
    script_dir = pathlib.Path(__file__).resolve().parent
    add_data_script = config.get("add_data_script")
    if add_data_script:
        add_data_script = pathlib.Path(add_data_script)
        if not add_data_script.is_absolute():
            add_data_script = script_dir / add_data_script
    else:
        add_data_script = script_dir.parent / "transfer" / "add_data.py"
    if not add_data_script.is_file():
        raise GrabError(f"add_data.py not found at {add_data_script}")
    return add_data_script


def resolve_output_dir(config, override=None):
    output_dir = override or config.get("output_dir")
    if output_dir:
        return pathlib.Path(os.path.expandvars(str(output_dir)))
    return pathlib.Path.home() / "Desktop"


def _unique_dir(parent, base, stamp):
    d = parent / base
    if d.exists():
        d = parent / f"{base} ({stamp})"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_info_file(folder, description, included, excluded, now):
    """Save the Hebrew description + collection summary as info.txt.
    UTF-8 with BOM so Windows Notepad renders Hebrew correctly."""
    lines = []
    if description and description.strip():
        lines.append(description.strip())
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
    lines.append(f"תאריך גיבוי: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("סוגי לוגים שנאספו:")
    for n in included:
        lines.append(f"  + {n}")
    if excluded:
        lines.append("")
        lines.append("סוגי לוגים שהוחרגו (לא נאספו):")
        for n in excluded:
            lines.append(f"  - {n}")
    (pathlib.Path(folder) / "info.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8-sig")


def run_grab(config, selected_names=None, description="", output_dir=None,
             kb=None, log=print, open_when_done=True, progress=None):
    """Run the full grab. Returns a dict of result paths. Raises GrabError.

    progress(fraction, stage) is called with fraction in 0..1 and a short
    Hebrew stage label, so a GUI can drive a progress bar / ETA.
    """
    def report(frac, stage):
        if progress:
            progress(min(max(frac, 0.0), 1.0), stage)

    validate_config(config)

    sources = config["sources"]
    all_names = [s["name"] for s in sources]
    if selected_names is None:
        selected = list(sources)
    else:
        sel = set(selected_names)
        selected = [s for s in sources if s["name"] in sel]
    if not selected:
        raise GrabError("no sources selected to collect.")
    included = [s["name"] for s in selected]
    excluded = [n for n in all_names if n not in set(included)]

    if kb is None:
        kb = int(config.get("add_data_kb", 4))
    add_data_script = resolve_add_data_script(config)

    out_root = resolve_output_dir(config, output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    stamp = now.strftime("%H-%M-%S")
    date_only = now.strftime("%Y-%m-%d")
    folder_name = f"Logs - {date_only}"

    # Main output folder "Logs - <date>" holding the three artifacts + info.txt
    bundle_dir = _unique_dir(out_root, folder_name, stamp)
    organized_dir = bundle_dir / "logs"
    organized_dir.mkdir(parents=True, exist_ok=True)

    # Temp backup mirroring the original folder layout, under "Logs - <date>"
    temp_root = pathlib.Path(tempfile.gettempdir()) / "LogsGrabber"
    temp_date_dir = _unique_dir(temp_root, folder_name, stamp)

    # Pre-scan total bytes so we can show real progress + an ETA. Each byte is
    # copied twice (organized package + temp mirror), hence the factor of 2.
    report(0.0, "מחשב גודל...")
    scanned = sum(path_size(os.path.expandvars(s["path"])) for s in selected)
    total_units = max(1, 2 * scanned)
    COPY_FRAC = 0.85  # collection occupies 0..85% of the bar
    copied_units = 0

    def on_bytes(n):
        nonlocal copied_units
        copied_units += n
        report(COPY_FRAC * copied_units / total_units, current_stage)

    section("Collecting logs")
    if excluded:
        log(f"  Excluded (per selection): {', '.join(excluded)}")
    total_copied = total_skipped = 0
    for src in selected:
        name = src["name"]
        path = os.path.expandvars(src["path"])
        current_stage = f"מעתיק: {name}"
        log(f"\n  [{name}] {path}")
        report(COPY_FRAC * copied_units / total_units, current_stage)

        # 1) organized package, grouped by source name
        organized_target = organized_dir / name
        copied, skipped = copy_source(path, organized_target, log=log, on_bytes=on_bytes)
        total_copied += copied
        total_skipped += skipped
        log(f"    copied {copied} file(s)"
            + (f", skipped {skipped}" if skipped else ""))

        # 2) temp backup mirroring the original layout (from the organized copy)
        if copied:
            mirror_target = temp_date_dir / mirror_relpath(path)
            if pathlib.Path(path).is_dir():
                shutil.copytree(organized_target, mirror_target, dirs_exist_ok=True,
                                copy_function=_counting_copy2(on_bytes))
            else:
                mirror_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(organized_target / pathlib.Path(path).name, mirror_target)
                on_bytes(path_size(path))

    log(f"\n  Total: {total_copied} file(s) copied, {total_skipped} skipped.")
    report(COPY_FRAC, "כותב פרטים...")

    # info.txt in both the main folder and the temp backup folder
    _write_info_file(bundle_dir, description, included, excluded, now)
    _write_info_file(temp_date_dir, description, included, excluded, now)

    # --- Main bundle: zip + add_data --------------------------------------
    section("Packaging main bundle")
    report(0.88, "דוחס לקובץ ZIP...")
    zip_path = bundle_dir / f"{bundle_dir.name}.zip"
    log(f"  Zipping organized folder -> {zip_path.name}")
    make_zip(organized_dir, zip_path)

    report(0.93, "יוצר קובץ מאובטח...")
    bin_path = bundle_dir / f"{bundle_dir.name}.zip.bin"
    run_add_data(add_data_script, zip_path, bin_path, kb, log=log)

    log(f"\n  Bundle artifacts in {bundle_dir}:")
    log(f"    - logs/                 (organized folder)")
    log(f"    - {zip_path.name}")
    log(f"    - {bin_path.name}")
    log(f"    - info.txt")

    # --- Temp backup: zip (keep the named top folder) and keep only the zip --
    section("Backing up to %TEMP%")
    report(0.97, "מגבה...")
    temp_zip = temp_root / f"{temp_date_dir.name}.zip"
    log(f"  Zipping backup -> {temp_zip}")
    make_zip(temp_root, temp_zip, base_dir=temp_date_dir.name)
    shutil.rmtree(temp_date_dir, ignore_errors=True)
    log(f"  Backup saved (zip only): {temp_zip}")

    section("Done")
    log(f"\n  Output folder: {bundle_dir}")
    log(f"  Temp backup  : {temp_zip}\n")
    report(1.0, "הסתיים")

    if open_when_done:
        open_folder(bundle_dir, log=log)

    return {
        "bundle_dir": bundle_dir,
        "zip": zip_path,
        "bin": bin_path,
        "temp_zip": temp_zip,
        "copied": total_copied,
        "skipped": total_skipped,
    }


def resolve_config_path(config_arg):
    config_path = pathlib.Path(config_arg)
    if not config_path.is_absolute():
        config_path = pathlib.Path(__file__).parent / config_path
    return config_path


def main():
    parser = argparse.ArgumentParser(
        prog="grab_logs.py",
        description="Collect logs from predefined locations, package, zip, "
                    "pad with add_data.py, and back up to %TEMP%.",
    )
    parser.add_argument("-c", "--config", default="config.json", metavar="FILE",
                        help="Path to config JSON (default: config.json next to this script)")
    parser.add_argument("-o", "--output", metavar="DIR",
                        help="Override output directory from config")
    parser.add_argument("-d", "--description", default="", metavar="TEXT",
                        help="Free-text (Hebrew) description saved to info.txt")
    parser.add_argument("--only", metavar="NAMES",
                        help="Comma-separated source names to include (default: all)")
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open the output folder when finished")
    parser.add_argument("--gui", action="store_true",
                        help="Launch the graphical interface instead of running headless")
    args = parser.parse_args()

    if args.gui:
        import gui
        gui.main()
        return

    try:
        config = load_config(resolve_config_path(args.config))
        selected = None
        if args.only:
            selected = [s.strip() for s in args.only.split(",") if s.strip()]
        run_grab(
            config,
            selected_names=selected,
            description=args.description,
            output_dir=args.output,
            log=print,
            open_when_done=not args.no_open,
        )
    except GrabError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

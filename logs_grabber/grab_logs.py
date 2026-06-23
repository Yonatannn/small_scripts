#!/usr/bin/env python3
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


class GrabError(Exception):
    pass


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
                log(f"  [skip] {s}: {e}")
                skipped += 1
    return copied, skipped


def copy_source(path, dest_dir, log=print, on_bytes=None):
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
        log(f"  [skip] {p}: {e}")
        return 0, 1


def _counting_copy2(on_bytes):
    def _cp(src, dst, *, follow_symlinks=True):
        shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
        if on_bytes:
            try:
                on_bytes(os.path.getsize(dst))
            except OSError:
                pass
    return _cp


def mirror_relpath(abs_path):
    p = pathlib.PureWindowsPath(abs_path)
    parts = list(p.parts)
    if not parts:
        return pathlib.Path("unknown")
    rest = parts[1:]
    if p.drive.startswith("\\\\"):
        unc = p.drive.strip("\\").replace("\\", os.sep)
        return pathlib.Path("UNC", unc, *rest)
    drive = parts[0].rstrip(":\\/") or "ROOT"
    return pathlib.Path(drive, *rest)


def make_zip(src_dir, zip_path, base_dir=None):
    zip_path = pathlib.Path(zip_path)
    base = zip_path.with_suffix("") if zip_path.suffix == ".zip" else zip_path
    if base_dir:
        shutil.make_archive(str(base), "zip", root_dir=str(src_dir), base_dir=base_dir)
    else:
        shutil.make_archive(str(base), "zip", root_dir=str(src_dir))
    return pathlib.Path(str(base) + ".zip")


def run_add_data(add_data_script, zip_path, bin_path, kb, log=print):
    cmd = [sys.executable, str(add_data_script), str(zip_path),
           "-k", str(kb), "-o", str(bin_path)]
    log(f"  Running add_data.py ({kb} KB padding)...")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise GrabError(f"add_data.py failed (exit {result.returncode})")


def open_folder(path, log=print):
    try:
        os.startfile(str(path))
    except AttributeError:
        subprocess.run(["xdg-open", str(path)], check=False)
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


def resolve_output_dir(config):
    out = config.get("output_dir")
    if out:
        return pathlib.Path(os.path.expandvars(str(out)))
    return pathlib.Path.home() / "Desktop"


def resolve_config_path():
    return pathlib.Path(__file__).resolve().parent / "config.json"


def _unique_dir(parent, base, stamp):
    d = parent / base
    if d.exists():
        d = parent / f"{base} ({stamp})"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_info_file(folder, description, included, excluded, now):
    lines = []
    if description and description.strip():
        lines.append(description.strip())
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
    lines.append(f"Backup date: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("Log types collected:")
    for n in included:
        lines.append(f"  + {n}")
    if excluded:
        lines.append("")
        lines.append("Log types excluded (not collected):")
        for n in excluded:
            lines.append(f"  - {n}")
    (pathlib.Path(folder) / "info.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8-sig")


def run_grab(config, selected_names=None, description="", log=print,
             open_when_done=True, progress=None):
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

    kb = int(config.get("add_data_kb", 4))
    add_data_script = resolve_add_data_script(config)

    out_root = resolve_output_dir(config)
    out_root.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    stamp = now.strftime("%H-%M-%S")
    folder_name = f"Logs - {now.strftime('%Y-%m-%d')}"

    bundle_dir = _unique_dir(out_root, folder_name, stamp)
    organized_dir = bundle_dir / "logs"
    organized_dir.mkdir(parents=True, exist_ok=True)

    temp_root = pathlib.Path(tempfile.gettempdir()) / "LogsGrabber"
    temp_date_dir = _unique_dir(temp_root, folder_name, stamp)

    report(0.0, "Scanning...")
    scanned = sum(path_size(os.path.expandvars(s["path"])) for s in selected)
    total_units = max(1, 2 * scanned)
    COPY_FRAC = 0.85
    copied_units = 0

    def on_bytes(n):
        nonlocal copied_units
        copied_units += n
        report(COPY_FRAC * copied_units / total_units, current_stage)

    log("Collecting logs...")
    if excluded:
        log(f"  Excluded: {', '.join(excluded)}")
    total_copied = total_skipped = 0
    for src in selected:
        name = src["name"]
        path = os.path.expandvars(src["path"])
        current_stage = f"Copying: {name}"
        log(f"  [{name}] {path}")
        report(COPY_FRAC * copied_units / total_units, current_stage)

        organized_target = organized_dir / name
        copied, skipped = copy_source(path, organized_target, log=log, on_bytes=on_bytes)
        total_copied += copied
        total_skipped += skipped

        if copied:
            mirror_target = temp_date_dir / mirror_relpath(path)
            if pathlib.Path(path).is_dir():
                shutil.copytree(organized_target, mirror_target, dirs_exist_ok=True,
                                copy_function=_counting_copy2(on_bytes))
            else:
                mirror_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(organized_target / pathlib.Path(path).name, mirror_target)
                on_bytes(path_size(path))

    log(f"  Total: {total_copied} copied, {total_skipped} skipped.")
    report(COPY_FRAC, "Writing details...")

    _write_info_file(bundle_dir, description, included, excluded, now)
    _write_info_file(temp_date_dir, description, included, excluded, now)

    report(0.88, "Creating ZIP...")
    zip_path = bundle_dir / f"{bundle_dir.name}.zip"
    make_zip(organized_dir, zip_path)

    report(0.93, "Creating .bin...")
    bin_path = bundle_dir / f"{bundle_dir.name}.zip.bin"
    run_add_data(add_data_script, zip_path, bin_path, kb, log=log)

    report(0.97, "Backing up...")
    temp_zip = temp_root / f"{temp_date_dir.name}.zip"
    make_zip(temp_root, temp_zip, base_dir=temp_date_dir.name)
    shutil.rmtree(temp_date_dir, ignore_errors=True)

    log(f"Done. Output: {bundle_dir}")
    log(f"Backup: {temp_zip}")
    report(1.0, "Done")

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


def main():
    try:
        config = load_config(resolve_config_path())
        run_grab(config, log=print)
    except GrabError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

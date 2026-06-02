#!/usr/bin/env python3
import argparse
import json
import pathlib
import shutil
import subprocess
import sys


def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def confirm_overwrite(label):
    while True:
        ans = input(f"\n  '{label}' already exists. Overwrite? [y/n]: ").strip().lower()
        if ans in ("y", "n"):
            return ans == "y"
        print("  Please enter y or n.")


def robocopy(src, dest):
    pathlib.Path(dest).mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["robocopy", str(src), str(dest), "/E", "/NJH", "/NJS"],
        check=False
    )
    if result.returncode > 7:
        print(f"  [ERROR] robocopy failed (exit {result.returncode}): {src} -> {dest}",
              file=sys.stderr)
        sys.exit(1)



def fetch_program(name, prog_cfg, dest_dir):
    dest_dir = pathlib.Path(dest_dir)
    if "smb_source" in prog_cfg:
        smb = pathlib.PureWindowsPath(prog_cfg["smb_source"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        if smb.suffix:
            # Direct path to a file — copy just that file
            print(f"  Copying '{name}' from SMB: {prog_cfg['smb_source']}")
            result = subprocess.run(
                ["robocopy", str(smb.parent), str(dest_dir), smb.name, "/NJH", "/NJS"],
                check=False
            )
            if result.returncode > 7:
                print(f"  [ERROR] robocopy failed (exit {result.returncode})", file=sys.stderr)
                sys.exit(1)
        else:
            # Path to a directory — copy everything inside
            print(f"  Copying '{name}' from SMB folder: {prog_cfg['smb_source']}")
            robocopy(prog_cfg["smb_source"], dest_dir)
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Downloading '{name}' via winget ({prog_cfg['winget_id']})...")
        result = subprocess.run([
            "winget", "download", "--id", prog_cfg["winget_id"],
            "--download-directory", str(dest_dir),
            "--accept-source-agreements", "--accept-package-agreements"
        ], check=False)
        if result.returncode != 0:
            print(f"  [WARN] winget download may have failed for '{name}' (exit {result.returncode})")


def clone_repo(repo_cfg, dest_dir):
    dest_dir = pathlib.Path(dest_dir)
    cmd = ["git", "clone", "--recurse-submodules", repo_cfg["url"], str(dest_dir)]

    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"  [ERROR] git clone failed for '{repo_cfg['name']}'", file=sys.stderr)
        sys.exit(1)


def download_wheels(repo_dir, python_version, requirements=None):
    repo_dir = pathlib.Path(repo_dir)
    req_file = repo_dir / (requirements or "requirements.txt")

    if not req_file.exists():
        print(f"  [skip] requirements not found: {req_file.relative_to(repo_dir)}")
        return

    deps_dir = repo_dir / "deps"
    deps_dir.mkdir(parents=True, exist_ok=True)

    # e.g. "3.12" or "3.12.10" -> "312"
    py_ver = python_version.replace(".", "")[:3]

    base_flags = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(deps_dir),
        "--platform", "win_amd64",
        "--python-version", py_ver,
        "--implementation", "cp",
        "--abi", f"cp{py_ver}",
        "--only-binary=:all:",
    ]

    print(f"  Downloading bootstrap wheels (setuptools, wheel)...")
    subprocess.run(base_flags + ["setuptools", "wheel"], check=False)

    print(f"  Downloading wheels for '{repo_dir.name}'...")
    result = subprocess.run(base_flags + ["-r", str(req_file)], check=False)
    if result.returncode != 0:
        print(f"  [ERROR] pip download failed for '{repo_dir.name}'", file=sys.stderr)
        print("  Hint: some packages may not have Windows binary wheels. Check PyPI.",
              file=sys.stderr)
        sys.exit(1)

    count = sum(1 for f in deps_dir.iterdir() if f.suffix == ".whl")
    print(f"  {count} wheel(s) saved to {repo_dir.name}/deps/")
    generate_deps_bat(deps_dir, repo_dir.name)


def _write_bat(path, lines):
    pathlib.Path(path).write_text("\r\n".join(lines) + "\r\n", encoding="cp1252")


def _program_install_lines(folder_expr, name):
    """Return bat lines that pushd into folder_expr and install all .exe/.msi files."""
    lines = [
        f'pushd "{folder_expr}"',
        'for %%F in (*.exe) do (',
        '    echo   Running %%F ...',
        '    "%%F" /S /quiet /norestart /VERYSILENT /NORESTART',
        ')',
        'for %%F in (*.msi) do (',
        '    echo   Running %%F ...',
        '    msiexec /i "%%F" /quiet /norestart',
        ')',
        'popd',
    ]
    if name.lower() == "python":
        lines += [
            ":: Refresh PATH so python/pip are visible in this session",
            'for /f "tokens=2*" %%A in (\'reg query "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment" /v Path 2^>nul\') do set "SYSPATH=%%B"',
            'set "PATH=%SYSPATH%;%PATH%"',
        ]
    return lines


def generate_program_bat(dest_dir, name):
    lines = [
        "@echo off",
        f"echo Installing {name}...",
        "",
    ] + _program_install_lines("%~dp0", name) + [
        "",
        "echo Done.",
        "pause",
    ]
    _write_bat(pathlib.Path(dest_dir) / "install.bat", lines)
    print(f"  Created: programs/{name}/install.bat")


def generate_deps_bat(deps_dir, repo_name):
    lines = [
        "@echo off",
        f"echo Installing pip packages for {repo_name}...",
        "",
        'pushd "%~dp0"',
        'for %%W in (*.whl) do pip install --no-index "%%W"',
        'popd',
        "",
        "echo Done.",
        "pause",
    ]
    _write_bat(pathlib.Path(deps_dir) / "install.bat", lines)
    print(f"  Created: {repo_name}/deps/install.bat")


def generate_install_bat(usb_root, config):
    programs = config.get("programs", [])
    repos = config.get("repos", [])

    lines = [
        "@echo off",
        'set "USB=%~dp0"',
        "",
        "echo ============================================================",
        "echo   USB Offline Installer",
        "echo ============================================================",
    ]

    for prog in programs:
        name = prog["name"]
        lines += [
            "",
            "echo.",
            f"echo --- Installing {name} ---",
        ] + _program_install_lines(f"%USB%programs\\{name}", name)

    for repo in repos:
        name = repo["name"]
        lines += [
            "",
            "echo.",
            f"echo --- pip install: {name} ---",
            f'if exist "%USB%repos\\{name}\\deps\\" (',
            f'    pushd "%USB%repos\\{name}\\deps"',
            f'    for %%W in (*.whl) do pip install --no-index "%%W"',
            f'    popd',
            ") else (",
            f"    echo   [skip] no deps folder for {name}",
            ")",
        ]

    lines += [
        "",
        "echo.",
        "echo ============================================================",
        "echo   Done.",
        "echo ============================================================",
        "pause",
    ]

    _write_bat(pathlib.Path(usb_root) / "install.bat", lines)
    print(f"  Created: install.bat")


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
    for prog in config.get("programs", []):
        has_smb = "smb_source" in prog
        has_winget = "winget_id" in prog
        if has_smb and has_winget:
            print(f"Error: program '{prog.get('name', '?')}' has both smb_source and winget_id — use one only.",
                  file=sys.stderr)
            sys.exit(1)
        if not has_smb and not has_winget:
            print(f"Error: program '{prog.get('name', '?')}' needs either smb_source or winget_id.",
                  file=sys.stderr)
            sys.exit(1)
    for repo in config.get("repos", []):
        if not repo.get("name"):
            print("Error: repo entry missing 'name'", file=sys.stderr)
            sys.exit(1)
        if not repo.get("url"):
            print(f"Error: repo '{repo['name']}' missing 'url'", file=sys.stderr)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="prepare_usb.py",
        description="Prepare a USB drive for offline Windows deployment"
    )
    parser.add_argument("usb_drive", help="USB root path (e.g. E:\\\\)")
    parser.add_argument("-c", "--config", default="config.json", metavar="FILE",
                        help="Path to config JSON (default: config.json)")
    args = parser.parse_args()

    usb_root = pathlib.Path(args.usb_drive)
    if not usb_root.is_dir():
        print(f"Error: path not found: {usb_root!r}", file=sys.stderr)
        sys.exit(1)

    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        print("Error: git not found on PATH. Install Git before running this script.",
              file=sys.stderr)
        sys.exit(1)

    config_path = pathlib.Path(args.config)
    if not config_path.is_absolute():
        config_path = pathlib.Path(__file__).parent / config_path

    config = load_config(config_path)
    validate_config(config)

    python_version = config.get("python_version", "3.12")

    # 1. Programs
    programs = config.get("programs", [])
    if programs:
        section("Downloading Programs")
        for prog in programs:
            dest = usb_root / "programs" / prog["name"]
            if dest.exists():
                if not confirm_overwrite(f"programs/{prog['name']}"):
                    print(f"  [skip] programs/{prog['name']}")
                    generate_program_bat(dest, prog["name"])
                    continue
                shutil.rmtree(dest)
            fetch_program(prog["name"], prog, dest)
            generate_program_bat(dest, prog["name"])

    # 2. OS images
    os_images = config.get("os_images", [])
    if os_images:
        section("Copying OS Images")
        for img in os_images:
            name = img["name"]
            dest = usb_root / "OS" / name
            if dest.exists():
                if not confirm_overwrite(f"OS/{name}"):
                    print(f"  [skip] OS/{name}")
                    continue
                shutil.rmtree(dest)
            smb = pathlib.PureWindowsPath(img["smb_source"])
            dest.mkdir(parents=True, exist_ok=True)
            print(f"  Copying '{name}' from: {img['smb_source']}")
            if smb.suffix:
                result = subprocess.run(
                    ["robocopy", str(smb.parent), str(dest), smb.name, "/NJH", "/NJS"],
                    check=False
                )
                if result.returncode > 7:
                    print(f"  [ERROR] robocopy failed (exit {result.returncode})", file=sys.stderr)
                    sys.exit(1)
            else:
                robocopy(img["smb_source"], dest)

    # 3. Repos + wheels
    repos = config.get("repos", [])
    if repos:
        section("Cloning Repos & Downloading Wheels")
        for repo in repos:
            print(f"\n  [{repo['name']}]")
            repo_dir = usb_root / "repos" / repo["name"]
            if repo_dir.exists():
                if not confirm_overwrite(f"repos/{repo['name']}"):
                    print(f"  [skip] repos/{repo['name']}")
                    continue
                shutil.rmtree(repo_dir)
            clone_repo(repo, repo_dir)
            download_wheels(repo_dir, python_version, requirements=repo.get("requirements"))

    # 4. install.bat
    section("Generating install.bat")
    generate_install_bat(usb_root, config)

    section("Done")
    print(f"\n  USB ready at: {usb_root}")
    print("  Run install.bat on the target Windows machine.\n")


if __name__ == "__main__":
    main()

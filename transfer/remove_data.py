#!/usr/bin/env python3
import argparse
import os
import sys

MAGIC_SIZE = 32
NUM_SIZE = 4
HEADER_FIXED = MAGIC_SIZE + NUM_SIZE + 1
CHUNK = 65536


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def read_kb(path):
    if os.path.getsize(path) < HEADER_FIXED:
        raise ValueError(f"file too small to contain a valid header")
    with open(path, "rb") as f:
        f.seek(MAGIC_SIZE)
        num = f.read(NUM_SIZE)
        nl = f.read(1)
    try:
        num_str = num.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError(f"invalid header: non-ASCII bytes at offset {MAGIC_SIZE}")
    if not num_str.isdigit() or nl != b"\n":
        raise ValueError(f"invalid header: expected 4 digits + newline, got {num!r}{nl!r}")
    kb = int(num_str)
    if kb == 0:
        raise ValueError("invalid header: KB count is 0")
    return kb


def main():
    parser = argparse.ArgumentParser(prog="remove_data.py")
    parser.add_argument("input", help="Padded .bin file")
    parser.add_argument("-o", "--output", metavar="FILE",
                        help="Output path (default: strips .bin, or appends .restored)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: file not found: {args.input!r}", file=sys.stderr)
        sys.exit(1)

    try:
        kb = read_kb(args.input)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    skip = HEADER_FIXED + kb * 1024
    file_size = os.path.getsize(args.input)

    if skip >= file_size:
        print(f"Error: header claims {kb} KB padding but file is only {human_size(file_size)}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output = args.output
    elif args.input.lower().endswith(".bin"):
        output = args.input[:-4]
    else:
        output = args.input + ".restored"

    restored = file_size - skip

    if args.verbose:
        print(f"  Input  : {args.input} ({human_size(file_size)})")
        print(f"  Skip   : {skip} bytes ({HEADER_FIXED} header + {kb} KB padding)")
        print(f"  Output : {output} ({human_size(restored)})")

    try:
        with open(args.input, "rb") as src, open(output, "wb") as dst:
            src.seek(skip)
            while chunk := src.read(CHUNK):
                dst.write(chunk)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        try:
            os.remove(output)
        except OSError:
            pass
        sys.exit(1)

    print(f"Done → {output}")


if __name__ == "__main__":
    main()

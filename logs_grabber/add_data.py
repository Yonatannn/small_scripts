#!/usr/bin/env python3
import argparse
import os
import sys

MAGIC_SIZE = 32
CHUNK = 65536


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main():
    parser = argparse.ArgumentParser(prog="add_data.py")
    parser.add_argument("input", help="File to pad")
    parser.add_argument("-k", "--kb", type=int, default=4, metavar="KB",
                        help="KB of random padding to prepend (default: 4, max: 9999)")
    parser.add_argument("-o", "--output", metavar="FILE",
                        help="Output path (default: <input>.bin)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.kb <= 9999:
        print(f"Error: --kb must be 1–9999, got {args.kb}", file=sys.stderr)
        sys.exit(2)

    if not os.path.isfile(args.input):
        print(f"Error: file not found: {args.input!r}", file=sys.stderr)
        sys.exit(1)

    output = args.output or args.input + ".bin"
    padding = args.kb * 1024
    header = MAGIC_SIZE + 5 + padding

    if args.verbose:
        print(f"  Input  : {args.input} ({human_size(os.path.getsize(args.input))})")
        print(f"  Output : {output}")
        print(f"  Padding: {args.kb} KB")
        print(f"  Total  : {human_size(header + os.path.getsize(args.input))}")

    try:
        with open(output, "wb") as out:
            out.write(os.urandom(MAGIC_SIZE))
            out.write(f"{args.kb:04d}\n".encode())
            remaining = padding
            while remaining > 0:
                n = min(CHUNK, remaining)
                out.write(os.urandom(n))
                remaining -= n
            with open(args.input, "rb") as src:
                while chunk := src.read(CHUNK):
                    out.write(chunk)
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

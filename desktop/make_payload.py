#!/usr/bin/env python3
"""
Zip the built program folder into the payload the setup file carries.

Deflate rather than LZMA: LZMA would make the setup file a little smaller, but
the payload is unpacked on the user's computer and deflate unpacks several
times faster. How long the person waits is the number that matters.
"""
import argparse
import os
import stat
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import app_info                                               # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--source", default=str(HERE / "dist" / app_info.APP_NAME),
                        help="the program folder PyInstaller built")
    parser.add_argument("--out", default=str(HERE / "build" / "payload" / "payload.zip"),
                        help="where to write payload.zip")
    args = parser.parse_args()
    source, out = Path(args.source), Path(args.out)
    if not source.is_dir():
        print(f"ERROR: {source} not found - build the program folder first.")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    # A Windows build has no symbolic links; a Linux test build does (shared
    # libraries), and they are stored as links rather than second copies.
    files = sorted(p for p in source.rglob("*") if p.is_file() or p.is_symlink())
    raw = sum(p.stat().st_size for p in files if not p.is_symlink())
    longest = max((len(str(p.relative_to(source))) for p in files), default=0)
    print(f"  packing {len(files):,} files ({raw / 1e6:.0f} MB); longest path inside "
          f"the program folder: {longest} characters")
    if longest > 150:
        print("  WARNING: a path this long can pass Windows' 260-character limit once "
              "the install folder is added in front of it.")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for index, path in enumerate(files, 1):
            arc = path.relative_to(source).as_posix()
            if path.is_symlink():
                info = zipfile.ZipInfo(arc)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                zf.writestr(info, os.readlink(path))
            else:
                zf.write(path, arc)
            if index % 200 == 0 or index == len(files):
                print(f"\r  {index:,}/{len(files):,}", end="", flush=True)
    print()
    print(f"  payload.zip: {out.stat().st_size / 1e6:.1f} MB "
          f"({out.stat().st_size / max(raw, 1) * 100:.0f}% of the folder)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

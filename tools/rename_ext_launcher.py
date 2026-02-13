#!/usr/bin/env python3
"""External Tools launcher for IDEA/IntelliJ.

This script allows you to run a batch rename from IDE's External Tools
by calling:
  python tools/rename_ext_launcher.py <dir> <pattern> <replacement> [--recursive] [--include-dirs] [--regex] [--dry-run]
"""

from __future__ import annotations

import sys
from daily_py.file_handler import FileHandler


def main(argv):
    if len(argv) < 4:
        print("Usage: rename_ext_launcher.py <dir> <pattern> <replacement> [--recursive] [--include-dirs] [--regex] [--dry-run]")
        return 2
    dir_path, pattern, replacement = argv[1], argv[2], argv[3]
    recursive = "--recursive" in argv
    include_dirs = "--include-dirs" in argv
    use_regex = "--regex" in argv
    dry_run = "--dry-run" in argv

    fh = FileHandler(base_path=dir_path)
    if recursive:
        res = fh.batch_rename_recursive(dir_path, pattern, replacement, use_regex=use_regex, include_dirs=include_dirs, dry_run=dry_run)
        print(res)
    else:
        count = fh.batch_rename(dir_path, pattern, replacement, use_regex=use_regex)
        print({"renamed": count})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

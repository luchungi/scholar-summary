"""
Rewrite math delimiters in already-saved reports into the $ / $$ form the frontend renders.

New reports are normalised as they are generated (agent._normalize_report_math); this
script brings older ones into line. It is safe to run repeatedly: a report already in
canonical form is not touched.

    .venv/bin/python scripts/normalize_report_math.py            # dry run, changes nothing
    .venv/bin/python scripts/normalize_report_math.py --apply    # back up, then rewrite

--apply first saves every file it is about to change into
reports/.math-backup-<timestamp>.tar.gz, and keeps each file's modification time.
"""

import argparse
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from math_delimiters import normalize_math_delimiters


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument("--verbose", action="store_true", help="list every file that changes")
    args = parser.parse_args()

    reports_dir = Path(config.REPORTS_DIR)
    if not reports_dir.is_absolute():
        reports_dir = ROOT / reports_dir
    files = sorted(reports_dir.glob("report_*.md"))

    pending = []          # (path, new_text, stats)
    unbalanced = []       # (path, count)
    totals = {"inline": 0, "display": 0, "promoted": 0}
    for path in files:
        text = path.read_text(encoding="utf-8")
        new_text, stats = normalize_math_delimiters(text)
        if stats.unbalanced:
            unbalanced.append((path, stats.unbalanced))
        if new_text != text:
            pending.append((path, new_text, stats))
            for key in totals:
                totals[key] += getattr(stats, key)

    print(f"Scanned {len(files)} reports in {reports_dir}")
    print(f"Reports to change: {len(pending)}")
    print(f"  \\(..\\) -> $..$              : {totals['inline']}")
    print(f"  \\[..\\] -> fenced $$         : {totals['display']}")
    print(f"  single-line $$ -> fenced $$ : {totals['promoted']}")
    if args.verbose:
        for path, _, stats in pending:
            print(f"  {path.name}: {stats.summary()}")
    for path, count in unbalanced:
        print(f"[-] {path.name}: {count} unpaired delimiter(s) left as written")

    if not args.apply:
        print("Dry run: nothing written. Re-run with --apply to rewrite the files.")
        return
    if not pending:
        print("Nothing to do.")
        return

    backup = reports_dir / f".math-backup-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    with tarfile.open(backup, "w:gz") as tar:
        for path, _, _ in pending:
            tar.add(path, arcname=path.name)
    print(f"Backed up {len(pending)} original files to {backup}")

    for path, new_text, _ in pending:
        stat = path.stat()
        path.write_text(new_text, encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    print(f"Rewrote {len(pending)} reports.")


if __name__ == "__main__":
    main()

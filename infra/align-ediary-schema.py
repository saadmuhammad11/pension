#!/usr/bin/env python3
"""Make the e-diary's database match the schema the legacy AG server actually runs.

    python3 infra/align-ediary-schema.py            # what would change, and nothing else
    python3 infra/align-ediary-schema.py --apply    # back up, then change it

The e-diary arrived without a database dump (see docs and the session notes), so its schema was
reconstructed from upstream HESK 3.5.3 DDL plus hand-written AG tables. That got the application
running and it is not the same schema: 3.5.3 carries tables and columns the AG's 3.2.4 install
never had, and the reconstruction had to guess at the AG's own tables -- the departmental feed,
the projects table, the ticket images.

``hesk_202609221644.sql`` is the real thing, exported from the legacy server (MariaDB 10.4.24)
on 22 September 2026. Schema only, no rows. This script makes ours match it, in the one
direction that is safe to automate: it never drops a table that holds rows, and it takes a full
backup before it touches anything.

What "match" means here, and where it bites
-------------------------------------------
The interesting differences are not cosmetic. In the real schema the departmental feed's
``officer_id``, ``retirement_id`` and ``district`` are **integers**, where the reconstruction
made them strings. That is a fact about the feed, not a detail: the department sends numeric
identifiers, and a demo seeded with ``RET-2026-0451`` is seeded with something the real system
cannot produce. Converting the column converts those values to 0, so the seed is rewritten
afterwards with numbers (``infra/seed-ediary-cases.py``).

The comparison is done in the database rather than by parsing SQL: the dump is loaded into a
throwaway ``hesk_ref`` schema and the two are diffed through ``information_schema``, so what is
compared is what MariaDB actually made of each definition.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DB_CONTAINER = os.environ.get("EDIARY_DB", "ediary-db-1")
LIVE = os.environ.get("EDIARY_DB_NAME", "hesk")
REF = "hesk_ref"
ROOT_PASS = os.environ.get("EDIARY_DB_ROOT_PASS", "rootpw")

#: The schema as the legacy server has it. Newest export in the project root wins.
DUMPS = sorted(ROOT.glob("hesk_*.sql"))

#: Tables in the export that are a backup somebody took on the live server, not part of the
#: schema. Created anyway -- they are in the schema we were given, and an empty copy costs
#: nothing -- but named here so the report can say what they are.
BACKUP_TABLES = re.compile(r"(_bk_\d+|_copy)$")


def mysql(sql: str, database: str | None = None, quiet: bool = False) -> str:
    cmd = ["docker", "exec", "-i", DB_CONTAINER, "mysql", "-uroot", f"-p{ROOT_PASS}",
           "-N", "-B", "-e", sql]
    if database:
        cmd.insert(-2, database)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 and not quiet:
        raise SystemExit(f"database refused:\n{proc.stderr.strip()}")
    return proc.stdout


def rows(sql: str) -> list[list[str]]:
    out = mysql(sql).strip()
    return [line.split("\t") for line in out.splitlines() if line]


def load_reference(dump: Path) -> None:
    """Load the legacy export into a throwaway schema, so it can be compared as MariaDB sees it.

    The export begins ``USE hesk;`` and drops every table it creates. Run as it stands it would
    empty the running help desk, so the database name is rewritten on the way in and the live
    schema is never named.
    """
    mysql(f"DROP DATABASE IF EXISTS {REF}; CREATE DATABASE {REF} CHARACTER SET utf8mb4;")
    sql = dump.read_text(encoding="utf-8", errors="replace")
    sql = re.sub(r"(?mi)^USE\s+`?hesk`?\s*;", f"USE {REF};", sql)
    if f"USE {REF}" not in sql:
        raise SystemExit(f"{dump.name} does not select a database; refusing to guess")
    proc = subprocess.run(
        ["docker", "exec", "-i", DB_CONTAINER, "mysql", "-uroot", f"-p{ROOT_PASS}"],
        input=sql, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"the export would not load:\n{proc.stderr.strip()[:2000]}")


# ---------------------------------------------------------------------------------------
# The difference
# ---------------------------------------------------------------------------------------

def missing_tables() -> list[str]:
    return [r[0] for r in rows(f"""
        SELECT table_name FROM information_schema.tables WHERE table_schema='{REF}'
          AND table_name NOT IN (SELECT table_name FROM information_schema.tables
                                 WHERE table_schema='{LIVE}') ORDER BY table_name;""")]


def extra_tables() -> list[tuple[str, int]]:
    out = []
    for (name,) in [tuple(r) for r in rows(f"""
            SELECT table_name FROM information_schema.tables WHERE table_schema='{LIVE}'
              AND table_name NOT IN (SELECT table_name FROM information_schema.tables
                                     WHERE table_schema='{REF}') ORDER BY table_name;""")]:
        count = int(mysql(f"SELECT COUNT(*) FROM `{name}`;", LIVE).strip() or 0)
        out.append((name, count))
    return out


def missing_columns() -> list[tuple[str, str, str]]:
    return [(r[0], r[1], r[2]) for r in rows(f"""
        SELECT r.table_name, r.column_name, r.ordinal_position FROM information_schema.columns r
         WHERE r.table_schema='{REF}'
           AND r.table_name IN (SELECT table_name FROM information_schema.tables
                                WHERE table_schema='{LIVE}')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns o
                           WHERE o.table_schema='{LIVE}' AND o.table_name=r.table_name
                             AND o.column_name=r.column_name)
         ORDER BY r.table_name, r.ordinal_position;""")]


def extra_columns() -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in rows(f"""
        SELECT o.table_name, o.column_name FROM information_schema.columns o
         WHERE o.table_schema='{LIVE}'
           AND o.table_name IN (SELECT table_name FROM information_schema.tables
                                WHERE table_schema='{REF}')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns r
                           WHERE r.table_schema='{REF}' AND r.table_name=o.table_name
                             AND r.column_name=o.column_name)
         ORDER BY o.table_name, o.ordinal_position;""")]


def wrong_types() -> list[tuple[str, str, str, str]]:
    return [(r[0], r[1], r[2], r[3]) for r in rows(f"""
        SELECT o.table_name, o.column_name, r.column_type, o.column_type
          FROM information_schema.columns o
          JOIN information_schema.columns r ON r.table_schema='{REF}'
               AND r.table_name=o.table_name AND r.column_name=o.column_name
         WHERE o.table_schema='{LIVE}' AND r.column_type <> o.column_type
         ORDER BY o.table_name, o.ordinal_position;""")]


def definition(table: str, column: str) -> str:
    """The column as the legacy server declares it: type, nullability, default, extra."""
    r = rows(f"""SELECT column_type, is_nullable, column_default, extra
                   FROM information_schema.columns
                  WHERE table_schema='{REF}' AND table_name='{table}'
                    AND column_name='{column}';""")[0]
    col_type, nullable, default, extra = r[0], r[1], r[2], r[3] if len(r) > 3 else ""
    piece = f"`{column}` {col_type}"
    piece += " NULL" if nullable == "YES" else " NOT NULL"
    if default not in (None, "NULL"):
        literal = default if re.match(r"^(current_timestamp|CURRENT_TIMESTAMP)", default) \
            else "'" + default.replace("'", "''") + "'"
        piece += f" DEFAULT {literal}"
    if extra and "auto_increment" not in extra:
        piece += f" {extra}"
    return piece


def after_clause(table: str, column: str) -> str:
    """Put a new column where the legacy server has it, so the two read alike."""
    r = rows(f"""SELECT ordinal_position FROM information_schema.columns
                  WHERE table_schema='{REF}' AND table_name='{table}' AND column_name='{column}';""")
    if not r:
        return ""
    before = rows(f"""SELECT column_name FROM information_schema.columns
                       WHERE table_schema='{REF}' AND table_name='{table}'
                         AND ordinal_position={int(r[0][0]) - 1};""")
    return f" AFTER `{before[0][0]}`" if before else " FIRST"


# ---------------------------------------------------------------------------------------

def plan() -> list[tuple[str, str]]:
    """Every change, as (what it is, the statement). Ordered so each step can run."""
    steps: list[tuple[str, str]] = []
    for table in missing_tables():
        ddl = subprocess.run(
            ["docker", "exec", "-i", DB_CONTAINER, "mysql", "-uroot", f"-p{ROOT_PASS}", REF,
             "-N", "-B", "-e", f"SHOW CREATE TABLE `{table}`;"],
            capture_output=True, text=True).stdout
        create = ddl.split("\t", 1)[1].replace("\\n", "\n") if "\t" in ddl else ""
        if create.strip():
            what = "backup table from the live server" if BACKUP_TABLES.search(table) else "table"
            steps.append((f"create {what} {table}", create.strip().rstrip(";") + ";"))

    for table, column, _pos in missing_columns():
        steps.append((f"add {table}.{column}",
                      f"ALTER TABLE `{table}` ADD COLUMN {definition(table, column)}"
                      f"{after_clause(table, column)};"))

    for table, column, legacy, ours in wrong_types():
        steps.append((f"{table}.{column}: {ours} -> {legacy}",
                      f"ALTER TABLE `{table}` MODIFY COLUMN {definition(table, column)};"))

    for table, column in extra_columns():
        steps.append((f"drop {table}.{column} (not in the legacy schema)",
                      f"ALTER TABLE `{table}` DROP COLUMN `{column}`;"))

    for table, count in extra_tables():
        if count:
            steps.append((f"KEPT {table}: holds {count} row(s), not dropped", ""))
        else:
            steps.append((f"drop empty {table} (not in the legacy schema)",
                          f"DROP TABLE `{table}`;"))
    return steps


def backup() -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "artifacts" / f"ediary-{LIVE}-before-align-{stamp}.sql"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["docker", "exec", DB_CONTAINER, "mysqldump", "-uroot", f"-p{ROOT_PASS}",
         "--databases", LIVE],
        capture_output=True, text=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(f"could not back the database up, so nothing was changed:\n"
                         f"{proc.stderr.strip()[:500]}")
    out.write_text(proc.stdout, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="make the changes (backs up first)")
    ap.add_argument("--dump", type=Path, default=DUMPS[-1] if DUMPS else None,
                    help="the legacy export to match (default: newest hesk_*.sql in the project)")
    args = ap.parse_args()

    if args.dump is None or not args.dump.exists():
        raise SystemExit("no legacy export found; expected hesk_<timestamp>.sql in the project")
    print(f"matching against {args.dump.name}")
    load_reference(args.dump)

    steps = plan()
    if not steps:
        print("  the schemas already agree")
        return 0

    changes = [s for s in steps if s[1]]
    kept = [s for s in steps if not s[1]]
    for what, _sql in steps:
        print(f"  {'·' if _sql else '!'} {what}")
    print(f"\n  {len(changes)} change(s)" + (f", {len(kept)} left alone" if kept else ""))

    if not args.apply:
        print("  nothing was changed. Re-run with --apply to make it so.")
        return 0

    saved = backup()
    print(f"\n  backed up to {saved.relative_to(ROOT)}")
    # Foreign keys off for the duration: the export disables them for the same reason, and the
    # order in which tables arrive is the export's, not a dependency graph's.
    failed = []
    for what, sql in changes:
        proc = subprocess.run(
            ["docker", "exec", "-i", DB_CONTAINER, "mysql", "-uroot", f"-p{ROOT_PASS}", LIVE,
             "-e", "SET FOREIGN_KEY_CHECKS=0; " + sql],
            capture_output=True, text=True)
        if proc.returncode != 0:
            failed.append((what, proc.stderr.strip().splitlines()[-1][:160]))
    print(f"  applied {len(changes) - len(failed)} of {len(changes)}")
    for what, why in failed:
        print(f"    ! {what}: {why}")

    remaining = [s for s in plan() if s[1]]
    print(f"\n  difference now: {len(remaining)} change(s) outstanding"
          + ("" if remaining else " — the schemas agree"))
    for what, _sql in remaining[:10]:
        print(f"    · {what}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

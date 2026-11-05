"""SENTINEL database kit: rebuild the whole Supabase database from the files in ./data.

  python ingest.py all          # check -> create -> load -> upload -> verify  (the usual command)

  python ingest.py check        # verify local files against data/manifest.json (no network)
  python ingest.py create       # create tables, view, policies and Storage bucket
  python ingest.py load         # load CSV shards into the tables   (--table labels to load one)
  python ingest.py upload       # upload training files to Supabase Storage
  python ingest.py verify       # row counts in Supabase must equal the manifest
  python ingest.py lockdown     # make the publishable key read-only (run after loading)
  python ingest.py reset --yes  # DELETE every table (and --storage: every bucket file)

Every step is safe to re-run: rows and files that already exist are skipped.
Settings come from .env next to this file (copy .env.example to .env).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import mimetypes
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SQL_DIR = ROOT / "sql"
PAGE_SIZE = 1000

csv.field_size_limit(50_000_000)  # documents contain long Markdown bodies


# ---------------------------------------------------------------- settings ---
def load_env() -> None:
    """Minimal .env reader (python-dotenv is used when installed)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        return
    except ImportError:
        pass
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def setting(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name) or default
    if required and not value:
        raise SystemExit(f"Missing setting {name}. Copy .env.example to .env and fill it in.")
    return value


def bucket() -> str:
    return setting("SUPABASE_BUCKET") or "sentinel-data"


# ------------------------------------------------------------ what to load ---
@dataclass(frozen=True)
class TableSpec:
    name: str
    key: str                          # primary key, used for pagination and de-duplication
    json_columns: tuple[str, ...] = ()
    batch_size: int = 500             # rows per REST request (keep requests well under the API timeout)


# Parents before children so every foreign key already exists when a row arrives.
TABLES = [
    TableSpec("customers", "customer_id"),
    TableSpec("merchants", "merchant_id", ("merchant_location",)),
    TableSpec("devices", "device_id"),
    TableSpec("transactions", "transaction_id", ("customer_location", "merchant_location")),
    TableSpec("payment_outcomes", "transaction_id"),
    TableSpec("labels", "transaction_id"),
    TableSpec("features", "transaction_id", ("reason_codes",)),
    TableSpec("legacy_cases", "legacy_case_id", ("evidence",)),
    TableSpec("documents", "document_id", ("metadata",), batch_size=100),
    TableSpec("gold_explanations", "example_id", ("target",), batch_size=200),
    TableSpec("preference_pairs", "pair_id", ("chosen", "rejected"), batch_size=200),
    TableSpec("threshold_sets", "threshold_id"),
    TableSpec("hard_rules", "rule_id", ("expression",)),
    TableSpec("list_entries", "entry_id"),
]
TABLES_BY_NAME = {t.name: t for t in TABLES}

# Small reference files uploaded to Storage next to the training files.
STORAGE_TOP_LEVEL = ["manifest.json", "quality_report.json", "data_dictionary.json",
                     "feature_catalogue.json", "rules_config.json", "DATA_CARD.md"]


def load_manifest() -> dict:
    path = DATA_DIR / "manifest.json"
    if not path.exists():
        raise SystemExit(f"{path} not found. This folder must contain data/manifest.json.")
    return json.loads(path.read_text(encoding="utf-8"))


def expected_rows(manifest: dict) -> dict[str, int]:
    totals: dict[str, int] = {}
    for shard in manifest["tables"]:
        totals[shard["table"]] = totals.get(shard["table"], 0) + shard["rows"]
    return totals


# ------------------------------------------------------------------ clients ---
_local = threading.local()


def get_client(write: bool = False):
    """Reads use the publishable key. Writes use the secret key when it is set (bypasses
    Row Level Security, so keep it out of notebooks). One client per thread."""
    from supabase import create_client
    cache = _local.__dict__.setdefault("clients", {})
    if write not in cache:
        key = (setting("SUPABASE_SECRET_KEY") if write else None) or setting("SUPABASE_KEY", required=True)
        cache[write] = create_client(setting("SUPABASE_URL", required=True), key)
    return cache[write]


def count_rows(table: str, **filters) -> int:
    query = get_client().table(table).select("*", count="exact", head=True)
    for column, value in filters.items():
        query = query.eq(column, value)
    return query.execute().count or 0


def run_sql_file(name: str) -> bool:
    """Run sql/<name> through DATABASE_URL. Returns False (and prints how to do it by hand)
    when DATABASE_URL is not set."""
    path = SQL_DIR / name
    if not setting("DATABASE_URL"):
        print(f"DATABASE_URL is not set, so run this SQL yourself:\n"
              f"  Supabase dashboard -> SQL Editor -> New query -> paste {path} -> Run")
        return False
    import psycopg
    with psycopg.connect(setting("DATABASE_URL"), autocommit=True) as conn:
        conn.execute(path.read_text(encoding="utf-8"))
    print(f"Executed {name} through DATABASE_URL.")
    return True


# ------------------------------------------------------------------- steps ---
def cmd_check(args=None) -> None:
    """Local integrity check: every file listed in the manifest exists (and matches its sha256)."""
    manifest = load_manifest()
    problems = []
    for shard in manifest["tables"]:
        if not (DATA_DIR / shard["path"]).exists():
            problems.append(f"missing {shard['path']}")
    for f in manifest["files"]:
        path = DATA_DIR / f["path"]
        if not path.exists():
            problems.append(f"missing {f['path']}")
        elif f.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != f["sha256"]:
            problems.append(f"corrupt {f['path']} (sha256 mismatch)")
    if problems:
        raise SystemExit("Local data is incomplete:\n  " + "\n  ".join(problems[:20]) +
                         "\nRe-download / re-unzip the kit.")
    totals = expected_rows(manifest)
    print(f"Dataset {manifest['dataset_id']}: {len(manifest['tables'])} table shards "
          f"({sum(totals.values()):,} rows), {len(manifest['files'])} Storage files. All present.")


def missing_tables() -> list[str]:
    missing = []
    for name, key in [(t.name, t.key) for t in TABLES] + [("model_features", "transaction_id")]:
        try:
            get_client().table(name).select(key).limit(1).execute()
        except Exception:
            missing.append(name)
    return missing


def cmd_create(args=None) -> None:
    ran = run_sql_file("01_create_tables.sql")
    missing = missing_tables()
    for _ in range(4 if ran else 0):   # the REST API needs a moment to see new tables
        if not missing:
            break
        time.sleep(2)
        missing = missing_tables()
    if missing:
        raise SystemExit("Tables are not visible through the Supabase API yet: " + ", ".join(missing) +
                         f"\nPaste {SQL_DIR / '01_create_tables.sql'} into the SQL Editor, click Run, "
                         "then run this command again.")
    print(f"All {len(TABLES)} tables and the model_features view are reachable.")


def read_rows(path: Path, spec: TableSpec):
    """CSV text -> JSON-ready dicts: empty -> NULL, 'true'/'false' -> bool, JSON columns parsed."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out = {}
            for col, value in row.items():
                if value == "":
                    out[col] = None
                elif col in spec.json_columns:
                    out[col] = json.loads(value)
                elif value in ("true", "false"):
                    out[col] = value == "true"
                else:
                    out[col] = value
            yield out


def batches(rows, size):
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def insert_batch(spec: TableSpec, batch: list[dict], attempts: int = 4) -> int:
    from postgrest.types import ReturnMethod
    for attempt in range(1, attempts + 1):
        try:
            get_client(write=True).table(spec.name).upsert(
                batch, on_conflict=spec.key, ignore_duplicates=True, returning=ReturnMethod.minimal).execute()
            return len(batch)
        except Exception as exc:  # network blip or timeout: back off and retry
            if attempt == attempts:
                raise RuntimeError(f"{spec.name}: batch starting {batch[0][spec.key]} failed: {exc}") from exc
            time.sleep(2 ** attempt)
    return 0


def load_table(spec: TableSpec, shards: list[dict], workers: int) -> int:
    total = sum(s["rows"] for s in shards)
    done, started = 0, time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for shard in shards:
            rows = read_rows(DATA_DIR / shard["path"], spec)
            for n in pool.map(lambda b: insert_batch(spec, b), batches(rows, spec.batch_size)):
                done += n
                print(f"\r  {spec.name:<18} {done:>9,} / {total:,} rows", end="", flush=True)
    print(f"  ({time.time() - started:.0f}s)")
    return done


def cmd_load(args) -> None:
    manifest = load_manifest()
    selected = [t for t in TABLES if not args.table or t.name in args.table]
    print(f"Loading dataset {manifest['dataset_id']} into Supabase ({len(selected)} tables)")
    for spec in selected:
        shards = [s for s in manifest["tables"] if s["table"] == spec.name]
        load_table(spec, shards, args.workers)


def content_type(path: str) -> str:
    if path.endswith(".gz"):
        return "application/gzip"
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def upload_one(path: str, attempts: int = 4) -> str:
    data = (DATA_DIR / path).read_bytes()
    for attempt in range(1, attempts + 1):
        try:
            get_client(write=True).storage.from_(bucket()).upload(
                path, data, {"content-type": content_type(path), "upsert": "false"})
            return "uploaded"
        except Exception as exc:
            if "exists" in str(exc).lower() or "duplicate" in str(exc).lower():
                return "skipped"
            if attempt == attempts:   # network blip: back off and retry before giving up
                raise RuntimeError(f"{path}: {exc}") from exc
            time.sleep(2 ** attempt)
    return "skipped"


def cmd_upload(args) -> None:
    paths = STORAGE_TOP_LEVEL + sorted(f["path"] for f in load_manifest()["files"])
    size_mb = sum((DATA_DIR / p).stat().st_size for p in paths) / 2**20
    print(f"Uploading {len(paths)} files ({size_mb:.1f} MiB) to bucket '{bucket()}'")
    counts = {"uploaded": 0, "skipped": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, result in enumerate(pool.map(upload_one, paths), 1):
            counts[result] += 1
            print(f"\r  {i:>5} / {len(paths)}  uploaded={counts['uploaded']} already-there={counts['skipped']}",
                  end="", flush=True)
    print()


def storage_files(prefix: str) -> list[str]:
    """Every object path under a prefix (Storage lists one folder level at a time)."""
    storage, found = get_client(write=True).storage.from_(bucket()), []
    for item in storage.list(prefix, {"limit": 1000}):
        path = f"{prefix}/{item['name']}" if prefix else item["name"]
        found += [path] if item.get("id") else storage_files(path)
    return found


def cmd_verify(args=None) -> None:
    manifest = load_manifest()
    expected = expected_rows(manifest)
    ok = True
    print(f"{'table':<20}{'expected':>12}{'in supabase':>14}")
    for spec in TABLES:
        actual = count_rows(spec.name)
        flag = "OK" if actual == expected.get(spec.name, 0) else "MISMATCH"
        ok &= flag == "OK"
        print(f"{spec.name:<20}{expected.get(spec.name, 0):>12,}{actual:>14,}  {flag}")

    print("\nSplit balance (labels):")
    for split in ("warmup", "train", "validation", "holdout"):
        rows, fraud = count_rows("labels", split=split), count_rows("labels", split=split, fraud_label=1)
        print(f"  {split:<11} rows={rows:>8,}  fraud={fraud:>6,}  rate={fraud / max(rows, 1):.3%}")

    print(f"\nStorage bucket '{bucket()}':")
    for prefix in ("training", "evaluation", "parquet", "corpus"):
        want = sum(1 for f in manifest["files"] if f["path"].startswith(prefix + "/"))
        have = len(storage_files(prefix))
        ok &= have >= want
        print(f"  {prefix + '/':<12} {have:>5} / {want} files  {'OK' if have >= want else 'MISSING'}")

    if not ok:
        raise SystemExit("\nSomething is missing. Re-run: python ingest.py load   (and/or)   python ingest.py upload")
    print("\nDatabase matches the manifest. Run sql/03_checks.sql in the SQL Editor for data-quality checks.")


def cmd_lockdown(args=None) -> None:
    if run_sql_file("02_lockdown.sql"):
        print("The publishable key is now read-only.")


def cmd_reset(args) -> None:
    if not args.yes:
        raise SystemExit("This deletes every SENTINEL table. Re-run with --yes if you are sure.")
    if run_sql_file("99_reset_DANGER.sql"):
        print("All SENTINEL tables dropped.")
    if args.storage:
        if not setting("SUPABASE_SECRET_KEY"):
            raise SystemExit("Emptying Storage needs SUPABASE_SECRET_KEY in .env.")
        paths = storage_files("")
        storage = get_client(write=True).storage.from_(bucket())
        for i in range(0, len(paths), 100):
            storage.remove(paths[i:i + 100])
        print(f"Removed {len(paths)} files from bucket '{bucket()}'.")


def cmd_all(args) -> None:
    print("== 1/5 check local files");  cmd_check()
    print("\n== 2/5 create tables");    cmd_create()
    print("\n== 3/5 load tables");      cmd_load(args)
    print("\n== 4/5 upload files");     cmd_upload(argparse.Namespace(workers=6))
    print("\n== 5/5 verify");           cmd_verify()
    print("\nDone. Optional: python ingest.py lockdown   (makes the publishable key read-only)")


def main(argv=None) -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify local files (no network)").set_defaults(func=cmd_check)
    sub.add_parser("create", help="create tables, view, policies, bucket").set_defaults(func=cmd_create)
    for name, func, help_text in [("load", cmd_load, "load table rows"), ("all", cmd_all, "run every step")]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--table", choices=list(TABLES_BY_NAME), action="append",
                       help="Load only this table (repeatable). Default: all, in foreign-key order.")
        p.add_argument("--workers", type=int, default=4, help="Parallel REST requests")
        p.set_defaults(func=func)
    p = sub.add_parser("upload", help="upload training files to Storage")
    p.add_argument("--workers", type=int, default=6)
    p.set_defaults(func=cmd_upload)
    sub.add_parser("verify", help="compare Supabase with the manifest").set_defaults(func=cmd_verify)
    sub.add_parser("lockdown", help="make the publishable key read-only").set_defaults(func=cmd_lockdown)
    p = sub.add_parser("reset", help="drop every table (DESTRUCTIVE)")
    p.add_argument("--yes", action="store_true", help="confirm you really want to delete everything")
    p.add_argument("--storage", action="store_true", help="also delete every file in the bucket")
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ModuleNotFoundError as exc:
        sys.exit(f"{exc}. Install the requirements first:  pip install -r requirements.txt")


if __name__ == "__main__":
    main()

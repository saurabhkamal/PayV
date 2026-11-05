# PayV Database Kit

Everything you need to build the PayV fraud-detection database in **your own** Supabase project:
the data, the SQL schema and one Python script that loads it. You can rebuild the whole database
from this folder at any time, and every step is safe to re-run.

```
supabase_db_kit/
├── README.md            <- you are here
├── ingest.py            <- the only script you run
├── requirements.txt     <- Python packages
├── .env.example         <- copy to .env and add your Supabase keys
├── sql/
│   ├── 01_create_tables.sql   tables, model_features view, security policies, Storage bucket
│   ├── 02_lockdown.sql        make the data read-only after loading (optional)
│   ├── 03_checks.sql          data-quality checks to run in the SQL Editor
│   └── 99_reset_DANGER.sql    delete every table to start over
└── data/
    ├── manifest.json          list of every file + expected row counts (the source of truth)
    ├── tables/                14 tables as gzipped CSV shards  -> Postgres tables
    ├── training/ evaluation/ corpus/ parquet/                 -> Storage bucket "sentinel-data"
    └── DATA_CARD.md, data_dictionary.json, ...                 documentation of every column
```

## What ends up in Supabase

| Table | Rows | What it is |
|---|---:|---|
| customers | 2,500 | synthetic customers |
| merchants | 200 | synthetic merchants |
| devices | 10,120 | devices used for payments |
| transactions | 110,000 | payments (warmup / train / validation / holdout splits) |
| payment_outcomes | 110,000 | success / failure of each payment |
| labels | 110,000 | `fraud_label` (0/1), kept apart from transactions on purpose |
| features | 110,000 | engineered features FE-01 .. FE-10 |
| legacy_cases | 200 | closed investigation cases |
| documents | 5,256 | investigator notes, playbooks, guidelines, ... |
| gold_explanations | 8,500 | LLM fine-tuning targets |
| preference_pairs | 5,000 | DPO chosen / rejected pairs |
| threshold_sets, hard_rules, list_entries | 1 / 2 / 24 | rules-engine configuration |

Plus a view **`model_features`** (transactions + features + label in one flat table) and
43 training files in the private Storage bucket **`sentinel-data`**. All data is synthetic.

---

## Step-by-step

### 1. Create a Supabase project (once)
1. Sign in at <https://supabase.com> and click **New project** (the free tier is enough, ~60 MB used).
2. Wait until the project is ready.
3. Go to **Project Settings -> API Keys** and copy:
   - the **Project URL** (`https://xxxx.supabase.co`)
   - the **publishable key** (`sb_publishable_...`, also called *anon*)
   - optionally the **secret key** (`sb_secret_...`, also called *service_role*). Keep it private.

### 2. Install Python packages (once)
Python 3.10 or newer. From inside this folder:

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Add your keys
Copy `.env.example` to `.env` and fill in `SUPABASE_URL` and `SUPABASE_KEY` (and `SUPABASE_SECRET_KEY` if you have it).

```bash
cp .env.example .env        # Windows: copy .env.example .env
python ingest.py check      # confirms the data files are complete (no network needed)
```

### 4. Create the tables
Pick **one** option:

- **A. SQL Editor (simplest).** In the Supabase dashboard open **SQL Editor -> New query**, paste the
  whole content of `sql/01_create_tables.sql`, click **Run**. You should see "Success. No rows returned".
- **B. Let the script do it.** Put your connection string in `.env` as `DATABASE_URL`
  (dashboard -> **Connect** -> *Session pooler*, port 5432, with your database password).

### 5. Build the database
```bash
python ingest.py all
```
This runs: check files -> create/confirm tables -> load all 14 tables -> upload Storage files -> verify.
It takes about 5-15 minutes depending on your internet. The final report must say every table is `OK`:

```
table                   expected   in supabase
customers                  2,500         2,500  OK
...
Database matches the manifest.
```

If it stops halfway (Wi-Fi drop, laptop sleep), **just run the same command again** — rows and files
that are already there are skipped.

### 6. Check data quality (optional, recommended)
Paste `sql/03_checks.sql` into the SQL Editor and run it. Every `violations` value must be `0`.

### 7. Make it read-only (optional)
`01_create_tables.sql` lets the publishable key **insert** rows so you can load without the secret key.
After loading, remove that permission:
```bash
python ingest.py lockdown      # needs DATABASE_URL, or paste sql/02_lockdown.sql into the SQL Editor
```

---

## Rebuild from scratch at any time
```bash
python ingest.py reset --yes --storage   # drops all tables + empties the bucket
python ingest.py all                     # builds everything again
```
`reset` needs `DATABASE_URL` (or paste `sql/99_reset_DANGER.sql` into the SQL Editor yourself);
`--storage` needs `SUPABASE_SECRET_KEY`. After a lockdown, loading again needs `SUPABASE_SECRET_KEY`
(or re-run `sql/01_create_tables.sql`, which restores the insert permission).

## All commands
| Command | What it does |
|---|---|
| `python ingest.py check` | check local files against the manifest (sha256), no network |
| `python ingest.py create` | create tables (via `DATABASE_URL`) or confirm you created them in the SQL Editor |
| `python ingest.py load` | load all tables; `--table labels` loads one, `--workers 8` goes faster |
| `python ingest.py upload` | upload training files to the `sentinel-data` bucket |
| `python ingest.py verify` | compare row/file counts in Supabase with `data/manifest.json` |
| `python ingest.py all` | check + create + load + upload + verify |
| `python ingest.py lockdown` | make the publishable key read-only |
| `python ingest.py reset --yes [--storage]` | delete every table (and bucket file) |

## Using the data afterwards
```python
from supabase import create_client
sb = create_client(SUPABASE_URL, SUPABASE_KEY)
rows = sb.table("model_features").select("*").eq("split", "train").limit(1000).execute().data
```
The API returns at most 1,000 rows per request: page with `.gt("transaction_id", last_id).order("transaction_id")`.
Column meanings are in `data/data_dictionary.json` and `data/DATA_CARD.md`.

## Troubleshooting
| Message | Fix |
|---|---|
| `Missing setting SUPABASE_URL` | `.env` is missing or not in this folder. |
| `Tables are not visible through the Supabase API yet` | Run `sql/01_create_tables.sql` in the SQL Editor (step 4), then retry. |
| `new row violates row-level security policy` | You ran lockdown. Add `SUPABASE_SECRET_KEY` to `.env`, or re-run `sql/01_create_tables.sql`. |
| `Bucket not found` | `01_create_tables.sql` was not run completely; run it again. |
| `MISMATCH` in verify | Run `python ingest.py load` again; it only adds the missing rows. |
| `No module named 'supabase'` | Activate the virtual environment and `pip install -r requirements.txt`. |
| timeouts / `ConnectionError` | Retry; or lower parallelism: `python ingest.py load --workers 2`. |

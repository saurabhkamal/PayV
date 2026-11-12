"""Step 1: Load the raw tables from supabase into pandas and save a local copy."""

import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

CACHE = Path(__file__).parent / "cache"      # the folder pipeline/cache/
CACHE.mkdir(exist_ok=True)                   # create it if it doesn't exist yet

# table name --> the id column we page by
# Sort by that column and read 1000 rows at a time, continuing from the last value we got.
TABLES = {
    "customers": "customer_id",
    "merchants": "merchant_id",
    "devices": "device_id",
    "transactions": "transaction_id",
    "payment_outcomes": "transaction_id",
    "labels": "transaction_id",
    "features": "transaction_id",            # the client's table, used in Step 5
}

def fetch_all(table, id_column):
    """Read a whole table from supabase, 1000 rows per request"""
    rows, last_id = [], ""                         # rows collects every row; last_id starts empty, so the first page begins at the very start
    while True:                                    # keep asking for pages until we break out below
        page = (sb.table(table).select("*")        # from this table, take all columns
                .gt(id_column, last_id)            # only rows whose id comes after the last one we already have
                .order(id_column)                  # sorted by id, so every page continues where the last one ended         
                .limit(1000)                       # at most 1,000 rows (the Supabase limit per request)
                .execute().data)                   # send the request and keep just the rows (a list of dictionaries)
        if not page:                               # an empty page means there are no rows left
            break                                  # so stop the loop
        rows += page                               # add this page's rows to the full list
        last_id = page[-1][id_column]              # remember the id of the last row, so the next page starts after it
    return pd.DataFrame(rows)                      # turn the list of dictionaries into a pandas table: one row per dictionary, one column per key


for table, id_column in TABLES.items():
    df = fetch_all(table, id_column)               # download the whole table from Supabase as a pandas table (df = DataFrame)
    df.to_parquet(CACHE / f"{table}.parquet", index=False)   # save it as a parquet file
    print(f"{table:17} {len(df):>8,} rows  {df.shape[1]:>3} columns")  # print the table name, its row count and its column count, lined up

print(f"\nSaved to {CACHE}")
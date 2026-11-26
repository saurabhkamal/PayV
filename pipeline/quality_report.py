"""Step 2: data quality report on the raw tables."""
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).parent / "cache"    # the folder with the files saved in Step 1

# each raw table, and its id column
ID_COLUMN = {
    "customers": "customer_id",
    "merchants": "merchant_id",
    "devices": "device_id",
    "transactions": "transaction_id",
    "payment_outcomes": "transaction_id",
    "labels": "transaction_id",
}
tables = {name: pd.read_parquet(CACHE / f"{name}.parquet") for name in ID_COLUMN}       # load all 6 tables into a dictionary: name -> DataFrame

# the columns that hold dates, per table
TIME_COLUMNS = {
    "customers": "created_at",
    "transactions": "transaction_time",
    "payment_outcomes": "outcome_time",
    "labels": "label_available_at",
}

# ---------- 1. Nulls ----------
print("1. Nulls per column")
for name, df in tables.items():       # go through each table
    nulls = df.isna().sum()           # count the missing values in every column
    print(f" {name}: {nulls[nulls > 0].to_dict() or 'no nulls'}")   # print only columns with missing values, or "no nulls" if there are none

# ---------- 2. Duplicates ----------
print("\n2. Duplicates")
for name, df in tables.items():
    repeated_ids = df[ID_COLUMN[name]].duplicated().sum()      # ids that already appeared in an earlier row
    repeated_rows = df.astype(str).duplicated().sum()          # rows identical to an earlier row in every column (compared as text, because dictionaries can't be compared directly)
    print(f" {name}: {repeated_ids} repeated ids, {repeated_rows} repeated rows")

# ---------- 3. Wrong types ----------
print("\n3. Wrong types")
for name, column in TIME_COLUMNS.items():                        # go through each date column
    dates = pd.to_datetime(tables[name][column], utc=True, errors="coerce", format="ISO8601")   # read the text as dates; anything unreadable becomes missing (NaT)
    print(f" {name}.{column}: stored as {tables[name][column].dtype}, {dates.isna().sum()} values are not valid dates")
    tables[name][column] = dates                    # replace the text with the real dates for the checks below

tx = tables["transactions"]    
labels = tables["labels"].set_index("transaction_id")       # labels with transaction_id as the row name, so we can look rows up by id
print(f" amount_paise != transaction_amount x 100: {(tx['amount_paise'] != (tx['transaction_amount'] * 100).round()).sum()} rows")   # the two amount columns should agree (1 rupee = 100 paise)
print(f" fraud_label values: {sorted(labels['fraud_label'].unique().tolist())}")     # should be only 0 and 1


# ---------- 4. Outliers in amount ----------
print("\n4. Outliers in amount (rupees)")
amount = tx["transaction_amount"]                                 # the payment amount in rupees
print(amount.describe().round(2).to_string())                     # count, mean, min, quartiles and max in one table

def outliers(values):
    """True for every value outside the IQR fences."""
    q1, q3 = values.quantile([0.25, 0.75])                        # the values 25% and 75% of the way up
    fence = 1.5 * (q3 - q1)                                       # the standard distance allowed beyond them
    return (values < q1 - fence) | (values > q3 + fence)          # True if too small or too large

plain = outliers(amount)                                          # IQR rule on the amounts as they are
log = outliers(np.log10(amount))                                  # the same rule on log scale (counts digits: 100 -> 2, 1,000 -> 3)
print(f" plain IQR rule: {plain.sum():,} outliers")
print(f" log IQR rule:   {log.sum():,} outliers")

fraud = tx["transaction_id"].map(labels["fraud_label"])     # look up each payment's fraud label by its id
print(f" fraud rate: all payments {fraud.mean():.1%}, log outliers {fraud[log].mean():.1%}")   # is fraud more common among the outliers?

# ---------- 5. Rows per split ----------
print("\n5. Rows per split")
tx["india_time"] = tx["transaction_time"].dt.tz_convert("Asia/Kolkata")     # UTC -> Indian time, because the splits follow Indian dates
print(tx.groupby("split")["india_time"].agg(["count", "min", "max"]).sort_values("min").to_string())
label_split = tx["transaction_id"].map(labels["split"])      # look up each payment's split in the labels table
print(f" split differs between transaction and labels: {(tx['split'] != label_split).sum()} rows")

"""Step 4: add the extra features the reason codes need, then assign R01 to R08."""
from pathlib import Path

import pandas as pd

CACHE = Path(__file__).parent / "cache"

tx = pd.read_parquet(CACHE / "transactions.parquet")
ours = pd.read_parquet(CACHE / "our_features.parquet")              # the features from Step 3
outcomes = pd.read_parquet(CACHE / "payment_outcomes.parquet")
customers = pd.read_parquet(CACHE / "customers.parquet")

tx["time"] = pd.to_datetime(tx["transaction_time"], utc=True, format="ISO8601")
tx = tx.merge(ours, on="transaction_id")                            # add our Step 3 features to each payment
tx = tx.sort_values(["customer_id", "time"]).reset_index(drop=True) # each customer's payments together, oldest first

# ---------- extra feature 1: is_new_city ----------
tx["city"] = tx["customer_location"].str.get("city")                 # the customer's city for this payment; empty if no location
gap = tx.groupby(["customer_id", "city"])["time"].diff()   
tx["is_new_city"] = ((gap.isna() | (gap > pd.Timedelta(days=90)))   # new = never seen, or not in the last 90 days (same idea as is_new_device)
                     .astype("boolean")
                     .mask(tx["city"].isna()))                       # unknown location -> empty


# ---------- extra feature 2: failed attempts in the previous 24 hours ----------
outcomes["outcome_time"] = pd.to_datetime(outcomes["outcome_time"], utc=True, format="ISO8601")
failed = (outcomes[outcomes["status"] == "FAILED"]                                  # only the failures
            .merge(tx[["transaction_id", "customer_id"]], on="transaction_id"))      # find whose payment each failure belongs to


timeline = pd.concat([                                                               # one timeline per customer with two kinds of rows:
    pd.DataFrame({"customer_id": tx["customer_id"], "time": tx["time"],              #   payments (failed = 0)
                  "failed": 0, "transaction_id": tx["transaction_id"]}),
    pd.DataFrame({"customer_id": failed["customer_id"], "time": failed["outcome_time"],   #   failure outcomes, at the time they ARRIVED (failed = 1)
                  "failed": 1, "transaction_id": None}),
]).sort_values(["customer_id", "time"]).reset_index(drop=True)

timeline["failed_last_24h"] = (timeline.groupby("customer_id")
                                       .rolling("24h", on="time", closed="left")["failed"]
                                       .sum().to_numpy())                            # failures that arrived in the 24 h before each row
fails = timeline.dropna(subset=["transaction_id"]).set_index("transaction_id")["failed_last_24h"]   # keep only the payment rows
tx["failed_last_24h"] = tx["transaction_id"].map(fails).fillna(0).astype(int)       # copy the count back to each payment
tx["has_recent_failures"] = tx["failed_last_24h"] >= 3

# ---------- extra feature 3: account age ----------
created = pd.to_datetime(customers.set_index("customer_id")["created_at"], utc=True, format="ISO8601")   # when each account was opened
tx["account_age_days"] = (tx["time"] - tx["customer_id"].map(created)).dt.days     # complete days from opening to this payment
tx["is_new_account"] = tx["account_age_days"] < 30

# ---------- the 8 reason codes ----------
HIGH_RISK_MCC = ["gaming", "gift_cards", "electronics"]
rules = pd.DataFrame({
    "R01_NEW_DEVICE":      tx["is_new_device"].fillna(False),                    # empty (no device) -> no code
    "R02_GEO_MISMATCH":    (tx["customer_merchant_distance_km"] > 500) | tx["is_new_city"].fillna(False),
    "R03_ODD_HOUR":        tx["is_night"],
    "R04_FAILED_ATTEMPTS": tx["has_recent_failures"],
    "R05_AMOUNT_SPIKE":    tx["amount_to_avg_ratio"] >= 5,                        # empty ratio -> comparison is False -> no code
    "R06_NEW_ACCOUNT":     tx["is_new_account"],
    "R07_VELOCITY":        tx["txn_count_last_1h"] >= 4,
    "R08_HIGH_RISK_MCC":   tx["merchant_category"].isin(HIGH_RISK_MCC),
}).astype(bool)                                                                   # one True/False column per code

codes = rules.columns.to_numpy()                                                  # the 8 code names, in order R01 to R08
tx["reason_codes"] = [list(codes[row]) for row in rules.to_numpy()]              # for each payment: the names of the codes that are True

# ---------- save ----------
COLUMNS = ["transaction_id", "is_new_city", "failed_last_24h", "has_recent_failures",
           "account_age_days", "is_new_account", "reason_codes"]
tx[COLUMNS].to_parquet(CACHE / "our_reason_codes.parquet", index=False)          # Step 5 reads this file

print("Payments per reason code:")
print(rules.sum().to_string())
print("\nFirst payments of one customer:")
print(tx.loc[tx["customer_id"] == "C_b90ff711ce3e3dba", ["transaction_id", "reason_codes"]].head(5).to_string())
"""Step 5: compare our features and reason codes with the client's features table."""
from pathlib import Path

import pandas as pd

CACHE = Path(__file__).parent / "cache"

client = pd.read_parquet(CACHE / "features.parquet")                       # the client's table
ours = (pd.read_parquet(CACHE / "our_features.parquet")                     # our Step 3 features...
          .merge(pd.read_parquet(CACHE / "our_reason_codes.parquet"), on="transaction_id"))   # ...plus our Step 4 features and codes
both = client.merge(ours, on="transaction_id", suffixes=("_client", "_ours"))   # one row per payment, with both versions side by side
print(f"Payments compared: {len(both):,}\n")

# feature -> number of decimals the client rounds to (None = not a decimal number)
FEATURES = {
    "amount_to_avg_ratio": 4,
    "is_new_device": None,
    "customer_merchant_distance_km": 2,
    "is_new_city": None,
    "hour_of_day": None,
    "is_night": None,
    "has_recent_failures": None,
    "is_new_account": None,
    "txn_count_last_1h": None,
    "txn_amount_last_24h_paise": None,
}

def matches(our_values, client_values):
    """True for every payment where the two values are the same, or both are empty."""
    same = our_values.astype(object) == client_values.astype(object)   # compare as plain Python values (our "boolean" type vs their True/False/None)
    both_empty = our_values.isna() & client_values.isna()               # both unknown = they agree
    return same | both_empty

# ---------- 1. match rate per feature ----------
print("1. Match rate per feature")
print(f" {'feature':31} {'exact':>8} {'rounded':>8} {'mismatches':>11}")
for feature, decimals in FEATURES.items():
    our_values = both[f"{feature}_ours"]                                  # e.g. amount_to_avg_ratio_ours
    client_values = both[f"{feature}_client"]                             # e.g. amount_to_avg_ratio_client
    exact = matches(our_values, client_values)                            # same without any rounding
    rounded = matches(our_values.round(decimals), client_values) if decimals else exact   # same after rounding ours like the client
    print(f" {feature:31} {exact.mean():>8.2%} {rounded.mean():>8.2%} {(~rounded).sum():>11,}")


# ---------- 2. match rate per reason code ----------
print("\n2. Match rate per reason code")
CODES = ["R01_NEW_DEVICE", "R02_GEO_MISMATCH", "R03_ODD_HOUR", "R04_FAILED_ATTEMPTS",
         "R05_AMOUNT_SPIKE", "R06_NEW_ACCOUNT", "R07_VELOCITY", "R08_HIGH_RISK_MCC"]
for code in CODES:
    ours_has = both["reason_codes_ours"].map(lambda codes: code in codes)       # does our list contain this code?
    client_has = both["reason_codes_client"].map(lambda codes: code in codes)   # does theirs?
    print(f" {code:22} {(ours_has == client_has).mean():>8.2%}   ours {ours_has.sum():>6,}   client {client_has.sum():>6,}")
same_list = both["reason_codes_ours"].map(tuple) == both["reason_codes_client"].map(tuple)   # whole list identical, same order
print(f" whole list identical   {same_list.mean():>8.2%}   ({(~same_list).sum():,} payments differ)")

# q ---------- 3. explain the exact-match gaps ----------
print("\n3. Why 'exact' is lower for two features: the client rounds")
example = both[["transaction_id", "amount_to_avg_ratio_ours", "amount_to_avg_ratio_client",
                "customer_merchant_distance_km_ours", "customer_merchant_distance_km_client"]]
print(example.iloc[1:4].to_string(index=False))                           # three payments side by side


# ---------- 4. can the check catch a mistake? ----------
print("\n4. Can the check catch a mistake? is_night computed in UTC instead of Indian time")
utc_night = pd.to_datetime(both["feature_as_of"], utc=True, format="ISO8601").dt.hour < 5   # the WRONG way: UTC hour
print(f" match rate: {(utc_night == both['is_night_client']).mean():.2%}")

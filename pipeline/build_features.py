"""Step 3: rebuild the features from the raw transactions, using only earlier data."""
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).parent / "cache"                    # the folder with the files saved in Step 1

tx = pd.read_parquet(CACHE / "transactions.parquet")       # all 110,000 payments
tx["time"] = pd.to_datetime(tx["transaction_time"], utc=True, format="ISO8601")   # text -> real date (found in Step 2)
tx = tx.sort_values(["customer_id", "time"]).reset_index(drop=True)              # each customer's payments together, oldest first


def window(column, size, how):
    """For every payment: mean / count / sum of `column` over the same customer's payments in the `size` before it."""
    rolled = (tx.groupby("customer_id")                        # look at one customer at a time
                .rolling(size, on="time", closed="left")[column]   # window of `size` ending just BEFORE this payment (current one excluded)
                .agg(how))                                     # "mean", "count" or "sum" of the payments inside
    return rolled.to_numpy()   


# ---------- 1. amount_to_avg_ratio ----------
tx["avg_90d"] = window("transaction_amount", "90D", "mean")              # average of the customer's payments in the previous 90 days
tx["amount_to_avg_ratio"] = tx["transaction_amount"] / tx["avg_90d"]     # this amount ÷ that average; empty if there was no earlier payment


# ---------- 2. is_new_device ----------
gap = tx.groupby(["customer_id", "device_id"])["time"].diff()           # time since this customer last used this same device
tx["is_new_device"] = ((gap.isna() | (gap > pd.Timedelta(days=90)))     # new = never used before, or not in the last 90 days
                       .astype("boolean")                               # True/False column that can also hold "empty"
                       .mask(tx["device_id"].isna()))                    # no device recorded -> empty, not True


# ---------- 3. customer_merchant_distance_km ----------
def haversine_km(lat1, lon1, lat2, lon2):
    """Straight-line distance on the Earth's surface, in km."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])  # degrees -> radians (what sin/cos expect)
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))                              # 6371 km = Earth's radius


customer_lat = tx["customer_location"].str.get("lat")     # take "lat" out of {'lat':…, 'lon':…, 'city':…}; empty if no location
customer_lon = tx["customer_location"].str.get("lon")
merchant_lat = tx["merchant_location"].str.get("lat")
merchant_lon = tx["merchant_location"].str.get("lon")
tx["customer_merchant_distance_km"] = haversine_km(customer_lat, customer_lon, merchant_lat, merchant_lon)   # empty location -> empty distance

# ---------- 4. hour_of_day and is_night ----------
tx["hour_of_day"] = tx["time"].dt.tz_convert("Asia/Kolkata").dt.hour    # the hour in Indian time (0-23)
tx["is_night"] = tx["hour_of_day"] < 5                                   # 00:00 up to 04:59 = night

# ---------- 5. txn_count_last_1h and txn_amount_last_24h_paise ----------
tx["txn_count_last_1h"] = window("transaction_amount", "1h", "count")    # how many payments in the previous hour
tx["txn_amount_last_24h_paise"] = window("amount_paise", "24h", "sum")   # total paise in the previous 24 hours
velocity = ["txn_count_last_1h", "txn_amount_last_24h_paise"]
tx[velocity] = tx[velocity].fillna(0).astype(int)                        # empty window = nothing happened = 0 (here 0 is correct, not a guess)

# ---------- save ----------
FEATURES = ["amount_to_avg_ratio", "is_new_device", "customer_merchant_distance_km",
            "hour_of_day", "is_night", "txn_count_last_1h", "txn_amount_last_24h_paise"]
ours = tx[["transaction_id", *FEATURES]]                                  # just the id and our features
ours.to_parquet(CACHE / "our_features.parquet", index=False)             # Steps 4 and 5 read this file

print(ours.shape)
print("\nEmpty values per feature:")
print(ours.isna().sum().to_string())
print("\nFirst payments of one customer:")
print(ours[tx["customer_id"] == "C_b90ff711ce3e3dba"].head(5).to_string())


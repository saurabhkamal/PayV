"""Step 3: copy the sample of project data from Supabase into MongoDB Atlas."""
import os
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient
from supabase import create_client

load_dotenv()
N_CUSTOMERS = 150  # all transactions of these customers (~6,800)

# Clients for Supabase (source) and MongoDB (target); they connect on first use
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
db = MongoClient(os.environ["MONGODB_URI"])["payv"]    # database payv

def to_date(text):
    """Supabase returns dates as text; MongoDB needs real dates."""
    return datetime.fromisoformat(text) if text else None

# Prepare the connections, read 150 customers and their transactions from Supabase,
# and convert the dates, then insert them into payv database in MongoDB.

# 1. Pick the customers
customers = (sb.table("customers").select("*")
               .order("customer_id").limit(N_CUSTOMERS).execute().data)
ids = [c["customer_id"] for c in customers]
cust_by_id = {c["customer_id"]: c for c in customers}
print(f"{len(customers)} customers")


# 2. Fetch their transactions, with merchant, device and label joined in
rows, last_id = [], ""
while True:
    page = (sb.table("transactions")                 # from the transactions table
              .select("*, merchants(*), devices(*), labels(fraud_label)")
              .in_("customer_id", ids)               # only our 150 customers
              .gt("transaction_id", last_id)         # only IDs AFTER the last one received
              .order("transaction_id")               # sorted by ID
              .limit(1000)                           # at most 1,000 rows
              .execute().data)                       # send the request; keep the rows
    if not page:
        break
    rows += page
    last_id = page[-1]["transaction_id"]
    print(f"fetched {len(rows)} transactions")


# 3. Reshape the rows into transaction documents
transactions = []
for r in rows:
    c, m, d = cust_by_id[r["customer_id"]], r["merchants"], r["devices"]
    transactions.append({
        "_id": r["transaction_id"],
        "customer_id": r["customer_id"],                       # the reference
        "transaction_time": to_date(r["transaction_time"]),
        "amount_paise": r["amount_paise"],
        "transaction_amount": float(r["transaction_amount"]),
        "payment_channel": r["payment_channel"],
        "split": r["split"],
        "customer": {                                          # copied fields
            "customer_age": r["customer_age"],
            "home_city": c["home_city"],
            "region": c["region"],
            "location": r["customer_location"],                # can be null
        },
        "merchant": {
            "merchant_id": m["merchant_id"],
            "name": m["synthetic_name"],
            "category": m["merchant_category"],
            "location": m["merchant_location"],
        },
        "device": {"device_id": d["device_id"], "device_kind": d["device_kind"]} if d else None,
        "account_age": r["account_age"],
        "previous_transactions": r["previous_transactions"],
        "average_transaction_value": r["average_transaction_value"],
        "failed_transactions": r["failed_transactions"],
        "fraud_label": r["labels"]["fraud_label"],             # from the separate labels table
        "is_synthetic": r["is_synthetic"],
    })


# 4. Build each customer's embedded device list
# As noted in step 2, the source has no customer-to-device table, 
# so deriving it from the transactions.

devices = defaultdict(dict)        # customer_id -> {device_id: info}
for t in transactions:
    d, when = t["device"], t["transaction_time"]
    if d is None:
        continue
    info = devices[t["customer_id"]].setdefault(
        d["device_id"], {**d, "first_seen": when, "last_seen": when, "txn_count": 0})
    info["first_seen"] = min(info["first_seen"], when)   # keep the earliest time
    info["last_seen"]  = max(info["last_seen"],  when)   # keep the latest time
    info["txn_count"] += 1                               # one more payment on this device


customer_docs = [{
    "_id": c["customer_id"],
    "created_at": to_date(c["created_at"]),
    "customer_age": c["customer_age"],
    "home_city": c["home_city"],
    "region": c["region"],
    "devices": list(devices[c["customer_id"]].values()),     # embedded
    "is_synthetic": c["is_synthetic"],
} for c in customers]


# 5. Write to MongoDB
db.customers.drop()
db.transactions.drop()
db.customers.insert_many(customer_docs)
db.transactions.insert_many(transactions)

print("customers:   ", db.customers.count_documents({}))
print("transactions:", db.transactions.count_documents({}))
print("fraud:       ", db.transactions.count_documents({"fraud_label": 1}))

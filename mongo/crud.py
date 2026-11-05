"""Step 4: CRUD operations on the payv collections."""

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# Connect to MongoDB using the connection string from the MONGODB_URI env var,
db = MongoClient(os.environ["MONGODB_URI"])["payv"]

# "transactions" collection in payv (created on first insert)
tx = db.transactions

# Demo documents use IDs starting with TX_DEMO_ so they never clash with real data
DEMO = {"_id": {"$regex": "^TX_DEMO_"}}
tx.delete_many(DEMO)        # remove leftovers from a previous run

# Attach the demo transactions to a real customer
customer = db.customers.find_one()

def demo_txn(n, rupees, category, channel):
    """A small transaction document shaped like the real ones."""
    return {
        "_id": f"TX_DEMO_{n:04d}",
        "customer_id": customer["_id"],
        "transaction_time": datetime.now(timezone.utc),
        "amount_paise": rupees * 100,
        "transaction_amount": float(rupees),
        "payment_channel": channel,
        "split": "demo",
        "merchant": {"merchant_id": "M_DEMO", "name": "Demo Merchant",
                     "category": category, "location": None},
        "device": None,
        "fraud_label": 0,
        "is_synthetic": True,
    }

# 1. insert_one, adding one document
result = tx.insert_one(demo_txn(1, 2500, "grocery", "UPI"))
print("insert_one  ->", result.inserted_id)
# result.inserted_id is the _id of the new document. Expected: TX_DEMO_0001.

# 2. insert_many, adding several documents in one call
result = tx.insert_many([
    demo_txn(2, 15000, "electronics", "card"),
    demo_txn(3,   800, "grocery",     "wallet"),
    demo_txn(4, 52000, "gift_cards",  "UPI"),
])
print("insert_many ->", result.inserted_ids)
# Expected: ['TX_DEMO_0002', 'TX_DEMO_0003', 'TX_DEMO_0004'].

# 3. FILTER: which documents. UPI gift-card payments of Rs 10,000 or more
query = {                                       # start of the search conditions (all must be true)
    "payment_channel": "UPI",                   # paid by UPI
    "merchant.category": "gift_cards",          # merchant category is gift_cards (inside the "merchant" sub-document)
    "amount_paise": {"$gte": 10_000 * 100},     # amount >= Rs 10,000 (stored in paise, so x100 = 1,000,000)
}                                               # end of the search conditions
# PROJECTION: which fields come back (1 = include)
projection = {"_id": 1, "transaction_time": 1, "transaction_amount": 1, "merchant.category": 1}  # return only these 4 fields

print("find        ->", tx.count_documents(query), "matches; top 5 by amount:")  # count ALL matching documents and print the total
for doc in tx.find(query, projection).sort("transaction_amount", -1).limit(5):  # search, sort largest amount first, keep 5
    print("   ", doc)                           # print each of those 5 documents


# 4. Tag every real transaction where the customer had 3 or more recent failed payments, a common fraud warning sign:

result = tx.update_many(                                # update ALL documents that match (not just one)
    {"failed_transactions": {"$gte": 3}},              # filter: failed_transactions >= 3
    {"$set": {"flags.repeated_failures": True}},       # change: set flags.repeated_failures to True
)                                                       # result holds the counts
print("update_many -> matched", result.matched_count, "modified", result.modified_count)  # print found vs. changed

# 5.delete_one, removing one document
result = tx.delete_one({"_id": "TX_DEMO_0003"})
print("delete_one  ->", result.deleted_count, "deleted")
# Expected: 1 deleted. If several documents match, delete_one removes only the first one it finds; delete_many removes them all.

# 6. Clean up
tx.delete_many(DEMO)
print("transactions now:", tx.count_documents({}))
# Expected: 6788, back to the real data only. The flags tags from 4 stay; they're harmless

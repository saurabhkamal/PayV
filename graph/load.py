"""Steps 2-3: build the PayV graph in Neo4j from a Supabase sample."""

import os                              # to read the settings from the .env file
from collections import defaultdict    # a dictionary that creates empty values on its own
from dotenv import load_dotenv
from supabase import create_client     # client to read data from Supabase

from db import get_driver              # helper from db.py: the Neo4j connection

load_dotenv()
N_SHARED_DEVICES = 20      # shared devices (rings) to include: ~155 customers, ~8,000 transactions
BATCH = 1000               # send rows to Neo4j 1,000 at a time instead of one by one (much faster)

# connect to Supabase, source of data
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

def fetch_transactions(columns, customer_ids=None):
    """Read transactions from Supabase, 1000 rows per request."""
    rows, last_id = [], ""       # all rows collected so far; last id seen ("" = start)
    while True:                 # keep asking until Supabase returns nothing
        query = sb.table("transactions").select(columns)     # only the columns we need
        if customer_ids:                  # If a customer_id was given
            query = query.in_("customer_id", customer_ids)  # only those customers
        page = (query.gt("transaction_id", last_id)  # only rows after the last one seen 
                .order("transaction_id")          # order by transaction_id (ascending)
                .limit(1000)                       # only 1000 rows at a time
                .execute().data)                        # send the request to Supabase

        if not page:                # if Supabase returned nothing, we're done
            break                   # stop the loop
        rows += page                # add this page to the collection
        last_id = page[-1]["transaction_id"]  # remember where this page ended

    print(f"Fetched {len(rows)} transactions from Supabase.")
    return rows     # give back all rows

# 1. Pick the sample: shared devices -> their customers
print("1. Finding shared devices")
pairs = fetch_transactions("transaction_id,device_id,customer_id")  # get all transactions, only 3 columns
customers_by_device = defaultdict(set)  # device_id -> set of customer_ids
for row in pairs:  # go through every transaction
        if row["device_id"]:     # skip the payments that don't have a device_id (e.g. cash payments)
             customers_by_device[row["device_id"]].add(row["customer_id"])  # this customer used this device
# keep devices with 3+ customers, sort by id so the choice is the same every run, take the first 20
shared_devices = sorted(device for device, customers in customers_by_device.items() if len(customers) >= 3)[:N_SHARED_DEVICES]

# collect every customer who used one of the 20 shared devices
chosen = set()       # empty set, a set keeps each customer only once
for device in shared_devices:    # go through 20 shared devices
    chosen.update(customers_by_device[device])  # add all customers of this device to the set
ids = sorted(chosen)  # sort the customer_ids 
print(f"Found {len(shared_devices)} shared devices -> {len(ids)} customers")

# 2. Fetch everything about those customers
print("2. Fetching their transactions")
# the columns we want, plus the merchant, device and label tables joined in
columns = ("transaction_id, customer_id, transaction_amount, transaction_time, "
           "merchants(*), devices(*), labels(fraud_label)")
rows = fetch_transactions(columns, ids)          # all transactions of our customers
# the customer details (age, city, region) for the same customers
customers = sb.table("customers").select("*").in_("customer_id", ids).execute().data

# 3. Reshape into rows for nodes and relationships

# Customer nodes: Keep only the 4 columns we need
customer_rows = []
for c in customers:
     customer_rows.append({
          "customer_id": c["customer_id"],
          "customer_age": c["customer_age"],
          "home_city": c["home_city"],
          "region": c["region"],
     })

merchants = {}   # merchant_id -> merchant_row
devices = {}     # device_id -> device_row
used = {}        # (customer_id, device_id) -> True
paid_rows = []        # (customer_id, merchant_id, transaction_id, amount, time, label)

rows.sort(key=lambda r: r["transaction_time"])  # oldest transactions first

for r in rows:
    customer_id = r["customer_id"]
    time = r["transaction_time"]
    m = r["merchants"]      # the joined merchants
    d = r["devices"]        # the joined device, or None

    # Merchant nodes: Keep only the 3 columns we need
    merchants[m["merchant_id"]] = {
          "merchant_id": m["merchant_id"],
          "name": m["synthetic_name"],
          "category": m["merchant_category"],
    }

    # Paid arrow: one per transaction
    paid_rows.append({
          "transaction_id": r["transaction_id"],
          "customer_id": customer_id,
          "merchant_id": m["merchant_id"],
          "amount": float(r["transaction_amount"]),
          "time": time,
          "fraud_label": r["labels"]["fraud_label"],
          "device_id": d["device_id"] if d else None,  # some transactions have no device
    })

    # Payments without a device have no Device node or USED_DEVICE arrow
    if d is None:
           continue # skip the rest of this loop and go to the next transaction

    # Device nodes: Keep only the 2 columns we need
    devices[d["device_id"]] = {
            "device_id": d["device_id"],
            "device_kind": d["device_kind"],
        }

    # USED_DEVICE arrow: one per (customer, device) pair
    pair = (customer_id, d["device_id"])
    if pair not in used:              # first time this pair appears = earliest use
          used[pair] = {
               "customer_id": customer_id,
               "device_id": d["device_id"],
               "first_seen": time,  # first time this customer used this device
               "last_seen": time,   # last time this customer used this device
               "transactions": 0,
          }
    used[pair]["last_seen"] = time      # update the last time this customer used this device
    used[pair]["transactions"] += 1      # count how many times this customer used


# 4. Uniqueness Constraints (before any MERGE): forbid duplicates, and create an index that makes MERGE fast
CONSTRAINTS = [
    # no two customer nodes may have the same customer_id
    "CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE",
    # no two devices have the same device_id
    "CREATE CONSTRAINT device_id IF NOT EXISTS FOR (d:Device) REQUIRE d.device_id IS UNIQUE",
    # no two Merchant nodes may have the same merchant_id
    "CREATE CONSTRAINT merchant_id IF NOT EXISTS FOR (m:Merchant) REQUIRE m.merchant_id IS UNIQUE",
    # no two PAID arrows have the same transaction_id (one arrow = one payment)
    "CREATE CONSTRAINT paid_id IF NOT EXISTS FOR ()-[p:PAID]-() REQUIRE p.transaction_id IS UNIQUE",

]


# 5. MERGE = find it, or create it if missing
MERGE_CUSTOMERS = """
// take the list of rows we send, one row at a time, called r
UNWIND $rows AS r
// find the customer with this id, or create it if missing
MERGE (c:Customer {customer_id: r.customer_id})
// fill in (or refresh) the other properties
SET c.customer_age = r.customer_age, c.home_city = r.home_city, c.region = r.region
"""

MERGE_DEVICES = """
// one row at a time
UNWIND $rows AS r
// find or create the Device by its id
MERGE (d: Device {device_id: r.device_id})
// mobile or browser
SET d.device_kind = r.device_kind
"""

MERGE_MERCHANTS = """
// one row at a time
UNWIND $rows AS r
// find or create the Merchant by its id
MERGE (m: Merchant {merchant_id: r.merchant_id})
// shop name and category
SET m.name = r.name, m.category = r.category
"""

MERGE_USED_DEVICE = """
// one customer+device pair at a time
UNWIND $rows AS r
// find the customer already created above
MATCH (c:Customer {customer_id: r.customer_id})
// find the device already created above
MATCH (d:Device {device_id: r.device_id})
// draw the arrow between them, unless it is already there
MERGE (c)-[u:USED_DEVICE]->(d)
// text -> real date-time, so we can compare times later
SET u.first_seen = datetime(r.first_seen), 
    u.last_seen = datetime(r.last_seen),
    u.transactions = r.transactions
"""

MERGE_PAID = """
// one transaction at a time
UNWIND $rows AS r
// the customer who paid
MATCH (c:Customer {customer_id: r.customer_id})
// the merchant who was paid
MATCH (m:Merchant {merchant_id: r.merchant_id})
// one arrow per transaction_id, so payments to the same shop stays separate
MERGE (c)-[p:PAID {transaction_id: r.transaction_id}]->(m)
// payment details; device_id is the extra we added for Query 3
SET p.amount = r.amount,
    p.time = datetime(r.time),
    p.fraud_label = r.fraud_label,
    p.device_id = r.device_id
"""

def write(driver, cypher, rows):
     for i in range(0, len(rows), BATCH):  # i = 0, 1000, 2000, ... up to the number of rows
          driver.execute_query(cypher, rows=rows[i:i + BATCH])   # run the query on the next 1,000 rows ($rows)

print("3. Writing to Neo4j")
with get_driver() as driver:                 # open the Neo4j connection; closed automatically at the end
    for c in CONSTRAINTS:                    # constraints first...
        driver.execute_query(c)              # ...so every MERGE below can use them
    write(driver, MERGE_CUSTOMERS, customer_rows)               # nodes first,
    write(driver, MERGE_DEVICES, list(devices.values()))        # because arrows need
    write(driver, MERGE_MERCHANTS, list(merchants.values()))    # both ends to exist
    write(driver, MERGE_USED_DEVICE, list(used.values()))       # then customer -> device arrows
    write(driver, MERGE_PAID, paid_rows)

    # 6. count what is in the graph

    # Nodes: group all nodes by their label (Customer, Device, Merchant) and count each group
    node_counts = driver.execute_query("""
        MATCH (node)
        RETURN labels(node)[0] AS label, count(*) AS how_many
        ORDER BY label
    """).records

    # Relationships: group all arrows by their type (PAID, USED_DEVICE) and count each group
    rel_counts = driver.execute_query("""
        MATCH ()-[rel]->()
        RETURN type(rel) AS rel_type, count(*) AS how_many
        ORDER BY rel_type
    """).records

    print("Nodes:")
    for row in node_counts:
         print(f" {row['label']}: {row['how_many']:,}")

    print("Relationships")
    for row in rel_counts:
         print(f"  {row['rel_type']}: {row['how_many']:,}")
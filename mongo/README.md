# PayV on MongoDB Atlas

Part of the PayV fraud data (synthetic Indian payments, already loaded into Supabase with
`python ingest.py all`) modelled as **documents** in MongoDB Atlas and queried from Python with **pymongo**.

```
mongo/
├── README.md            <- you are here
├── mongo_connect.py     <- Step 1: connection test
├── load.py              <- Step 3: copy a sample from Supabase into MongoDB
├── crud.py              <- Step 4: insert, find, update, delete
├── indexes.py           <- Step 5: indexes and explain() before and after
└── aggregations.py      <- Step 6: fraud rate per category, top 10 customers by last-24h amount
```

| Step | What | Status |
|---|---|---|
| 1 | Atlas cluster, database user, IP access rule, connect with `MongoClient` | Done |
| 2 | Design the `customers` and `transactions` collections (embed vs. reference) | Done |
| 3 | Load at least 5,000 transactions with customer, merchant and device fields | Done |
| 4 | `insert_one`, `insert_many`, `find` (filter + projection), `update_many`, `delete_one` | Done |
| 5 | Indexes on `customer_id` and time, `explain()` before and after | Done |
| 6 | Aggregations: fraud rate per merchant category, top 10 customers by last-24h amount | Done |

---

## Step 1 - Atlas setup and connection

### Atlas
1. Created a free (**M0**) cluster, `PayV-cluster`.
2. Created a database user with **read and write** rights (*Database Access*).
3. Added IP access rules (*Network Access*):
   - `43.229.163.35/32` - added automatically when the cluster was created
   - `0.0.0.0/0` - allow from anywhere (see note below)

> **Note on the IP rule.** With only the `/32` rule the connection failed with
> `SSL handshake failed ... TLSV1_ALERT_INTERNAL_ERROR`, even though `curl ifconfig.me` showed the same IP.
> Atlas rejects connections from unknown IPs during the TLS handshake, and this ISP sends MongoDB
> traffic (port 27017) out through a different public IP than web traffic. Adding `0.0.0.0/0` fixed it.
> That is acceptable for a free cluster holding synthetic data; a real deployment should allow only
> known IPs (or use private networking).

### Python
The connection string is kept in the project's `.env` (already in `.gitignore`), never in code:
```
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster-host>/?retryWrites=true&w=majority&appName=PayV-cluster
```

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt     # includes pymongo
python mongo/mongo_connect.py
```
Expected output:
```
Connected to MongoDB Atlas!
Databases: ['admin', 'local']
```
Only the system databases exist at first. MongoDB creates a database and its collections on the first insert.

---

## Step 2 - Data model

### What the source data looks like
Measured on the PayV tables (110,000 transactions, 2,500 customers):

| Question | Answer |
|---|---|
| Devices per customer | 1 to 8 (median 2): small and bounded |
| Transactions per customer | median 45, max 113, and growing with every payment |
| Devices shared by several customers | 120 devices used by 3 to 11 customers each (the "shared ring device" fraud signal); 5,285 devices belong to one customer |
| Device attributes | only `device_id` and `device_kind` (`mobile` / `browser`), never change |
| Customer-device link | none in the source; it exists only through transactions (`customer_id` + `device_id`) |
| Fraud label | stored in a separate `labels` table, not in `transactions` |

### Collection `customers` - devices **embedded**
```json
{
  "_id": "C_0004ff2f7739f0d3",
  "created_at": ISODate("2023-04-02T18:30:00Z"),
  "customer_age": 60,
  "home_city": "Jaipur",
  "region": "north",
  "devices": [
    { "device_id": "D_506a929cba09f1ad", "device_kind": "browser",
      "first_seen": ISODate("2024-10-09T13:38:16.727Z"),
      "last_seen":  ISODate("2026-02-28T13:53:23.947Z"),
      "txn_count": 47 },
    { "device_id": "D_33b70b18f806c856", "device_kind": "mobile",
      "first_seen": ISODate("2025-03-08T21:58:18.260Z"),
      "last_seen":  ISODate("2026-01-11T13:04:16.975Z"),
      "txn_count": 9 }
  ],
  "is_synthetic": true
}
```
The `devices` list is built from the customer's transactions. Both examples are real documents from the
loaded `payv` database.

### Collection `transactions` - **references** the customer, **copies** a few key fields
```json
{
  "_id": "TX_0000000965",
  "customer_id": "C_0004ff2f7739f0d3",
  "transaction_time": ISODate("2024-10-09T13:38:16.727Z"),
  "amount_paise": 364783,
  "transaction_amount": 3647.83,
  "payment_channel": "card",
  "split": "warmup",
  "customer": { "customer_age": 60, "home_city": "Jaipur", "region": "north",
                "location": { "city": "Jaipur", "lat": 26.91, "lon": 75.79 } },
  "merchant": { "merchant_id": "M_bdfbd509bd290325", "name": "Synthetic Merchant 000093",
                "category": "travel",
                "location": { "city": "Jamshedpur", "lat": 22.8, "lon": 86.2 } },
  "device":   { "device_id": "D_506a929cba09f1ad", "device_kind": "browser" },
  "account_age": 555,
  "previous_transactions": 0,
  "average_transaction_value": null,
  "failed_transactions": 0,
  "fraud_label": 0,
  "is_synthetic": true
}
```

```
customers (devices embedded)  1 ──────────<  many  transactions
      _id  ◄───────────────────────────────  customer_id
                                             + copies of customer / merchant / device fields
```

### Why embed or reference

| Relationship | Choice | Reason |
|---|---|---|
| Customer → devices | **Embed** | The list is small (at most 8) and stays small; a device has only two fields; devices are read together with their customer, so one read returns everything. |
| Customer → transactions | **Reference** (separate collection) | The list grows without limit. Embedded, every payment would rewrite an ever larger customer document, heading towards MongoDB's 16 MB document limit. Transactions are also queried on their own (by time, category, split) and need their own indexes. |
| Transaction → customer, merchant, device details | **Copy a small subset** (extended reference) | Reports group by merchant category and need customer and device context. Copying these rarely changing fields avoids a `$lookup` (join) on every query. |

### Trade-offs
- **Shared devices are duplicated.** One of the 120 ring devices can appear in up to 11 customers' `devices`
  arrays. Device data is tiny and immutable, so this is cheap. "All customers who used device X" is
  `customers.find({"devices.device_id": "D_..."})`, made fast by a multikey index on `devices.device_id`.
- **Copied details can go stale.** If a merchant were renamed, old transactions would keep the old name.
  For payment records this is arguably correct: they show the facts at the time of payment.
- **The fraud label sits next to the inputs.** Postgres keeps `labels` separate so raw transactions never
  carry the answer. Here `fraud_label` is copied in for analysis (Step 6); it must be **excluded from model
  inputs**.

### Data types
| Field | Stored as | Why |
|---|---|---|
| `transaction_time`, `created_at` | BSON Date (Python `datetime`) | Range queries, the time index and the 24-hour window need real dates, not strings. |
| `amount_paise` | integer | Exact money; sums use this field. |
| `_id` | the source ID (`transaction_id`, `customer_id`) | Already unique; reloading cannot create duplicates. |
| locations | nested `{city, lat, lon}` | Already JSON in the source. |

---

## Step 3 - Loading the data

`mongo/load.py` reads from Supabase (already filled by `python ingest.py all`) and writes the two
collections into the MongoDB database **`payv`**.

```powershell
python mongo/load.py
```

### Which transactions
**Every transaction of the first 150 customers** (sorted by `customer_id`): 6,788 transactions,
from all splits (warmup, train, validation, holdout; October 2024 to February 2026).

A sample by customer rather than "the first 5,000 transactions" keeps each customer's full history.
The first 5,000 rows by ID would be a narrow time slice with about 2 transactions per customer, which
would make the device lists and the "last 24 hours of activity" aggregation (Step 6) meaningless.
Customer IDs are hash-like, so the first 150 behave like a random sample.

### How it works
| Part | What happens |
|---|---|
| 1. Pick customers | Read the first 150 rows of `customers` from Supabase. |
| 2. Fetch transactions | Read their transactions 1,000 at a time (the Supabase API limit), paging with "`transaction_id` greater than the last one received". `select("*, merchants(*), devices(*), labels(fraud_label)")` makes Supabase join the merchant, device and fraud label through the foreign keys. |
| 3. Reshape | Build one transaction document per row: `customer_id` as the reference, plus copied `customer`, `merchant` and `device` sub-documents and `fraud_label`. Text timestamps become Python `datetime`, which pymongo stores as BSON Dates. |
| 4. Devices | Derive each customer's device list from their transactions (`first_seen`, `last_seen`, `txn_count` per device) and embed it in the customer document. |
| 5. Write | `drop()` both collections, then `insert_many`. Re-running the script gives the same result instead of duplicate-key errors. |

### Result
```
150 customers
fetched 1000 transactions
...
fetched 6788 transactions
customers:    150
transactions: 6788
fraud:        40
```

| Check | Result |
|---|---|
| Documents | `customers` 150, `transactions` 6,788 |
| Fraud | 40 transactions (0.59%, close to the dataset's 0.6%) |
| Dates stored as BSON Date | `transaction_time` 6,788/6,788, `created_at` 150/150 |
| Transactions without a device | 70 (`device: null`) |
| Customers with an empty `devices` list | 2 (all their payments had no device) |
| Size in Atlas | `customers` 66.65 kB (avg 444 B/doc), `transactions` 4.67 MB (avg 687 B/doc); about 1 MB on disk after compression |
| Indexes | only the default `_id` index so far (Step 5 adds more) |

## Step 4 - CRUD operations

`mongo/crud.py` demonstrates the five required operations on the `transactions` collection.

```powershell
python mongo/crud.py
```

### Keeping the loaded data intact
Steps 5 and 6 rely on the 6,788 loaded transactions, so inserts and deletes are shown on **demo documents**
whose `_id` starts with `TX_DEMO_` (no real ID can clash with them). They are attached to a real customer
and shaped like real transactions. The script removes leftover demo documents at the start (so it can be
re-run without `DuplicateKeyError`) and all demo documents at the end. The only lasting change is the
additive tag from `update_many`.

### Operations

| Operation | Code (shortened) | What it shows |
|---|---|---|
| `insert_one` | `tx.insert_one(demo_txn(1, 2500, "grocery", "UPI"))` | Add one document; `result.inserted_id` returns its `_id`. |
| `insert_many` | `tx.insert_many([demo_txn(2, ...), demo_txn(3, ...), demo_txn(4, ...)])` | Add several documents in one request (also how `load.py` loads the data). |
| `find` + filter + projection | see below | Select documents by several conditions, return only chosen fields. |
| `update_many` | `tx.update_many({"failed_transactions": {"$gte": 3}}, {"$set": {"flags.repeated_failures": True}})` | Tag every transaction whose customer had 3+ recent failed payments, a common fraud warning sign. |
| `delete_one` | `tx.delete_one({"_id": "TX_DEMO_0003"})` | Remove one document; `result.deleted_count` is 1. |

**find with filter and projection.** UPI gift-card payments of Rs 10,000 or more, five largest first:
```python
query = {
    "payment_channel": "UPI",
    "merchant.category": "gift_cards",          # dot notation reaches into the merchant sub-document
    "amount_paise": {"$gte": 10_000 * 100},     # amounts are stored in paise
}
projection = {"_id": 1, "transaction_time": 1, "transaction_amount": 1, "merchant.category": 1}
tx.find(query, projection).sort("transaction_amount", -1).limit(5)
```
SQL equivalent:
```sql
SELECT transaction_id, transaction_time, transaction_amount, merchant_category
FROM transactions
WHERE payment_channel = 'UPI' AND merchant_category = 'gift_cards' AND amount_paise >= 1000000
ORDER BY transaction_amount DESC LIMIT 5;
```

### Result
```
insert_one  -> TX_DEMO_0001
insert_many -> ['TX_DEMO_0002', 'TX_DEMO_0003', 'TX_DEMO_0004']
find        -> 21 matches; top 5 by amount:
    {'_id': 'TX_0000076879', 'transaction_time': datetime.datetime(2025, 10, 9, 21, 55, 47, 415000), 'transaction_amount': 126556.51, 'merchant': {'category': 'gift_cards'}}
    {'_id': 'TX_0000040800', 'transaction_time': datetime.datetime(2025, 5, 10, 5, 56, 58, 899000), 'transaction_amount': 85654.32, 'merchant': {'category': 'gift_cards'}}
    {'_id': 'TX_DEMO_0004', 'transaction_time': datetime.datetime(2026, 11, 5, 16, 57, 46, 69000), 'transaction_amount': 52000.0, 'merchant': {'category': 'gift_cards'}}
    {'_id': 'TX_0000032464', 'transaction_time': datetime.datetime(2025, 4, 5, 3, 9, 32, 453000), 'transaction_amount': 39741.88, 'merchant': {'category': 'gift_cards'}}
    {'_id': 'TX_0000001001', 'transaction_time': datetime.datetime(2024, 10, 9, 21, 36, 47, 840000), 'transaction_amount': 22534.58, 'merchant': {'category': 'gift_cards'}}
update_many -> matched 651 modified 651
delete_one  -> 1 deleted
transactions now: 6788
```

| Observation | Meaning |
|---|---|
| `TX_DEMO_0004` (Rs 52,000) is third in the `find` result | The inserted demo documents are immediately queryable. |
| Only four fields per document | The projection works; `_id` is returned unless excluded with `"_id": 0`. |
| `matched 651 modified 651` | 651 of 6,788 transactions were tagged. A second run reports `modified 0`, because `$set` writes a value that is already there: the update is safe to repeat. |
| `transactions now: 6788` | All demo documents were removed; the real data is unchanged. |
| Times have no timezone | pymongo returns dates as UTC without timezone info; Atlas shows the same values marked `UTC`. |

The tagged documents can be checked in Atlas Data Explorer with the filter
`{ "flags.repeated_failures": true }` (651 documents).

## Step 5 - Indexes and `explain()`

`mongo/indexes.py` runs one query with `explain()`, creates the two indexes, and runs the same query again.

```powershell
python mongo/indexes.py
```

### What the script does
1. `tx.drop_indexes()` removes any indexes from a previous run, so "before" really has no index
   (the automatic `_id` index is never dropped).
2. `explain()` on the query **"all transactions of customer `C_09768e467feed4a5`"** (48 transactions):
   ```python
   tx.find({"customer_id": "C_09768e467feed4a5"}).explain()
   ```
3. Creates the two indexes:
   ```python
   tx.create_index([("customer_id", ASCENDING)])        # -> customer_id_1
   tx.create_index([("transaction_time", ASCENDING)])   # -> transaction_time_1
   ```
4. `explain()` on the same query again.

From each `explain()` report the script prints the plan MongoDB chose (`queryPlanner.winningPlan`, following
each stage's `inputStage`) and four numbers from `executionStats`:

| Field | Meaning |
|---|---|
| plan | `COLLSCAN` = read every document; `IXSCAN` = look up the index; `FETCH` = load the matching documents |
| `nReturned` | documents returned |
| `totalKeysExamined` | index entries read |
| `totalDocsExamined` | documents read |
| `executionTimeMillis` | time on the server |

### Result
```
BEFORE indexes
  plan:           COLLSCAN
  returned:       48
  keys examined:  0
  docs examined:  6788
  time (ms):      8
created: customer_id_1
created: transaction_time_1
AFTER indexes
  plan:           FETCH -> IXSCAN
  returned:       48
  keys examined:  48
  docs examined:  48
  time (ms):      1
indexes now: ['_id_', 'customer_id_1', 'transaction_time_1']
```

| | Before | After |
|---|---|---|
| Plan | `COLLSCAN` (read the whole collection) | `FETCH <- IXSCAN` (index lookup, then load only the matches) |
| Documents examined | 6,788 | 48 |
| Documents examined per document returned | 141 | 1 (the ideal) |
| Time | 8 ms | 1 ms |

The answer is the same 48 documents, but MongoDB reads only those 48 instead of the whole collection.
With 6,788 small documents both runs are fast; **documents examined** is the meaningful measure. A collection
scan grows with the collection size, while the index lookup grows only with the number of matches, so on
millions of transactions the difference becomes seconds versus milliseconds.

### Why these two indexes
- **`customer_id`**: a fraud check looks up the paying customer's history (devices, amounts, failures)
  before approving a payment.
- **`transaction_time`**: date-range queries ("everything on 24 December 2025") and the 24-hour window
  in Step 6.

**Trade-off:** each index takes storage, and every insert or update must also update the index, which
slows writes slightly. Only fields that are searched often are indexed.

The indexes are visible in Atlas Data Explorer under `payv` → `transactions` → **Indexes**; the
**Explain** button in the Documents tab draws the same plan as a diagram.

## Step 6 - Aggregation pipelines

`mongo/aggregations.py` runs two pipelines on the `transactions` collection.

```powershell
python mongo/aggregations.py
```

An aggregation pipeline passes documents through a series of stages, each doing one job, like SQL's
`WHERE` / `GROUP BY` / `ORDER BY`:

| Stage | Does | SQL equivalent |
|---|---|---|
| `$match` | keep only some documents | `WHERE` |
| `$group` | one result per group, with counts and sums | `GROUP BY` |
| `$project` | choose, rename or calculate fields | `SELECT ... AS ...` |
| `$sort`, `$limit` | order, keep the first N | `ORDER BY`, `LIMIT` |
| `$setWindowFields` | add a per-group value to every document without merging them | `MAX(...) OVER (PARTITION BY ...)` |

### Pipeline 1 - fraud rate per merchant category
```python
[
    {"$group": {"_id": "$merchant.category",
                "transactions": {"$sum": 1},             # count
                "fraud": {"$sum": "$fraud_label"}}},     # fraud = 1, normal = 0, so the sum counts frauds
    {"$project": {"_id": 0, "category": "$_id", "transactions": 1, "fraud": 1,
                  "fraud_rate_pct": {"$round": [{"$multiply": [{"$divide": ["$fraud", "$transactions"]}, 100]}, 2]}}},
    {"$sort": {"fraud_rate_pct": -1}},
]
```
`merchant.category` comes from the merchant fields copied into each transaction (Step 2), so no join is needed.

Result:
```
Fraud rate per merchant category
  electronics: 19 fraud out of 865 transactions (2.2%)
  gift_cards: 9 fraud out of 452 transactions (1.99%)
  gaming: 12 fraud out of 635 transactions (1.89%)
  quick_commerce: 0 fraud out of 1000 transactions (0.0%)
  healthcare: 0 fraud out of 413 transactions (0.0%)
  travel: 0 fraud out of 404 transactions (0.0%)
  other: 0 fraud out of 362 transactions (0.0%)
  grocery: 0 fraud out of 1271 transactions (0.0%)
  education: 0 fraud out of 422 transactions (0.0%)
  food: 0 fraud out of 964 transactions (0.0%)
```
- The counts reconcile with Step 3: frauds 19 + 9 + 12 = 40, transactions add up to 6,788.
- All 40 frauds fall in three categories (electronics, gift cards, gaming), typical "cash-out" categories
  because the goods are easy to resell. The dataset's labels were generated in "learnable" mode
  (see `data/DATA_CARD.md`), so this pattern is deliberately clear. The other seven categories have no
  fraud **in this 150-customer sample**; with all 110,000 transactions a few may appear.
- Tied rates (0.0%) have no guaranteed order; adding `"category": 1` to `$sort` would fix it.

### Pipeline 2 - top 10 customers by amount in their last 24 hours of activity
"Last 24 hours of activity" is taken **per customer**: the 24 hours before that customer's most recent
transaction. Customers are active at different times, so one shared window (e.g. the last 24 hours of the
dataset) would leave most customers with no transactions at all.

```python
[
    # each customer's latest transaction time, written onto all of their transactions
    {"$setWindowFields": {"partitionBy": "$customer_id",
                          "output": {"last_time": {"$max": "$transaction_time"}}}},
    # keep transactions at most 24 hours before that time ($expr: compare two fields of one document)
    {"$match": {"$expr": {"$gte": ["$transaction_time",
        {"$dateSubtract": {"startDate": "$last_time", "unit": "hour", "amount": 24}}]}}},
    # per customer: total amount and number of transactions in the window
    {"$group": {"_id": "$customer_id",
                "amount_paise": {"$sum": "$amount_paise"},
                "transactions": {"$sum": 1},
                "last_time": {"$first": "$last_time"},
                "home_city": {"$first": "$customer.home_city"}}},
    {"$sort": {"amount_paise": -1}},
    {"$limit": 10},
    {"$project": {"_id": 0, "customer_id": "$_id", "home_city": 1, "transactions": 1, "last_time": 1,
                  "amount_rupees": {"$divide": ["$amount_paise", 100]}}},
]
```
- `$dateSubtract` needs real dates, which is why Step 3 stored `transaction_time` as a BSON Date.
- Sums use the exact integer `amount_paise`; conversion to rupees happens only at the end.
- The amounts include every authorisation attempt in the window, including failed ones (payment outcomes
  were not copied to MongoDB).

Result:
```
Top 10 customers by amount in their last 24 hours of activity
  C_083f2888db375225 (Kochi): Rs 132,271.04 in 7 transactions, last one at 2026-02-11 08:16:46.494000 UTC
  C_0004ff2f7739f0d3 (Jaipur): Rs 108,791.87 in 9 transactions, last one at 2026-02-28 13:53:23.947000 UTC
  C_00d12d9a443db216 (Ahmedabad): Rs 72,398.31 in 8 transactions, last one at 2026-02-21 19:04:11.851000 UTC
  C_03c92a046ce16616 (Hyderabad): Rs 54,244.03 in 9 transactions, last one at 2026-02-12 19:16:47.189000 UTC
  C_0a0deb43c107f797 (Patna): Rs 23,248.68 in 5 transactions, last one at 2026-02-20 21:56:10.184000 UTC
  C_0e3483cb57427412 (Hyderabad): Rs 22,434.55 in 2 transactions, last one at 2026-02-21 09:09:05.559000 UTC
  C_0dc5cc9f4b41a714 (Pune): Rs 21,514.05 in 2 transactions, last one at 2025-12-27 09:00:21.543000 UTC
  C_0a4220462594b45e (Delhi): Rs 19,759.25 in 2 transactions, last one at 2026-02-16 03:59:38.905000 UTC
  C_082691b114bb8de1 (Bhubaneswar): Rs 19,129.92 in 2 transactions, last one at 2026-02-14 01:01:49.369000 UTC
  C_05975f47a31a783b (Jaipur): Rs 17,313.75 in 8 transactions, last one at 2026-02-09 15:17:36.958000 UTC
```
Several of the top customers made 5 to 9 payments within 24 hours, up to Rs 1.3 lakh in total. A burst of
high-value payments in a short window is a classic signal for fraud review; it is the same idea as the
`txn_amount_last_24h_paise` feature in the source data.

Both pipelines can also be built stage by stage in Atlas Data Explorer (`payv` → `transactions` →
**Aggregations**), which shows the documents after each stage.

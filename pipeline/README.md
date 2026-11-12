# PayV feature pipeline

Part of the PayV fraud data (synthetic Indian payments, already loaded into Supabase with
`python ingest.py all`). The client gave us a ready-made `features` table. Here we **rebuild those
features and reason codes ourselves from the raw tables** and then check how well our values match
theirs.

Why do this? A fraud model is only as good as its features. If we can't reproduce the client's
numbers from the raw data, either their pipeline or our understanding of it is wrong, and both are
worth knowing before anyone trains a model on it.

```
pipeline/
├── README.md       <- you are here
├── load_data.py    <- Step 1: load the raw tables from Supabase into pandas, save a local cache
├── quality_report.py  <- Step 2: data quality report on the raw tables
├── build_features.py  <- Step 3: rebuild the features using only earlier data
├── reason_codes.py    <- Step 4: extra features for the codes, then reason codes R01 to R08
├── compare.py         <- Step 5: compare our values with the client's features table
└── cache/          <- local copy of the tables (git-ignored, never pushed)
```

| Step | What | Status |
|---|---|---|
| 1 | Load customer, merchant, device, transaction, payment_outcome and label into pandas | Done |
| 2 | Data quality report: nulls, duplicates, wrong types, amount outliers, rows per split | Done |
| 3 | Rebuild the features using only data from before each transaction (no leakage) | Done |
| 4 | Assign reason codes R01 to R06, plus velocity and high-risk MCC | Done |
| 5 | Compare with the client's `features` table: match rate per feature, explain every mismatch | Done |

**Result in one line:** our rebuild matches the client's table on all 110,000 payments, for every
feature and every reason code; the only differences are decimal rounding. See Step 5.

---

## Step 1 - Load the raw tables into pandas

### What the script does
`load_data.py` reads **7 tables** from Supabase into pandas DataFrames (a DataFrame is a table in
Python, like a spreadsheet) and saves each one as a **Parquet** file in `pipeline/cache/`.

- The **6 raw tables** that the features are rebuilt from: `customers`, `merchants`, `devices`,
  `transactions`, `payment_outcomes`, `labels`.
- The client's **`features`** table, which is loaded now so it can be compared with ours in Step 5.

Steps 2-5 then read the local files, which takes about a second, instead of downloading more than
450,000 rows from Supabase every time.

### All rows, not a sample
The task allows a sample of a few thousand rows where it says so, but the features need each
customer's **full history**: a "90-day average" or a "count in the last hour" is wrong if some of
the earlier payments were left out. The tables are small for pandas (110,000 payments), so
everything is loaded.

### Reading 1,000 rows at a time
Supabase returns at most **1,000 rows per request**, so each table is read in pages. Every table
is sorted by a column with a unique value in every row (its id), and each new page asks for the
rows **after the last id we already have**:

```
Page 1: customer_id > ""          -> first 1,000 customers   (remember the last id)
Page 2: customer_id > last id     -> next 1,000
Page 3: customer_id > last id     -> last 500
Page 4: customer_id > last id     -> empty -> stop
```

`payment_outcomes`, `labels` and `features` have one row per payment, so they are paged by
`transaction_id`.

### Data kept as it is
Step 1 changes nothing: no type conversion and no cleaning. Checking the types and the quality is
Step 2's job; if the data were fixed while loading, there would be nothing left to check.

### Run it
```bash
python -m pip install -r requirements.txt
python pipeline/load_data.py
```

Output:
```
customers            2,500 rows    6 columns
merchants              200 rows    5 columns
devices             10,120 rows    3 columns
transactions       110,000 rows   18 columns
payment_outcomes   110,000 rows    5 columns
labels             110,000 rows    7 columns
features           110,000 rows   22 columns

Saved to ...\pipeline\cache
```

Every table has the expected number of rows: one row per customer, merchant and device, and
exactly one outcome, one label and one feature row for each of the 110,000 payments.

### First look at the column types
Reading the cache back (`pd.read_parquet('pipeline/cache/transactions.parquet')`) gives 110,000
rows and 18 columns with these types:

| Type | Meaning | Columns |
|---|---|---|
| `str` | text | the ids, `payment_channel`, `merchant_category`, `split`, `transaction_time` |
| `int64` | whole number | `amount_paise`, `customer_age`, `account_age`, `previous_transactions`, `failed_transactions` |
| `float64` | decimal number | `transaction_amount`, `average_transaction_value` |
| `object` | a dictionary | `customer_location`, `merchant_location`, e.g. `{'lat': 28.61, 'lon': 77.21, 'city': 'Delhi'}` |
| `bool` | True / False | `is_synthetic` |

Three things carried forward to the next steps:
1. **`transaction_time` is text, not a date**, so time windows such as "the last 90 days" can't be
   computed until it is converted. Step 2 reports it as a wrong type.
2. **Locations are dictionaries**, and some payments have no customer location at all. Step 3 takes
   `lat` and `lon` out of them for the distance and keeps a missing location as missing.
3. **`previous_transactions` and `average_transaction_value` are already in the raw table**, but
   they are not used: there is no way to tell how they were computed or whether they include later
   payments. Step 3 builds its own values from the payment history.

### Windows note: blocked packages
On Windows 11 with **Smart App Control** switched on, the newest pandas (3.1.1) and pyarrow
(26.0.1) failed to import with *"An Application Control policy has blocked this file"*. Smart App
Control blocks unsigned compiled files that Microsoft hasn't seen often enough to trust, and these
releases were very new. One version older works, so `requirements.txt` pins **pandas 3.0.6** and
**pyarrow 25.0.1**. Plain `import pyarrow` worked even when blocked; the blocked file was its Parquet
part, so the check is:

```bash
python -c "import pyarrow.parquet; print('parquet ok')"
```

### Keeping the data out of GitHub
`pipeline/cache/` is listed in `.gitignore`. Only the code and this README are committed, never the
copied data.

---

## Step 2 - Data quality report

### What it checks
`quality_report.py` reads the 6 raw tables from the cache and runs five checks:

| # | Check | Question it answers |
|---|---|---|
| 1 | Nulls per column | Which values are missing, and how many? |
| 2 | Duplicates | Is any id or any whole row stored twice? |
| 3 | Wrong types | Is a column stored as the wrong kind of data, e.g. a date stored as text? |
| 4 | Outliers in amount | Are there extremely large or small payments? |
| 5 | Rows per split | How many payments are in warmup, train, validation and holdout, and do the dates fit? |

The report only **looks and counts**. Nothing is deleted or changed in the data; whether a finding
is a problem is decided below.

### Run it
```bash
python pipeline/quality_report.py
```

Output:
```
1. Nulls per column
 customers: no nulls
 merchants: no nulls
 devices: no nulls
 transactions: {'device_id': 1138, 'customer_location': 3257, 'average_transaction_value': 2829}
 payment_outcomes: {'failure_code': 97985}
 labels: no nulls

2. Duplicates
 customers: 0 repeated ids, 0 repeated rows
 merchants: 0 repeated ids, 0 repeated rows
 devices: 0 repeated ids, 0 repeated rows
 transactions: 0 repeated ids, 0 repeated rows
 payment_outcomes: 0 repeated ids, 0 repeated rows
 labels: 0 repeated ids, 0 repeated rows

3. Wrong types
 customers.created_at: stored as str, 0 values are not valid dates
 transactions.transaction_time: stored as str, 0 values are not valid dates
 payment_outcomes.outcome_time: stored as str, 0 values are not valid dates
 labels.label_available_at: stored as str, 0 values are not valid dates
 amount_paise != transaction_amount x 100: 0 rows
 fraud_label values: [0, 1]

4. Outliers in amount (rupees)
count     110000.00
mean        4478.12
std        95799.60
min            8.20
25%          582.55
50%         1250.34
75%         2717.58
max      7995933.05
 plain IQR rule: 10,344 outliers
 log IQR rule:   1,396 outliers
 fraud rate: all payments 0.6%, log outliers 11.4%

5. Rows per split
            count                              min                              max
split
warmup      10000 2024-10-01 00:05:15.602000+05:30 2024-12-31 23:39:03.133000+05:30
train       72050 2025-01-01 00:37:56.971000+05:30 2025-10-31 23:46:30.969000+05:30
validation  14061 2025-11-01 00:14:47.012000+05:30 2025-12-31 23:34:31.050000+05:30
holdout     13889 2026-01-01 01:06:56.017000+05:30 2026-02-28 23:37:27.471000+05:30
 split differs between transaction and labels: 0 rows
```

### 1. Nulls: four columns, each with a reason
A null is not always an error, so each one is judged on its own:

| Column | Missing | Verdict |
|---|---:|---|
| `payment_outcomes.failure_code` | 97,985 (89.1%) | **Expected.** Exactly the number of successful payments. A failure code says why a payment failed, so a successful payment has none. No successful payment has a code and no failed payment lacks one |
| `transactions.customer_location` | 3,257 (3.0%) | **Real gap.** We don't know where the customer was, so the distance feature in Step 3 must stay empty for these payments, not 0 |
| `transactions.device_id` | 1,138 (1.0%) | **Real gap.** No device was recorded, so `is_new_device` must stay empty: we can't say if the device is new or known |
| `transactions.average_transaction_value` | 2,829 (2.6%) | **Not used.** All of these rows have `previous_transactions = 0` (no history, so no average) |

An inconsistency was found in the last pair of columns: **10,523 other rows also have
`previous_transactions = 0` but still have an average.** A customer with no earlier payments
can't have an average, so these two columns contradict each other. This is one more reason why
Step 3 builds its own history from the payments and ignores these two columns.

### 2. Duplicates: none
No table has a repeated id or a repeated row. Rows are compared as text because the location
columns hold dictionaries, which pandas can't compare directly.

### 3. Types: dates stored as text
All 4 date columns came from Supabase as **text** (`str`). That is the wrong type: time windows
like "the last 90 days" need real dates. Every value converts to a valid date (0 failures), so
the fix is simply to convert them, and the report does so for the later checks.

The other checks are clean: `amount_paise` equals `transaction_amount × 100` in every row
(1 rupee = 100 paise), and `fraud_label` holds only 0 and 1.

### 4. Outliers in amount: why the log rule
Amounts run from **₹8.20 to ₹79,95,933**. The mean (₹4,478) is 3.6 times the median (₹1,250)
and the standard deviation is ₹95,800: the data is very **skewed**, with most payments small and
a few huge.

The usual **IQR rule** marks as an outlier anything beyond 1.5 × IQR outside the middle half
(Q1 to Q3). It assumes the values are spread evenly around the middle, which payment amounts
are not:

- **Plain IQR rule:** the upper fence is 2,718 + 1.5 × 2,135 = **₹5,920**. It flags **10,344
  payments (9.4%)**, about 1 in 11, including ordinary ₹6,000 purchases. Its lower fence is
  negative, so it can never flag a suspiciously tiny payment.
- **Log IQR rule:** the same rule applied to `log10(amount)`, i.e. to the number of digits
  (₹100 → 2, ₹1,000 → 3, ₹10,000 → 4). On this scale the amounts are spread evenly. The fences
  come out at about **one ×10 step beyond the middle half on each side**:

```
too small  |      normal range of payments        |  too large
  < ₹58    |  ₹58 --- ₹583 === ₹2,718 --- ₹27,382 |  > ₹27,382
           |  ÷10     └ middle half ┘        ×10  |
```

It flags **1,396 payments (1.3%)**: 411 below ₹58 and 985 above ₹27,382. For money, "how many
times bigger" is a fairer measure than "how many rupees bigger", so the log rule is used.

**The outliers are kept.** Fraud is **0.6%** across all payments but **11.4%** among the log
outliers, about 19 times higher. These are some of the most useful payments for catching fraud,
not errors to remove.

### 5. Rows per split

| Split | Rows | Share | Dates (Indian time) |
|---|---:|---:|---|
| warmup | 10,000 | 9.1% | 1 Oct 2024 to 31 Dec 2024 |
| train | 72,050 | 65.5% | 1 Jan 2025 to 31 Oct 2025 |
| validation | 14,061 | 12.8% | 1 Nov 2025 to 31 Dec 2025 |
| holdout | 13,889 | 12.6% | 1 Jan 2026 to 28 Feb 2026 |

Each split starts and ends on the right **Indian** calendar date, and the splits don't overlap.
The times are stored in UTC, where they would look wrong: warmup's first payment is
30 Sep 2024 18:35 UTC, which is 1 Oct 2024 00:05 IST. The `transactions` and `labels` tables give
the same split for every payment.

### Summary
- The data is **clean**: no duplicates, no unreadable values, and the amounts, labels and splits
  are consistent across tables.
- **One wrong type** (dates stored as text), fixed by converting them.
- **Two real gaps** that Step 3 must handle: 3,257 payments without a customer location and 1,138
  without a device. Their features stay empty, never 0 or "new".
- **One inconsistency in the client's columns** (`previous_transactions` and
  `average_transaction_value`), which are therefore not used.
- **1,396 amount outliers**, kept because they are much more likely to be fraud.

---

## Step 3 - Rebuild the features without leakage

### The one rule
For each payment, a feature may only use what the system **could have known at that moment**:
the payments **before** it, never the payment itself and never anything after it. The client's
feature catalogue (`data/feature_catalogue.json`) describes this as *"at authorisation, before
state update"*.

Breaking this rule is called **leakage**. A model trained on leaked features looks excellent in
testing, because it is quietly using information from the future, and then fails in production,
where that information does not exist yet.

### The features

| Feature | Meaning | Uses |
|---|---|---|
| `amount_to_avg_ratio` | this amount ÷ the customer's average amount over the previous 90 days | earlier payments |
| `is_new_device` | the customer has not used this device in the previous 90 days | earlier payments |
| `customer_merchant_distance_km` | straight-line (haversine) distance between customer and merchant | this payment only |
| `hour_of_day` | hour of the payment in **Indian time** (0-23) | this payment only |
| `is_night` | `hour_of_day` from 00:00 up to 04:59 (00:00 inclusive, 05:00 exclusive) | this payment only |
| `txn_count_last_1h` | number of the customer's payments in the previous hour | earlier payments |
| `txn_amount_last_24h_paise` | total paise the customer paid in the previous 24 hours | earlier payments |

Two rules from the catalogue shape the code:
- **"Earlier payments" means every attempt, including failed ones.** A fraudster's declined
  tries are part of the pattern, so they count in the averages, counts and totals.
- **Unknown stays unknown.** No history, no device or no location gives an empty value, never 0
  and never a guess.

### Run it
```bash
python pipeline/build_features.py
```

The result is saved to `pipeline/cache/our_features.parquet` (one row per payment:
`transaction_id` and the 7 columns above) for Steps 4 and 5.

### How it works

**Sort first.** The payments are sorted by `customer_id`, then by `time`, so each customer's
payments sit together from oldest to newest. Every window below relies on this order.

**A window that ends just before the payment.** The three history features use pandas `rolling`
per customer, with a time window that stops *just before* the current payment:

```
customer's payments:   P1 ── P2 ── P3 ── P4 ── P5 (now)
window for P5:        [──── previous 90 days ────)   <- P5 itself is not inside
```

```python
tx.groupby("customer_id").rolling("90D", on="time", closed="left")["transaction_amount"].mean()
```

- `groupby("customer_id")` keeps every customer's history separate.
- `"90D"` / `"24h"` / `"1h"` is how far back the window reaches, measured on the `time` column.
- `closed="left"` means the window includes its start but **not its end**, which is the current
  payment. This single argument is what keeps the current payment out of its own features.

A small helper, `window(column, size, how)`, runs this for `"mean"`, `"count"` or `"sum"`.

**is_new_device.** For every customer and device pair, `diff()` gives the time since the customer
last used that same device. The device is new if there is no earlier use (`NaT`) or the gap is
longer than 90 days. Payments without a device are then set to empty with `.mask()`. The column
uses pandas' `"boolean"` type, which can hold True, False *or* empty; a normal True/False column
can't hold an empty value.

```
device_id   gap         new?
D_A         NaT         True     <- first time on this device
D_A         5 minutes   False
D_A         109 days    True     <- not seen in the last 90 days
(none)      NaT         <NA>     <- no device: can't know, so empty
```

**Distance.** `lat` and `lon` are taken out of the location dictionaries with `.str.get()`, which
gives `NaN` where the location is missing. The haversine formula then measures the distance along
the Earth's curved surface (radius 6,371 km), for all rows at once. A missing location gives a
missing distance automatically.

**Hour and night.** The UTC time is converted to `Asia/Kolkata` before taking the hour. Using UTC
would put every payment 5 hours 30 minutes off and get `is_night` wrong.

**Velocity.** For the 1-hour count and the 24-hour total, an empty window means "no earlier
payments", so it is filled with 0. Here 0 is a real answer, not a guess, unlike for the ratio or
the distance, where empty means unknown.

### How each leakage rule is enforced

| Rule | How |
|---|---|
| Only data from **before** the payment | `rolling(..., closed="left")` and `diff()` only look backwards |
| The **current payment is excluded** | `closed="left"` |
| Customers don't mix | `groupby("customer_id")` |
| No future outcomes or labels | the script never reads `payment_outcomes` or `labels` |
| The client's precomputed columns are not trusted | `previous_transactions` and `average_transaction_value` are not used (see Step 2) |
| Unknown stays unknown | empty ratio, device flag and distance where the input is missing |

### Output
```
(110000, 8)

Empty values per feature:
transaction_id                      0
amount_to_avg_ratio              2829
is_new_device                    1138
customer_merchant_distance_km    3257
hour_of_day                         0
is_night                            0
txn_count_last_1h                   0
txn_amount_last_24h_paise           0
```

The empty values match the gaps found in Step 2 exactly: 2,829 payments with no earlier payment in
the previous 90 days, 1,138 without a device and 3,257 without a customer location.

### Worked example: one customer's first five payments
Customer `C_b90ff711ce3e3dba`, five payments within four minutes on the same phone, starting at
00:05 Indian time (18:35 UTC the day before):

| Payment | Amount ₹ | Earlier payments used | Ratio | New device | Count 1h | Amount 24h (paise) |
|---|---:|---|---:|---|---:|---:|
| TX_0000000001 | 790.38 | none | empty | True | 0 | 0 |
| TX_0000000002 | 2,319.80 | TX_1 | 2,319.80 ÷ 790.38 = **2.94** | False | 1 | 79,038 |
| TX_0000000003 | 1,132.82 | TX_1, TX_2 | 1,132.82 ÷ 1,555.09 = **0.73** | False | 2 | 3,11,018 |
| TX_0000000004 | 325.20 | TX_1 to TX_3 | 0.23 | False | 3 | 4,24,300 |
| TX_0000000005 | 455.15 | TX_1 to TX_4 | 0.40 | False | 4 | 4,56,820 |

- The current payment never appears in its own numbers: TX_2's 24-hour total is only TX_1's
  79,038 paise.
- TX_1 **failed**, but it still counts as an earlier attempt for TX_2 onwards.
- TX_1 has no customer location, so its distance is empty; TX_2 to TX_5 are 845.38 km from the
  merchant.
- All five are at hour 0 in Indian time, so `is_night` is True. In UTC they would show hour 18.

---

## Step 4 - Reason codes

### What reason codes are
A fraud score alone ("0.94") doesn't tell a support agent or a customer *why* a payment looks
risky. Reason codes are short, readable labels for the warning signs present in a payment, for
example `R01_NEW_DEVICE` or `R03_ODD_HOUR`. Each payment gets a list of the codes whose rule is
true; a payment with no warning signs gets an empty list.

### The rules and where the thresholds come from
The client requirement document (section 9.3) lists the eight codes with their meanings, and its
feature table (section 8) gives some thresholds. Three thresholds are not in the client documents
but are written in the dataset's training files (`data/training/`), in the fixed sentences used to
explain each code:

- *"Unusual observed city or customer to merchant distance above 500 km"*
- *"Amount is at least five times the observed 90 day average"*
- *"At least four prior authorisations observed in the preceding hour"*

| Code | Rule | Threshold source |
|---|---|---|
| R01_NEW_DEVICE | `is_new_device` is True (device not used in the previous 90 days) | client document |
| R02_GEO_MISMATCH | distance **> 500 km** or `is_new_city` is True | training files |
| R03_ODD_HOUR | `is_night` is True (00:00 to 04:59 IST) | client document |
| R04_FAILED_ATTEMPTS | **3 or more** failed outcomes in the previous 24 hours | client document |
| R05_AMOUNT_SPIKE | `amount_to_avg_ratio` **5 or more** | training files |
| R06_NEW_ACCOUNT | account **under 30 days** old | client document |
| R07_VELOCITY | `txn_count_last_1h` **4 or more** | training files |
| R08_HIGH_RISK_MCC | category is gaming, gift_cards or electronics | client document |

**Unknown gives no code.** If a feature is empty (no device, no location, no history), its code is
not given: a device can't be called "new" if we don't know which device it was.

### Three extra features
R02, R04 and R06 need features that Step 3 didn't build. They follow the same no-leakage rules.

**`is_new_city`.** The city is taken from the customer location. As with `is_new_device`, the
time since the customer was last seen in the same city is computed per customer and city pair;
the city is new if it was never seen before or not in the previous 90 days. Unknown location
gives an empty value.

**`failed_last_24h` and `has_recent_failures`.** This one has a leakage trap. Every payment has
two moments: when it **starts**, and when its **outcome** (SUCCESS or FAILED) comes back. A
failure is only known once its outcome has arrived, so it may only count for payments that start
**after `outcome_time`**:

```
10:00:00     payment A starts            (nobody knows yet that it will fail)
10:00:01     A's outcome: FAILED         <- from now on the failure is known
10:05:00     payment B starts            -> B counts A's failure
```

If B had started at 10:00:00.5, before A's outcome arrived, counting A for B would be leakage.

To handle this, the payments and the failure outcomes are put on **one timeline per customer**:
payments at the time they started (`failed = 0`) and failures at the time their outcome arrived
(`failed = 1`). A 24-hour window with `closed="left"`, as in Step 3, then sums `failed` over the
rows before each payment, which gives the number of failures known at that moment. The failure
rows are dropped afterwards and the count is copied back to each payment.
`has_recent_failures` is True when the count is 3 or more.

**`account_age_days` and `is_new_account`.** Complete days from the account's `created_at` to the
**time of the payment** (not to today, which would use the future). `is_new_account` is True
under 30 days.

### Assigning the codes
The eight rules are built as a table with one True/False column per code. For every payment, the
names of the True columns are collected into a list:

```
row   = [True, False, True, False, False, False, False, True]
codes = [R01_NEW_DEVICE, R02_GEO_MISMATCH, R03_ODD_HOUR, ..., R08_HIGH_RISK_MCC]
->      ['R01_NEW_DEVICE', 'R03_ODD_HOUR', 'R08_HIGH_RISK_MCC']
```

`.fillna(False)` on `is_new_device` and `is_new_city`, and the fact that comparing an empty ratio
with 5 gives False, make sure an unknown value never produces a code.

### Run it
```bash
python pipeline/reason_codes.py
```

The extra features and the codes are saved to `pipeline/cache/our_reason_codes.parquet` for
Step 5.

Output:
```
Payments per reason code:
R01_NEW_DEVICE          7305
R02_GEO_MISMATCH       90293
R03_ODD_HOUR           15438
R04_FAILED_ATTEMPTS     9877
R05_AMOUNT_SPIKE        3068
R06_NEW_ACCOUNT         1109
R07_VELOCITY           14509
R08_HIGH_RISK_MCC      32602

First payments of one customer:
      transaction_id                                                                            reason_codes
81484  TX_0000000001                                       [R01_NEW_DEVICE, R03_ODD_HOUR, R08_HIGH_RISK_MCC]
81485  TX_0000000002                                     [R02_GEO_MISMATCH, R03_ODD_HOUR, R08_HIGH_RISK_MCC]
81486  TX_0000000003                                     [R02_GEO_MISMATCH, R03_ODD_HOUR, R08_HIGH_RISK_MCC]
81487  TX_0000000004                                     [R02_GEO_MISMATCH, R03_ODD_HOUR, R08_HIGH_RISK_MCC]
81488  TX_0000000005  [R02_GEO_MISMATCH, R03_ODD_HOUR, R04_FAILED_ATTEMPTS, R07_VELOCITY, R08_HIGH_RISK_MCC]
```

### Results

| Code | Payments | Share |
|---|---:|---:|
| R02_GEO_MISMATCH | 90,293 | 82.1% |
| R08_HIGH_RISK_MCC | 32,602 | 29.6% |
| R03_ODD_HOUR | 15,438 | 14.0% |
| R07_VELOCITY | 14,509 | 13.2% |
| R04_FAILED_ATTEMPTS | 9,877 | 9.0% |
| R01_NEW_DEVICE | 7,305 | 6.6% |
| R05_AMOUNT_SPIKE | 3,068 | 2.8% |
| R06_NEW_ACCOUNT | 1,109 | 1.0% |

- The count for every code is **the same as in the client's `features` table**. Totals can agree
  by chance, so Step 5 checks the codes payment by payment.
- **R02 fires on 82% of payments**, because most customers pay merchants in other cities more
  than 500 km away. A code that is on almost every payment tells an investigator very little;
  the 500 km threshold may be worth reviewing with the client.
- **11,957 payments (10.9%) have no code at all.** Most payments have one or two codes, and the
  most any payment has is seven.

### Worked example: the failure rule in action
The same customer as in Step 3. The outcomes of their first five payments:

```
TX_1  FAILED    (outcome at 18:35:16 UTC)
TX_2  FAILED    (outcome at 18:36:11)
TX_3  SUCCESS
TX_4  FAILED    (outcome at 18:38:20)
TX_5  starts at 18:39:15  -> 3 failure outcomes already arrived -> R04
```

TX_4 sees only 2 failures, because its own failure has not happened yet, so it gets no R04;
TX_5 sees 3 and gets R04. TX_5 also gets R07, as the 5th payment within an hour (4 earlier ones).
TX_1 has no R02 because its customer location is unknown: unknown gives no code.

---

## Step 5 - Compare with the client's features table

### Why compare
The client says the `features` table was built from the raw tables with the documented rules. The
fraud model will learn from that table, so it can't be taken on trust: if a feature secretly used
future data, or a threshold differed from the documentation, the model would look good in testing
and fail on real payments. Steps 3 and 4 rebuilt the features and codes independently from the raw
data; this step puts our values next to the client's, **payment by payment**, and counts how often
they agree.

### How the comparison works
Both tables are joined on `transaction_id`, so every payment has our value and the client's value
side by side (columns ending in `_ours` and `_client`). For each feature, a payment **agrees** if:

- the two values are the same, **or**
- both are empty (both say "unknown", e.g. no device).

One value empty and the other not is a mismatch. Values are compared as plain Python values,
because our True/False columns use pandas' `"boolean"` type while the client's use True, False and
None.

**Rounding.** The client stores `amount_to_avg_ratio` with 4 decimals and
`customer_merchant_distance_km` with 2; our values keep full precision. Two match rates are
reported for every feature, so the effect of rounding is shown openly, not hidden:

- **exact**: same with no rounding at all;
- **rounded**: same after rounding our value to the client's number of decimals.

**Reason codes** are compared per code (did both give this code to the same payments?) and as a
whole list (identical codes in the same order).

**A test of the test.** A 100% match could also come from a broken comparison that always says
"same". To rule this out, one feature is computed wrongly on purpose (`is_night` from the UTC
hour, not the Indian hour) and compared too. If the check works, its match rate must drop.

### Run it
```bash
python pipeline/compare.py
```

Output:
```
Payments compared: 110,000

1. Match rate per feature
 feature                            exact  rounded  mismatches
 amount_to_avg_ratio                2.58%  100.00%           0
 is_new_device                    100.00%  100.00%           0
 customer_merchant_distance_km      8.90%  100.00%           0
 is_new_city                      100.00%  100.00%           0
 hour_of_day                      100.00%  100.00%           0
 is_night                         100.00%  100.00%           0
 has_recent_failures              100.00%  100.00%           0
 is_new_account                   100.00%  100.00%           0
 txn_count_last_1h                100.00%  100.00%           0
 txn_amount_last_24h_paise        100.00%  100.00%           0

2. Match rate per reason code
 R01_NEW_DEVICE          100.00%   ours  7,305   client  7,305
 R02_GEO_MISMATCH        100.00%   ours 90,293   client 90,293
 R03_ODD_HOUR            100.00%   ours 15,438   client 15,438
 R04_FAILED_ATTEMPTS     100.00%   ours  9,877   client  9,877
 R05_AMOUNT_SPIKE        100.00%   ours  3,068   client  3,068
 R06_NEW_ACCOUNT         100.00%   ours  1,109   client  1,109
 R07_VELOCITY            100.00%   ours 14,509   client 14,509
 R08_HIGH_RISK_MCC       100.00%   ours 32,602   client 32,602
 whole list identical    100.00%   (0 payments differ)

3. Why 'exact' is lower for two features: the client rounds
transaction_id  amount_to_avg_ratio_ours  amount_to_avg_ratio_client  customer_merchant_distance_km_ours  customer_merchant_distance_km_client
 TX_0000000002                  2.935044                      2.9350                          845.377592                                845.38
 TX_0000000003                  0.728459                      0.7285                          845.377592                                845.38
 TX_0000000004                  0.229932                      0.2299                          845.377592                                845.38

4. Can the check catch a mistake? is_night computed in UTC instead of Indian time
 match rate: 63.44%
```

### Match rate per feature

| Feature | Exact | After rounding | Mismatches |
|---|---:|---:|---:|
| `amount_to_avg_ratio` | 2.58% | 100% | 0 |
| `is_new_device` | 100% | 100% | 0 |
| `customer_merchant_distance_km` | 8.90% | 100% | 0 |
| `is_new_city` | 100% | 100% | 0 |
| `hour_of_day` | 100% | 100% | 0 |
| `is_night` | 100% | 100% | 0 |
| `has_recent_failures` | 100% | 100% | 0 |
| `is_new_account` | 100% | 100% | 0 |
| `txn_count_last_1h` | 100% | 100% | 0 |
| `txn_amount_last_24h_paise` | 100% | 100% | 0 |
| **Reason codes (whole list)** | **100%** | | **0** |

Every one of the 8 reason codes was given to exactly the same payments in both tables, not just
the same number of payments.

### Every mismatch explained
The only differences are in the **exact** column for two features, and both have the same cause:
**the client rounds.**

| Feature | Exact mismatches | Cause | Example (ours -> client) |
|---|---:|---|---|
| `amount_to_avg_ratio` | 107,167 (97.4%) | client keeps 4 decimals | 2.935044 -> 2.9350 |
| `customer_merchant_distance_km` | 100,205 (91.1%) | client keeps 2 decimals | 845.377592 -> 845.38 |

These are the same numbers written with fewer decimals, not different calculations: after
rounding our values the same way, **0 mismatches remain**. The few values that match exactly are
the ones rounding can't change:

- ratio: 2,833 exact matches = 2,829 payments where both are empty + 4 values with no extra decimals;
- distance: 9,795 exact matches = 3,257 payments where both are empty + 6,538 distances of exactly
  0 km (customer and merchant in the same city).

No other feature and no reason code has any mismatch.

### The check can catch a mistake
`is_night` computed from the **UTC** hour, a realistic bug, matches the client on only
**63.44%** of payments. UTC is 5 hours 30 minutes behind India, so a payment at 00:05 in India
(18:35 UTC) is wrongly marked "not night" and one at 05:30 in India (00:00 UTC) wrongly marked
"night". The comparison catches it immediately, so the 100% results above are real and not a
side effect of a broken check.

### What the result means
- The client's `features` table **follows its documented rules** for everything rebuilt here: only
  earlier payments are used, the current payment is excluded, failures count only after their
  outcome arrived, unknown values stay unknown, and night uses Indian time. **No leakage was
  found.**
- Failed attempts are counted in the averages and velocity features, as the catalogue says
  ("prior authorisation attempts, including declines").
- These columns are safe to use for training a model, as far as their definitions go.

### Limits
- **Scope.** The 10 features the task asked for, the three extra features the codes need and the
  reason codes were checked. Other columns in the client's table (`mcc_target_encoded_rate`,
  `distinct_customers_per_device_7d`, `combined_risk_flags`, `cold_start` and the missing-value
  flags) were not rebuilt, so they are **not verified**.
- **Correct is not the same as useful.** The rules are applied exactly as documented, but
  `R02_GEO_MISMATCH` fires on 82% of payments, because most customers pay merchants more than
  500 km away. A code on almost every payment gives an investigator little information; the
  500 km threshold is worth reviewing with the client.
- **The client's precomputed columns in `transactions` are a separate issue.**
  `previous_transactions` and `average_transaction_value` contradict each other in 10,523 rows
  (Step 2). They were not used to build any feature, and they should not be fed to a model as
  they are.

---

## Summary

| Step | Result |
|---|---|
| 1 | 7 tables loaded from Supabase into pandas and cached locally (110,000 payments) |
| 2 | Clean data: no duplicates or broken values; dates stored as text; real gaps in location (3,257) and device (1,138); 1,396 amount outliers kept (11.4% fraud vs 0.6%) |
| 3 | 7 features rebuilt with time windows that end just before each payment |
| 4 | 3 extra features (new city, failures known in the previous 24 h, account age) and reason codes R01 to R08, thresholds sourced from the client document and the training files |
| 5 | **100% match** with the client's table for every feature and every reason code after rounding; the only differences are 4- and 2-decimal rounding; a deliberate UTC bug drops to 63%, proving the check works |

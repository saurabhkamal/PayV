"""Step 4: three fraud-hunting Cypher queries on the PayV graph."""

from db import get_driver      # helper from db.py: the Neo4j connection

# Query 1: devices used by 3+ different customers within 7 days
SHARED_IN_7_DAYS = """
// find every payment made by a customer who used device d
MATCH (d:Device)<-[:USED_DEVICE]-(:Customer)-[p:PAID]->()
// keep only payments really made ON this device (not on the customer's other devices)
WHERE p.device_id = d.device_id
// each such payment's time becomes a possible start of a 7-day window
WITH d, p.time AS start
// look again at all payments on the same device, now with the customer who made them
MATCH (d)<-[:USED_DEVICE]-(c:Customer)-[p2:PAID]->()
// again only payments made on this device
WHERE p2.device_id = d.device_id
// ...and only those from the start time up to 7 days later
  AND p2.time >= start AND p2.time < start + duration({days: 7})
// per window: the list of different customers (one customer paying 10 times counts once)
WITH d, start, collect(DISTINCT c.customer_id) AS customers
// keep only windows with 3 or more different customers
WHERE size(customers) >= 3
// sort the windows by start time, oldest first
WITH d, start, customers ORDER BY start
// per device, put its windows in a list and take the first (earliest) one
WITH d, collect({start: start, customers: customers})[0] AS first
// show the device, its kind, when the window started and which customers were in it
RETURN d.device_id AS device, d.device_kind AS kind,
       first.start AS window_start, first.customers AS customers
// oldest window first
ORDER BY window_start
"""

# Query 2: customers within 2 hops of a fraud-labelled payment
# hop 1: fraud payment -> the device it was made on; hop 2: device -> other customers who used it
NEAR_FRAUD = """
// find every fraud payment and the customer who made it
MATCH (payer:Customer)-[p:PAID {fraud_label: 1}]->(:Merchant)
// hop 1: go to the device the payment was made on;
// hop 2: go to every customer who used that device
MATCH (d:Device {device_id: p.device_id})<-[:USED_DEVICE]-(other:Customer)
// skip the payer: we want the OTHER customers around them
WHERE other <> payer
// skip the payer: we want the OTHER customers around them
WITH other, count(DISTINCT p) AS linked_fraud
// look for their own fraud payments; OPTIONAL keeps the customer even if none are found
OPTIONAL MATCH (other)-[own:PAID {fraud_label: 1}]->()
// count their own fraud payments (0 if none)
WITH other, linked_fraud, count(own) AS own_fraud
// show the customer, their city and both counts
RETURN other.customer_id AS customer, other.home_city AS city, linked_fraud, own_fraud
// most linked first; customer id breaks ties so the order is the same every run
ORDER BY linked_fraud DESC, customer
"""

# Query 3: merchants most often paid from shared devices (used by 3+ customers)
MERCHANTS_FROM_SHARED = """
// for every device, find the customers who used it
MATCH (d:Device)<-[:USED_DEVICE]-(:Customer)
// count customers per device and keep devices with 3 or more = shared devices
WITH d, count(*) AS users WHERE users >= 3
// put all shared device ids into one list called shared
WITH COLLECT(d.device_id) AS shared
// find every payment and the merchant it went to
MATCH (:Customer)-[p:PAID]->(m:Merchant)
// keep only payments made on one of the shared devices
WHERE p.device_id IN shared
// per merchant: payments from shared devices, how many were fraud (labels are 0/1), how many devices
RETURN m.name AS merchant, m.category AS category, count(p) AS payments,
       sum(p.fraud_label) AS fraud, count(DISTINCT p.device_id) AS devices
// most payments first
ORDER BY payments DESC
// top 10 merchants only
LIMIT 10
"""

with get_driver() as driver:    # open the Neo4j connection; closed automatically at the end
    print("Query 1: devices used by 3+ customers within 7 days")
    for row in driver.execute_query(SHARED_IN_7_DAYS).records:    # one row per device
        device = row["device"]      
        kind = row["kind"]
        start = row["window_start"].to_native()     # Neo4j date-time -> Python datetime
        customers = ", ".join(row["customers"])     # list -> "C_1, C_2, C_3"
        print(f" {device} ({kind}): from {start:%Y-%m-%d %H:%M} UTC -> {customers}") 

    print("\nQuery 2: customers within 2 hops of a fraud-labelled payment")
    near = driver.execute_query(NEAR_FRAUD).records    # all reached customers
    hidden = [row for row in near if row["own_fraud"] == 0]    # those with no fraud of their own
    print(f" {len(near)} customers reached, {len(hidden)} have no fraud of their own")
    for row in near[:10]:
        customer = row["customer"]
        city = row["city"]
        linked = row["linked_fraud"]
        own = row["own_fraud"]
        print(f" {customer} ({city}): linked to {linked} fraud payments, own fraud: {own}")
    
    print("\nQuery 3: merchants most often paid from shared devices")
    for row in driver.execute_query(MERCHANTS_FROM_SHARED).records:    # one row per merchant
        merchant = row["merchant"]
        category = row["category"]
        payments = row["payments"]
        devices = row["devices"]
        fraud = row["fraud"]
        print(f" {merchant} ({category}): {payments} payments from {devices} shared devices, {fraud} fraud")
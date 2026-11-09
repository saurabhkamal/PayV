"""Step 3: prove that MERGE and the uniqueness constraints stop duplicates."""
from neo4j.exceptions import ConstraintError

from db import get_driver

CUSTOMER = "C_f9b5b518b79a7647"   # a customer that is already in the graph
PAYMENT = "TX_0000000826"         # a payment (PAID arrow) that is already in the graph

with get_driver() as driver:

    # A. which constraints exist?
    print("A. Constraints in the database")
    constraints = driver.execute_query(
        "SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties").records
    for row in constraints:
        print(f" {row['name']}: {row['type']} on {row['labelsOrTypes'][0]}.{row['properties'][0]}")

    # B1. MERGE an existing customer -> should find it, create nothing
    print("\nB1. MERGE a customer that already exists")
    summary = driver.execute_query(
        "MERGE (c:Customer {customer_id: $id})", id=CUSTOMER).summary
    print(f" nodes created: {summary.counters.nodes_created}"
    )

    # B2. CREATE the same customer -> the constraint should refuse it
    print("\nB2. CREATE the same customer again")
    try:
        driver.execute_query("CREATE(c:Customer {customer_id: $id})", id=CUSTOMER)
        print(" created a duplicate (the constraint is missing)")
    except ConstraintError as error:
        print(" refused:", error.message.splitlines()[0])

    #B3. CREATE a second paid arrow with an existing transaction_id -> also refused
    print("\nB3. CREATE a payment with an existing transaction_id")
    try:
        driver.execute_query("""
            MATCH (c:Customer {customer_id: $customer})
            MATCH (m:Merchant) WITH c, m limit 1
            CREATE (c)-[:PAID {transaction_id: $tx}]->(m)
        """, customer=CUSTOMER, tx=PAYMENT)
        print("  created a duplicate (the constraint is missing!)")
    except ConstraintError as error:
        print(" refused:", error.message.splitlines()[0])

    # Final check: still exactly one of each
    customers = driver.execute_query(
        "MATCH (c:Customer {customer_id: $id}) RETURN count(c) AS n", id=CUSTOMER).records[0]["n"]
    payments = driver.execute_query(
        "MATCH ()-[p:PAID {transaction_id: $tx}]->() RETURN count(p) AS n", tx=PAYMENT).records[0]["n"]
    print(f"\nCustomer {CUSTOMER} exists {customers} time(s)")
    print(f"payment {PAYMENT} exists {payments} time(s)")
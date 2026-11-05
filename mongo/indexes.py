"""Step 5: indexes on customer_id and transaction_time, explain() before and after."""
import os

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient

load_dotenv()
tx = MongoClient(os.environ["MONGODB_URI"])["payv"].transactions

QUERY = {"customer_id": "C_09768e467feed4a5"}     # one customer, 48 transactions



def stages(plan):
    """Stage names of a query plan, outermost first, e.g. ['FETCH', 'IXSCAN']."""
    names = []                          # empty list to collect the stage names
    while plan is not None:             # keep going while there is a box to look at
        names.append(plan["stage"])     # write down this box's name
        plan = plan.get("inputStage")   # move to the box inside (None if there isn't one)
    return names



def show(label):
    """Run explain() on QUERY and print the important numbers."""
    e = tx.find(QUERY).explain()
    s = e["executionStats"]
    print(label)
    print("  plan:          ", " -> ".join(stages(e["queryPlanner"]["winningPlan"])))
    print("  returned:      ", s["nReturned"])
    print("  keys examined: ", s["totalKeysExamined"])
    print("  docs examined: ", s["totalDocsExamined"])
    print("  time (ms):     ", s["executionTimeMillis"])


# 1. Remove our indexes so "before" is a true before (the _id index is never removed)
tx.drop_indexes()
show("BEFORE indexes")

# 2. Create the two indexes 
print("created:", tx.create_index([("customer_id", ASCENDING)]))
print("created:", tx.create_index([("transaction_time", ASCENDING)]))

# 3. The same query again
show("AFTER indexes")
print("indexes now:", list(tx.index_information()))
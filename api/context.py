"""Part 2: collect the facts about one transaction from Supabase, Neo4j and Qdrant."""

import os                               # reads settings from the environment
from dotenv import load_dotenv          # loads the .env file
from supabase import create_client      # Supabase client
from graph.db import get_driver         # Neo4j connection helper
from vectors.db import get_client       # Qdrant connection helper
from vectors.embed import embed         # Gemini Embedding 2 function

load_dotenv()                           # put the keys from .env into os.environ

# connect to the three databases once, when the API starts
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
neo4j_driver = get_driver()
qdrant = get_client()


# ---------- 1. Supabase: the transaction and its features ----------
def get_transaction(transaction_id: str) -> dict | None:
    """Return the transaction and its features, or None if the ID does not exist."""
    tx = sb.table("transactions").select("*").eq("transaction_id", transaction_id).execute().data
    if not tx:
        return None
    features = sb.table("features").select("*").eq("transaction_id", transaction_id).execute().data
    return{"transaction": tx[0], "features": features[0] if features else None}



# ---------- 2. Neo4j: who else used this payment's device ----------
SHARED_DEVICE_QUERY = """
MATCH (other:Customer)-[u:USED_DEVICE]->(d:Device {device_id: $device_id})
WHERE other.customer_id <> $customer_id AND u.first_seen < datetime($before)
OPTIONAL MATCH (other)-[p:PAID {fraud_label: 1}]->()
WHERE p.time < datetime($before)
RETURN other.customer_id AS customer_id, count(p) > 0 AS had_fraud_before
"""
# line 1: find every customer who used this device
# line 2: but not the customer making this payment and only those who used the device before this payment
# line 3-4: look for their fraud payments that happened BEFORE this payment (no peeking at the future)
# line 5: one row per other customer: their ID, and true/false for earlier fraud

def get_neighbourhood(customer_id: str, device_id: str | None, before: str) -> dict:
    """Return the other customers who share this device, and whether they had fraud earlier."""
    if device_id is None:                                         # some payments have no device
        return {"device_in_graph": False, "shared_with": []}      # nothing to look up, so return an empty answer
    with neo4j_driver.session() as session:                       # open a Neo4j session
        in_graph = session.run(                                  # run a small check query
            "MATCH (d:Device {device_id: $id}) RETURN count(d) > 0 AS found",   # true if this device exists in the graph
            id=device_id,                                        
        ).single()["found"]         
        rows = session.run(              # run the shared-device query defined above
            SHARED_DEVICE_QUERY,
            device_id=device_id,
            customer_id=customer_id,    # the device to look at
            before=before,              # only count fraud that happened before this time
        ).data()
    return {"device_in_graph": in_graph, "shared_with": rows}   # was the device found, and who else used it


# ---------- 3. Qdrant: the policy chunks that match the reason codes ----------
def get_policy_chunks(reason_codes: list[str], top_k: int = 5) -> list[dict]:
    """Search the corpus with the reason codes and return the closest chunks"""
    codes_text = ", ".join(reason_codes) or "no risk flags"          # Reason codes or "no risk flags" if the list is empty
    question = "Investigator guidance for a payment flagged: " + codes_text       # the search question sent to Qdrant
    points = qdrant.query_points(                          # ask Qdrant for the chunks closest in meaning
        collection_name="payv_corpus",                     # the collection built in vectors/upload.py
        query=embed(question),                             # the question turned into 3,072 numbers
        limit=top_k,                                       # chunks to return (5 by default)
        with_payload=True,                                 # also return each chunk's source, number and text
    ).points                                               # the list of matching chunks, best match first
    results = []                                # start with an empty list
    for p in points:                            # take each chunk Qdrant returned, one at a time, and call it p
        results.append({                        # make a small dict for this chunk and add it to the list
            "document": p.payload["source"],    # which document the chunk came from
            "chunk": p.payload["chunk"],        # the chunk's number inside that document
            "score": round(p.score, 3),         # cosine similarity, 3 decimals
            "text": p.payload["text"],          # the chunk text the LLM will read
        })                                      # close the dict and the append() call
    return results                              # give back the full list (5 dicts by default)
        
# ---------- all together ----------
def build_context(transaction_id: str) -> dict | None:
    """Collect the full context for one transaction, or None if it does not exist."""
    record = get_transaction(transaction_id)       # 1. Supabase
    if record is None:                             # transaction ID not found
        return None
    tx = record["transaction"]                     # the transaction row
    reason_codes = record["features"]["reason_codes"] if record["features"] else []   # the codes that fired, or an empty list if there are no features
    return {
        "transaction": tx,                         # the payment details from Supabase
        "features": record["features"],            # the computed features from Supabase (incl. reason codes)
        "neighbourhood": get_neighbourhood(tx["customer_id"], tx["device_id"],    # who else used this payment's device
                                           tx["transaction_time"]),   # 2. Neo4j
        "policy_chunks": get_policy_chunks(reason_codes),             # the matching policy text from Qdrant
    }
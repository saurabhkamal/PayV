"""Step 1: connect to Neo4j Aura and check the connection."""
from db import get_driver

with get_driver() as driver:
    driver.verify_connectivity()
    info = driver.get_server_info()
    print("Connected to Neo4j at", info.address)
    print("Server version:", info.agent)

    records, summary, keys = driver.execute_query("RETURN 'hello graph' AS msg")
    print("Test query says:", records[0]["msg"])

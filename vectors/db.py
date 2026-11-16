"""Connect to Qdrant Cloud and run a health check."""

import os

from dotenv import load_dotenv          # reads the .env file
from qdrant_client import QdrantClient   # Qdrant Python client

load_dotenv()    # put QDRANT_URL and QDRANT_API_KEY into os.environ

def get_client() -> QdrantClient:
    """Return a connected Qdrant client."""
    return QdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ["QDRANT_API_KEY"],
        timeout=60,     # embedding uploads can be slow; wait up to 60s
    )

if __name__ == "__main__":
    client = get_client()
    collections = client.get_collections()   # health check: ask for the list of collections
    names = [c.name for c in collections.collections]
    print("Connected to Qdrant. Collections:", names)
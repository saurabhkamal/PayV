"""Step 3: turn every chunk into a vector of 3,072 numbers with Gemini Embedding 2"""

import json                      # reads chunks and writes vectors as JSON lines
import os                        # reads the API key from the environment
import time                      # waits before retrying when the API says "slow down"
from pathlib import Path         # handles file paths

import requests                  # sends HTTP requests to the API (gateway)
from dotenv import load_dotenv   # reads the .env file

load_dotenv()                    

EURI_URL = "https://api.euron.one/api/v1/euri/embeddings"   # embeddings endpoint
MODEL = "gemini-embedding-2-preview"                                
DIMENSIONS = 3072                                           # Gemini Embedding 2 returns 3,072 numbers
IN_FILE = Path("vectors/cache/chunks.jsonl")                # input: chunks from Step 2
OUT_FILE = Path("vectors/cache/embeddings.jsonl")           # output: chunks + their vectors

def embed(text: str) -> list[float]:
    """Send one text to embedding API and return its vector."""
    for attempt in range(5):                                # try up to 5 times
        response = requests.post(
            EURI_URL,
            headers={"Authorization": f"Bearer {os.environ['EURI_API_KEY']}"},  # proves who we are
            json={"model": MODEL, "input": text},           # what to embed, and with which model
            timeout=60,                                     # give up on one request after 60 s
        )
        if response.status_code == 429:                     # 429 = too many requests
            time.sleep(2 ** attempt)                        # wait 1, 2, 4, 8, 16 s, then retry
            continue
        response.raise_for_status()                         # stop with an error for any other problem
        return response.json()["data"][0]["embedding"]      # the list of numbers
    raise RuntimeError("Embedding API kept answering 429 (rate limit); try again later")

def main() -> None:
    chunks = [json.loads(line) for line in IN_FILE.open(encoding="utf-8")]    # Read every chunk from prepare.py into a json
    start = sum(1 for _ in OUT_FILE.open(encoding="utf-8")) if OUT_FILE.exists() else 0    # counting how many chunks are done.

    # Open the file in "append" mode: new lines go at the end, old line are kept
    with OUT_FILE.open("a", encoding="utf-8") as out:
        for i in range(start, len(chunks)):
            vector = embed(chunks[i]["text"])    # Send the chunk's text to the embedding API and get back its 3,072 numbers.

            if len(vector) != DIMENSIONS:     # stop if we didn't get exactly 3072 numbers (wrong model)
                raise ValueError(f"Expected {DIMENSIONS} numbers, got {len(vector)}")

            out.write(json.dumps({"id": i, **chunks[i], "vector": vector}) + "\n")
            # Save one line: the chunk's id, all its fields (source, title, doc_type, chunk, text) and vectors

            print(f"{i + 1}/{len(chunks)} embedded", end="\r") 

    print(f"\nDone: {len(chunks)} chunks embedded, saved to {OUT_FILE}")

if __name__ == "__main__":
    main()


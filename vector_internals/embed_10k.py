"""Step 5b: embed the 10,000 texts in batches and save them as one NumPy file."""

import json                      # reads the texts file
import os                        # reads the API key from the environment
import time                      # waits before retrying
from pathlib import Path         # handles file paths

import numpy as np               # saves the vectors as .npy files
import requests                  # sends the requests to EURI

from vectors.embed import EURI_URL, MODEL

IN_FILE = Path("vector_internals/cache/texts_10k.jsonl")     # the 10,000 texts from Step 5a
BATCH_DIR = Path("vector_internals/cache/batches")           # one .npy file per finished batch
OUT_FILE = Path("vector_internals/cache/vectors_10k.npy")    # final file: 10,000 rows x 3,072 numbers
BATCH_SIZE = 50                                              # texts per request


def embed_batch(texts):
    """Embed a list of texts in one request. Returns (vectors, tokens used)."""
    for attempt in range(5):                                                   # try up to 5 times (attempt = 0, 1, 2, 3, 4)
        response = requests.post(EURI_URL, timeout=120,                        # send the request; give up after 120 s
                                 headers={"Authorization": f"Bearer {os.environ['EURI_API_KEY']}"},  
                                 json={"model": MODEL, "input": texts})        # the model + the list of texts to embed
        if response.status_code == 429:                                        # too many requests
            time.sleep(2 ** attempt)                                           # yes: wait 1, 2, 4, 8 or 16 seconds
            continue                                                           # and try again
        response.raise_for_status()                                            # any other error (wrong key, bad model) stops the script
        reply = response.json()                                                # turn the reply text into a Python dictionary
        vectors = np.array([item["embedding"] for item in reply["data"]], dtype=np.float32)   # take every vector out and stack them into one array
        assert vectors.shape == (len(texts), 3072), f"unexpected shape {vectors.shape}"   # check: one vector of 3,072 numbers per text
        return vectors, reply["usage"]["total_tokens"]                         # hand back the vectors and the tokens counted
    raise RuntimeError("Still rate-limited after 5 tries; run again later (finished batches are kept)")   # all 5 tries got 429: give up

def main() -> None:
    texts = [json.loads(line)["text"] for line in IN_FILE.open(encoding="utf-8")]   # read all 10,000 texts, in id order
    BATCH_DIR.mkdir(parents=True, exist_ok=True)                                    # create the batches folder if it doesn't exist
    starts = range(0, len(texts), BATCH_SIZE)                                       # where each batch starts: 0, 50, 100, ... 9,950
    tokens = 0                                                                      # running total of tokens used in this run


    for start in starts:                                                            # go through the batches one by one
        batch_file = BATCH_DIR / f"batch_{start:05d}.npy"                           # this batch's file name, e.g. batch_00050.npy
        if batch_file.exists():                                                     # already saved in an earlier run?
            continue                                                                # yes: skip it (this is the resume)
        vectors, used = embed_batch(texts[start:start + BATCH_SIZE])                # embed the next 50 texts
        np.save(batch_file, vectors)                                                # save this batch straight away
        tokens += used                                                              # add its tokens to the running total
        print(f"{start + len(vectors):,}/{len(texts):,} embedded   tokens: {tokens:,}", end="\r")   # progress on one updating line

    all_vectors = np.vstack([np.load(BATCH_DIR / f"batch_{s:05d}.npy") for s in starts])   # load every batch file, in order, and stack them
    np.save(OUT_FILE, all_vectors)                                                         # save the 10,000 × 3,072 matrix as one file
    print(f"\nDone: {all_vectors.shape} saved to {OUT_FILE}")                             # final message, e.g. (10000, 3072)


if __name__ == "__main__":     # run main() only when the file is run directly
    main()
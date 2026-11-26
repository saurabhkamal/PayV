"""Step 5a: collect 10,000 unique texts - every corpus chunk, topped up with training prompts."""

import json                      # writes the output file
import random                    # shuffles the final list
from collections import Counter  # counts how many texts of each kind
from pathlib import Path         # handles file paths

import pandas as pd              # reads the compressed .jsonl.gz files

from vectors.prepare import clean, splitter   # same cleaning and chunking as the semantic search task

TARGET = 10_000                                           
OUT_FILE = Path("vector_internals/cache/texts_10k.jsonl")

def read_all(folder):
    """Read every .jsonl.gz file in the folder pattern into one table (sorted in same order every run)."""
    files = sorted(Path(".").glob(folder))
    return pd.concat([pd.read_json(f, lines=True) for f in files], ignore_index=True)      # read each file and stack them into one table


def main() -> None:
    records, seen = [], set()     # records is texts collected so far; seen = to skip duplicates

    # 1. Every chunk of every corpus document (all types, all splits) - gives 8,058 unique chunks.
    for doc in read_all("data/corpus/*/*/*.jsonl.gz").to_dict("records"):   # go through every corpus document, one at a time
        for chunk in splitter.split_text(clean(doc["content"])):            # clean its text and cut it into chunks
            if chunk not in seen:                                            
                seen.add(chunk)                                              
                records.append({"source": doc["document_id"], "kind": doc["kind"], "text": chunk})   # keep it, with its labels


     # 2. Top up with training prompts until we have 10,000.
    for row in read_all("data/training/sft/train/*.jsonl.gz").to_dict("records"):   # go through the training prompts
        if len(records) == TARGET:                # if already have 10,000
            break                                 # then, yes: stop reading
        if row["prompt"] not in seen:             
            seen.add(row["prompt"])               
            records.append({"source": row["example_id"], "kind": "sft_prompt", "text": row["prompt"]})   # labelled as a training prompt

    # 3. Shuffle, so the first 1,000 (used for the small test) are a mix of all kinds.
    random.Random(42).shuffle(records)            # mix the order; seed 42 gives the same order every run

    # 4. Save one text per line, each with an id (0 ... 9,999).
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)               # create vector_internals/cache/ if it doesn't exist
    with OUT_FILE.open("w", encoding="utf-8") as out:                # open the output file for writing (replaces any old one)
        for i, record in enumerate(records):                         # go through the records, numbering them 0, 1, 2 ...
            out.write(json.dumps({"id": i, **record}, ensure_ascii=False) + "\n")   # write the id + source, kind, text as one line
            # ensure_ascii=False keeps characters like ₹ readable in the file instead of writing them as codes like \u20b9

    tokens = sum(len(r["text"]) for r in records) // 4                      # rough token estimate: total characters ÷ 4
    print(f"{len(records):,} texts saved to {OUT_FILE}  (≈ {tokens:,} tokens)")   # how many texts, where, and roughly how many tokens
    print("All 10,000:", dict(Counter(r["kind"] for r in records)))               # how many of each kind, across all 10,000
    print("First 1,000:", dict(Counter(r["kind"] for r in records[:1000])))       # how many of each kind in the first 1,000 (the small test)


if __name__ == "__main__":     # run main() only when the file is run directly
    main()



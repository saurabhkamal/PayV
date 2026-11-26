"""Step 2: load documents, clean them, split them into chunks, save to a file."""

import gzip                 # opens the compressed .jsonl.gz files
import json                 # turns each text line into a Python dict (and back)
import random               # picks a random sample of documents
import re                   # finds and replaces text patterns (cleaning, sentence splitting)
from pathlib import Path    # handles file and folder paths easily
import pandas as pd 
from langchain_text_splitters import RecursiveCharacterTextSplitter



CORPUS_DIR = Path("data/corpus")          # one folder per document type
OUT_FILE = Path("vectors/cache/chunks.jsonl")   # file where the finished chunks are saved (one chunk per line)
DOCS_PER_TYPE = 60   # take at most 60 documents from each type (types with fewer are taken whole)
CHUNK_SIZE = 800                            # max characters per chunk (≈ 200 tokens, using 1 token ≈ 4 characters)
CHUNK_OVERLAP = 150                        # characters repeated from the previous chunk

# The disclaimer paragraph that starts every document (same text everywhere).
DISCLAIMER = re.compile(r"SYNTHETIC TRAINING MATERIAL\..*?production model output\.", re.S)

def load_documents() -> list[dict]:
    """Read the train split of every document type and pick a sample."""
    files = CORPUS_DIR.glob("*/train/*.jsonl.gz")                             # every type's train files
    df = pd.concat([pd.read_json(f, lines=True) for f in files], ignore_index=True)  # read all files into one table
    df = df.sample(frac=1, random_state=42)                                   # shuffle all rows (seed 42 = same order every run)
    df = df.groupby("kind").head(DOCS_PER_TYPE)                               # keep the first 60 of each type (all, if fewer)
    return df.to_dict("records")                                              # table -> list of dicts, like before

def clean(text: str) -> str:
    """Remove the disclaimer, markdown '#' marks and extra spaces/blank lines."""
    text = DISCLAIMER.sub("", text)                    # drop the repeated disclaimer
    text = re.sub(r"^#+\s*", "", text, flags=re.M)     # "## Purpose" -> "Purpose"
    text = re.sub(r"[ \t]+", " ", text)                # many spaces -> one space
    text = re.sub(r"\n{2,}", "\n", text)               # many blank lines -> one line break
    return text.strip()

def split_sentences(text: str) -> list[str]:
    """Cut text after . ! ? or at a line break; drop empty pieces."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


# One splitter, built once and reused for every document.
splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,                 # max 800 characters per chunk
    chunk_overlap=CHUNK_OVERLAP,           # repeat up to 150 characters from the previous chunk
    separators=["\n", ". ", " ", ""],      # cut at line breaks first, then sentence ends, then spaces
)

def main() -> None:
    docs = load_documents()                                   # the 245 sampled documents
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)        # create vectors/cache/ if it doesn't exist
    n_chunks = 0                                              # counts the chunks written
    seen = set()                                              # chunk texts already saved
    with OUT_FILE.open("w", encoding="utf-8") as out:         # open the output file for writing
        for doc in docs:                                      # go through each document
            for i, chunk in enumerate(splitter.split_text(clean(doc["content"]))):   # clean the text, then split it into chunks
                if chunk in seen:                             # same text already saved from another document
                    continue                                  # skip the duplicate
                seen.add(chunk)
                record = {
                    "source": doc["document_id"],             # which document it came from
                    "title": doc["title"],                    # the document's title
                    "doc_type": doc["kind"],                  # e.g. "playbooks"
                    "chunk": i,                               # chunk number inside the document (0, 1, 2 ...)
                    "text": chunk,                            # the chunk text itself
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")   # one chunk per line
                n_chunks += 1                                 # count it
    print(f"{len(docs)} documents -> {n_chunks} chunks, saved to {OUT_FILE}")


if __name__ == "__main__":     # run main() only when the file is run directly
    main()


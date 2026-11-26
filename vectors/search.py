"""Step 5: search the corpus by meaning, with and without a payload filter."""

from qdrant_client.models import FieldCondition, Filter, MatchValue   # building blocks for a filter
from vectors.db import get_client 
from vectors.embed import embed        # same embedding function

COLLECTION = "payv_corpus"
TOP_K = 5                              # how many results to show per question

# 10 natural-language questions, written the way an investigator would ask them.

QUESTIONS = [
    "What should an investigator check when a new device makes a large payment?",
    "How should a duplicate debit complaint be handled?",
    "Is a declined payment proof of fraud?",
    "When does the final fraud label become available?",
    "How do I write up the evidence in a case note?",
    "What does an unusual city or a long distance from the merchant tell us?",
    "A customer says they did not authorise a payment made late at night",
    "Which notes are allowed in continued pretraining?",
    "How should a reviewer treat missing device or location information?",
    "What does the risk-based authentication guidance say?",
]

def search(question: str, doc_type: str | None = None) -> None:
    """Embed the question, find the TOP_K closest chunks, print them with scores."""
    query_filter = None                                          # no filter: search all document types
    if doc_type:                                                 # filter: only points whose doc_type matches exactly
        query_filter = Filter(must=[FieldCondition(key="doc_type", match=MatchValue(value=doc_type))])

    results = get_client().query_points(
        collection_name=COLLECTION,
        query=embed(question),                                   # question -> 3,072 numbers
        query_filter=query_filter,                               # None, or the doc_type filter
        limit=TOP_K,                                             # top 5
        with_payload=True,                                       # also return source, doc_type, text ...
    ).points

    label = f"  [filter: doc_type = {doc_type}]" if doc_type else ""
    print(f"\nQ: {question}{label}")
    print(f" #  score  {'doc_type':<22} {'source':<36} chunk  text")
    for rank, point in enumerate(results, start=1):              
        p = point.payload                                        
        preview = p["text"][:60].replace("\n", " ")              
        print(f" {rank}  {point.score:.3f}  {p['doc_type']:<22} {p['source']:<36} {p['chunk']:<5}  {preview}...")



def main() -> None:
    for question in QUESTIONS:                                   # the 10 normal searches
        search(question)
    search(QUESTIONS[0], doc_type="playbooks")                   # the filtered search: same question, playbooks only


if __name__ == "__main__":
    main()
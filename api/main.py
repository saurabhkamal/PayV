"""Part 1: the API skeleton. POST /explain returns a placeholder answer in the final format."""

from typing import Literal                  # Literal limits a field to a fixed set of allowed values
from fastapi import FastAPI, HTTPException  # FastAPI builds the web service and its endpoints
                                            # HTTPException sends an error reply
from api.context import build_context       # Part 2: collects data from the three databases
from api.llm import ask_llm                 # Part 3: sends the context to the LLM
from pydantic import BaseModel              # BaseModel describes the shape of the JSON going in and out

# ---------- what the caller sends ----------
class ExplainRequest(BaseModel):            # the body of a POST /explain request
    transaction_id: str                     # the payment the investigator wants explained


# ---------- what send back ----------
class Source(BaseModel):                    # one piece of evidence the answer is based on
    document: str                           # which document the text came from
    chunk: int                              # which chunk of that document was used


class ExplainResponse(BaseModel):           # the full answer returned to the investigator
    transaction_id: str                     # the ID so the caller knows which case this is
    risk_summary: str                       # a short plain-English explanation of the risk
    reason_codes: list[str]                 # the fraud rules that fired, e.g. ["R01", "R04"]
    recommended_action: Literal["approve", "review", "block"]    # only these three actions are allowed
    sources: list[Source]                   # the policy chunks the answer cites


# ---------- the app ----------
app = FastAPI(title="PayV Investigator Assistant")        # create the web service; the title shows on /docs

@app.get("/health")                         # GET /health: a quick check that the server is running
def health() -> dict:
    return {"status": "ok"}                 # if you see this, the server is up

@app.post("/explain", response_model=ExplainResponse)      # POST /explain; the reply must match ExplainResponse
def explain(request: ExplainRequest) -> ExplainResponse:
    ctx = build_context(request.transaction_id)            # Part 2: ask the three databases
    if ctx is None:                                        # the transaction ID does not exist
        raise HTTPException(status_code=404, detail="Transaction not found")

    answer = ask_llm(ctx)                                  # Part 3: the LLM's summary, action and sources

    sources = []                                           # the citations we will keep
    for cited in answer.get("sources", []):                # go through each source the LLM cited
        for chunk in ctx["policy_chunks"]:                 # compare it with each chunk Qdrant really returned
            if cited["document"] == chunk["document"] and str(cited["chunk"]) == str(chunk["chunk"]):   # same document and same chunk number?
                sources.append({"document": chunk["document"], "chunk": chunk["chunk"]})   # yes: it is real, keep it
                break                                      # found it, stop comparing this citation

    reason_codes = ctx["features"]["reason_codes"] if ctx["features"] else []   # from the data, not the LLM

    return ExplainResponse(
        transaction_id=request.transaction_id,             # the same ID we received
        risk_summary=answer["risk_summary"],               # written by the LLM
        reason_codes=reason_codes,                         # computed in the features table
        recommended_action=answer["recommended_action"],   # chosen by the LLM; must be approve/review/block
        sources=sources,                                   # only citations that really exist
    )

@app.post("/context")                # POST /context: shows the raw context (for testing Part 2)
def context(request: ExplainRequest) -> dict:     # Checks that the request contains a transaction_id
    ctx = build_context(request.transaction_id)   # ask the three databases
    if ctx is None:                               # the transaction ID does not exist
        raise HTTPException(status_code=404, detail="Transaction not found")
    return ctx                        # FastAPI turns the dict into JSON

# ^^Adding a test endpoint to see what the three databases return before any LLM is involved.

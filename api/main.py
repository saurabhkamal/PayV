"""Part 1: the API skeleton. POST /explain returns a placeholder answer in the final format."""

from typing import Literal                  # Literal limits a field to a fixed set of allowed values
from fastapi import FastAPI                 # FastAPI builds the web service and its endpoints
from pydantic import BaseModel              # BaseModel describes the shape of the JSON going in and out

# ---------- what the caller sends ----------
class ExplainRequest(BaseModel):            # the body of a POST /explain request
    transaction_id: str                     # the payment the investigator wants explained


# ---------- what send back ----------
class Source(BaseModel):                    # one piece of evidence the answer is based on
    document: str                           # which document the text came from
    chunk: str                              # which chunk of that document was used


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
    # Part 1 only: return a fixed placeholder. Parts 2 and 3 replace it with real data and the LLM's answer.
    return ExplainResponse(
        transaction_id=request.transaction_id,       # send back the same ID was received 
        risk_summary="placeholder: real explanation comes in Part 3",   # dummy text for now
        reason_codes=[],                        # no rules checked yet
        recommended_action="review",            # a safe default until real logic exists
        sources=[],                             # no policy chunks retrieved yet
    )


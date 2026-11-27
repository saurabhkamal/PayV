"""Part 3: send the context to an LLM and get back a JSON answer."""

import json                      # turns the context into text, and the reply back into a dict
import os                        # reads the API key from the environment
import requests                  # Sends the HTTP request to the LLM gateway
from dotenv import load_dotenv   # loads the .env file

load_dotenv()                   # put API_KEY into os.environ


CHAT_URL = "https://api.euron.one/api/v1/euri/chat/completions"     # chat endpoint of the gateway
MODEL = "gpt-6.1-sol"          # Chat Model

# the rules the LLM must follow, sent with every request
SYSTEM_PROMPT = """You are an assistant for fraud investigators at PayV, an Indian payments company.
You receive the facts about one payment as JSON: the transaction, its features, the device
neighbourhood from the graph, and policy chunks from the document library.

Rules:
1. Use ONLY the facts in the JSON. Never invent facts, numbers or documents.
2. Write risk_summary in 3 to 5 plain sentences: which risk signals fired, what they mean,
   and what the device neighbourhood shows. Say when information is missing.
3. Choose recommended_action as exactly one of: "approve", "review", "block".
   Base it on the signals and the policy chunks. A risk flag alone does not prove fraud.
4. In sources, list only the policy chunks you actually used, copying their
   "document" and "chunk" values exactly from the JSON.
5. Reply with JSON only, no other text, in exactly this shape:
{"risk_summary": "...", "recommended_action": "review", "sources": [{"document": "...", "chunk": 0}]}
"""

def ask_llm(context: dict) -> dict:
    """Send the context to the LLM and return its answer as a dict."""
    response = requests.post(
        CHAT_URL,                                                  # where to send the request
        headers={"Authorization": f"Bearer {os.environ['EURI_API_KEY']}"},   # proves who we are
        json={
            "model": MODEL,                                        # which LLM to use
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},      # the rules
                {"role": "user", "content": json.dumps(context, indent=2, default=str)},   # the facts, as JSON text
            ],
            "temperature": 0,                                      # 0 = same input gives (almost) the same answer
        },
        timeout=120,                                               # give up after 2 minutes
    )
    response.raise_for_status()                                    # stop with an error if the gateway refused
    text = response.json()["choices"][0]["message"]["content"]    # the LLM's reply as text
    start = text.find("{")                                         # where the JSON begins (skips any extra words)
    end = text.rfind("}") + 1                                      # where the JSON ends
    return json.loads(text[start:end])                             # text -> Python dict
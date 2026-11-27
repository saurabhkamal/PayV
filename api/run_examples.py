"""Part 4: run /explain on 5 fraud and 5 genuine validation transactions and save the answers."""

import json 
import os                   # reads settings from the environment
import random               # picks a random sample of transactions
from pathlib import Path    # handles the output file path
import requests
from dotenv import load_dotenv      # loads the .env file
from supabase import create_client  # reads the labels table
from api.llm import MODEL           

load_dotenv()


API_URL = "http://127.0.0.1:8000/explain"   # running API
OUT_FILE = Path("api/results/explain_10.json")   # where the answers are saved
N_PER_CLASS = 5                              # 5 fraud + 5 genuine
SEED = 42                                    # same seed = same 10 transactions every run

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])   # Supabase client

def pick_ids(fraud_label: int) -> list[str]:
    """Pick N_PER_CLASS validation transactions with this label (1 = fraud, 0 = genuine)."""
    rows = (sb.table("labels").select("transaction_id")    # only the ID column
                .eq("split", "validation")                 # only the validation split
                .eq("fraud_label", fraud_label)            # only fraud, or only genuine
                .order("transaction_id")                   # fixed order, so the sample is repeatable
                .limit(1000)                               # Supabase returns at most 1,000 rows per request
                .execute().data)

    ids = []                                               # start with an empty list
    for r in rows:                                         # go through each row
        ids.append(r["transaction_id"])                    # keep just the ID
    random.seed(SEED)                                      # fix the random choice
    return random.sample(ids, N_PER_CLASS)                 # pick 5 of them


def main() -> None:
    cases = []                                             # the 10 transactions to test
    for tid in pick_ids(1):                                # 5 fraud
        cases.append({"transaction_id": tid, "true_label": "fraud"})
    for tid in pick_ids(0):                                # 5 genuine
        cases.append({"transaction_id": tid, "true_label": "genuine"})

    results = []                                           # the answers we will save
    for case in cases:                                     # one API call per transaction
        print(f"Explaining {case['transaction_id']} ({case['true_label']}) ...")
        response = requests.post(API_URL, json={"transaction_id": case["transaction_id"]},
                                 timeout=300)              # wait up to 5 minutes
        response.raise_for_status()                        # stop if the API returned an error
        results.append({"transaction_id": case["transaction_id"],
                        "true_label": case["true_label"],  # added AFTER the API answered; never sent to the LLM
                        "response": response.json()})      # the full answer from /explain

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)     # create api/results/ if missing
    OUT_FILE.write_text(json.dumps({"model": MODEL, "results": results}, indent=2),
                        encoding="utf-8")                  # save everything as readable JSON
    print(f"\nSaved {len(results)} answers to {OUT_FILE}\n")

    print(f"{'transaction':<16} {'true label':<10} {'action':<8} reason codes")   # a quick summary table
    for r in results:                                      # one line per transaction
        answer = r["response"]
        print(f"{r['transaction_id']:<16} {r['true_label']:<10} "
              f"{answer['recommended_action']:<8} {', '.join(answer['reason_codes'])}")


if __name__ == "__main__":
    main()
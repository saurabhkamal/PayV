"""Step 6: two aggregation pipelines on the payv transactions."""
import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
tx = MongoClient(os.environ["MONGODB_URI"])["payv"].transactions

# Pipeline 1: fraud rate per merchant category
fraud_by_category = [
    # 1. One group per category: count transactions, add up the 0/1 fraud labels
    {"$group": {
        "_id": "$merchant.category",
        "transactions": {"$sum": 1},
        "fraud": {"$sum": "$fraud_label"},
    }},
    # 2. Calculate the rate in percent, rounded to 2 decimals; rename _id to category
    {"$project": {
        "_id": 0,
        "category": "$_id",
        "transactions": 1,
        "fraud": 1,
        "fraud_rate_pct": {"$round": [
            {"$multiply": [{"$divide": ["$fraud", "$transactions"]}, 100]}, 2]},
    }},
    # 3. Riskiest first
    {"$sort": {"fraud_rate_pct": -1}},
]

print("Fraud rate per merchant category")
for r in tx.aggregate(fraud_by_category):
    category = r["category"]
    total = r["transactions"]
    fraud = r["fraud"]
    rate = r["fraud_rate_pct"]
    print(f"  {category}: {fraud} fraud out of {total} transactions ({rate}%)")

# Pipeline 2: top 10 customers by amount in their last 24 hours of activity
top_last_24h = [
    # 1. Add each customer's latest transaction time to all of their transactions
    {"$setWindowFields": {
        "partitionBy": "$customer_id",
        "output": {"last_time": {"$max": "$transaction_time"}},
    }},
    # 2. Keep transactions within 24 hours before that latest time
    {"$match": {"$expr": {"$gte": [
        "$transaction_time",
        {"$dateSubtract": {"startDate": "$last_time", "unit": "hour", "amount": 24}},
    ]}}},
    # 3. One result per customer: total amount and number of transactions in the window
    {"$group": {
        "_id": "$customer_id",
        "amount_paise": {"$sum": "$amount_paise"},
        "transactions": {"$sum": 1},
        "last_time": {"$first": "$last_time"},
        "home_city": {"$first": "$customer.home_city"},
    }},
    # 4. Biggest amounts first, keep 10
    {"$sort": {"amount_paise": -1}},
    {"$limit": 10},
    # 5. Tidy output: rupees instead of paise
    {"$project": {
        "_id": 0,
        "customer_id": "$_id",
        "home_city": 1,
        "transactions": 1,
        "last_time": 1,
        "amount_rupees": {"$divide": ["$amount_paise", 100]},
    }},
]

print("\nTop 10 customers by amount in their last 24 hours of activity")
for r in tx.aggregate(top_last_24h):
    customer = r["customer_id"]
    city = r["home_city"]
    count = r["transactions"]
    amount = r["amount_rupees"]
    last = r["last_time"]
    print(f"  {customer} ({city}): Rs {amount:,.2f} in {count} transactions, last one at {last} UTC")


import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
client = MongoClient(os.environ["MONGODB_URI"])

client.admin.command("ping")          # raises an error if the connection fails
print("Connected to MongoDB Atlas!")
print("Databases:", client.list_database_names())

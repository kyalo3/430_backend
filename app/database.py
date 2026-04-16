from dotenv import load_dotenv
import os
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()
# MongoDB connection details
MONGO_DETAILS = os.getenv("MONGO_DETAILS")

# Establish connection to MongoDB server
client = AsyncIOMotorClient(MONGO_DETAILS)

# Initialize database
database = client.food_donation

# Initialize collections for storing data
donor_collection = database.get_collection("donors")
recipient_collection = database.get_collection("recipients")
donation_collection = database.get_collection("donations")
user_collection = database.get_collection("users")
volunteer_collection = database.get_collection("volunteers")
review_collection = database.get_collection("reviews")
donation_request_collection = database.get_collection("donation_requests")

db = database
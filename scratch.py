import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

def create_payment(amount_inr: float, item_description: str) -> str:
    """Creates a payment order."""
    pass

chat = client.chats.create(
    model="gemini-2.5-flash",
    config=types.GenerateContentConfig(tools=[create_payment])
)

response = chat.send_message("Create a payment for 500 INR for shoes.")
print(response.function_calls)

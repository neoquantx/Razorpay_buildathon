import os
import sys
from dotenv import load_dotenv
from google import genai

def main():
    # Load environment variables from .env file
    load_dotenv()
    
    # Check if the API key is set
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_key_here":
        print("Error: GEMINI_API_KEY is not set correctly in the .env file.")
        print("Please update your .env file with a valid Gemini API key.")
        sys.exit(1)
        
    try:
        print("Initializing Gemini client...")
        client = genai.Client(api_key=api_key)
        
        print("Sending test message to Gemini...")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Say hello and confirm you are working correctly.'
        )
        
        print("\n--- Gemini Response ---")
        print(response.text)
        print("-----------------------")
        print("\nSuccess! Gemini API connection is working.")
        
    except Exception as e:
        print("\nError connecting to Gemini API:")
        print(f"Details: {str(e)}")
        print("Please check your API key and internet connection.")

if __name__ == "__main__":
    main()

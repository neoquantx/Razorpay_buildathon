# Razorpay AI Checkout Agent

This is a Python project skeleton for an AI-powered checkout agent that integrates with the Razorpay payment gateway. It currently contains the initial project structure and basic connection tests for both the Gemini AI API and the Razorpay API to ensure everything is set up correctly before building the main logic.

## Project Setup

1. **Install dependencies**
   Make sure you have Python installed, then run:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables**
   Copy the example environment file to create your own `.env` file:
   ```bash
   cp .env.example .env
   ```
   Then open `.env` and fill in your actual Gemini API key and Razorpay test credentials. (Note: The `.env` file is ignored by git so your secrets will not be committed).

## Running the Tests

To verify that your API keys are working, you can run the following test scripts from the root of the project:

**Test Gemini Connection:**
```bash
python src/test_gemini_connection.py
```
This script sends a simple hello message to the Gemini API and prints its response.

**Test Razorpay Connection:**
```bash
python src/test_razorpay_connection.py
```
This script creates a dummy order for ₹1 using your Razorpay test credentials. It clearly indicates that it is a test mode order and no real money is involved.

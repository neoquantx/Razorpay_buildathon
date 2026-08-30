import os
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import types

import payment
import guardrail
import audit_log

def create_payment(amount_inr: float, item_description: str):
    """Creates a payment order for the specified amount and item."""
    pass

def main():
    # Load environment variables
    load_dotenv()
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_key_here":
        print("Error: GEMINI_API_KEY is not set correctly in the .env file.")
        sys.exit(1)

    try:
        print("Initializing Gemini client...")
        client = genai.Client(api_key=api_key)
        
        chat = client.chats.create(
            model='gemini-2.5-flash',
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are Ledger, a checkout assistant for an online merchant. "
                    "You help customers complete purchases naturally. You are aware that "
                    "all purchases are checked against a spending policy before anything happens — "
                    "orders under ₹500 are automatic, orders between ₹500 and ₹2000 need the "
                    "customer's confirmation, and orders above ₹2000 are not allowed. "
                    "If a payment is denied or fails, explain why in a calm, clear, and reassuring way, "
                    "and suggest what the customer could do instead. Keep responses brief and conversational, "
                    "like a helpful human assistant, not a robotic system log."
                ),
                tools=[create_payment],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
            )
        )
    except Exception as e:
        print(f"Error initializing Gemini client: {e}")
        sys.exit(1)

    revoked = False
    
    print("\n--- Razorpay Checkout Agent Started ---")
    print("Commands:")
    print("  'revoke' - Instantly revoke payment capabilities.")
    print("  'exit'   - Quit the agent.")
    print("---------------------------------------")

    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ['exit', 'quit']:
                print("Goodbye!")
                break
                
            if user_input == "revoke":
                revoked = True
                print("Confirmation: Payment capabilities have been REVOKED.")
                continue

            # Send message to Gemini
            response = chat.send_message(user_input)

            # Check if Gemini made a tool call
            if response.function_calls:
                for tool_call in response.function_calls:
                    if tool_call.name == "create_payment":
                        # Extract arguments
                        amount_inr = tool_call.args.get("amount_inr", 0.0)
                        item_description = tool_call.args.get("item_description", "Unknown item")
                        
                        print(f"\n[Agent wants to call create_payment(amount_inr={amount_inr}, item_description='{item_description}')]")
                        
                        # 1. Guardrail Check
                        decision_result = guardrail.check_action(amount_inr, revoked)
                        decision = decision_result["decision"]
                        reason = decision_result["reason"]
                        
                        skip_gemini_print = False
                        tool_result = {}
                        
                        if decision == "approved":
                            print(f"[Guardrail] Approved: {reason}")
                            try:
                                order = payment.create_order(amount_inr, item_description)
                                audit_log.log_action("create_payment", amount_inr, reason, "approved")
                                tool_result = {"status": "success", "order": order}
                            except payment.PaymentFailedError as e:
                                audit_log.log_action("create_payment", amount_inr, str(e), "failed")
                                tool_result = {"status": "failed", "error": str(e)}
                                print(f"\nAgent: I'm sorry, the payment failed. {e} Would you like to try a different amount or item instead?")
                                skip_gemini_print = True
                            except Exception as e:
                                print(f"[Error] Failed to create order: {e}")
                                audit_log.log_action("create_payment", amount_inr, str(e), "failed")
                                tool_result = {"status": "error", "error": str(e)}

                        elif decision == "needs_confirmation":
                            audit_log.log_action("create_payment", amount_inr, reason, "pending_confirmation")
                            print("\nThis is above the auto-approve limit of ₹500. Type 'yes' to confirm or 'no' to cancel.")
                            
                            confirm = input("Confirm? (yes/no): ").strip().lower()
                            if confirm == 'yes':
                                try:
                                    order = payment.create_order(amount_inr, item_description)
                                    audit_log.log_action("create_payment", amount_inr, "User confirmed", "approved after confirmation")
                                    tool_result = {"status": "success", "order": order}
                                    print("[System] Payment created successfully.")
                                except payment.PaymentFailedError as e:
                                    audit_log.log_action("create_payment", amount_inr, str(e), "failed")
                                    tool_result = {"status": "failed", "error": str(e)}
                                    print(f"\nAgent: I'm sorry, the payment failed. {e} Would you like to try a different amount or item instead?")
                                    skip_gemini_print = True
                                except Exception as e:
                                    print(f"[Error] Failed to create order: {e}")
                                    audit_log.log_action("create_payment", amount_inr, str(e), "failed")
                                    tool_result = {"status": "error", "error": str(e)}
                            else:
                                audit_log.log_action("create_payment", amount_inr, "User declined", "cancelled_by_user")
                                tool_result = {"status": "cancelled", "reason": "User denied the confirmation."}
                                print("[System] Payment cancelled by user.")

                        elif decision == "denied":
                            audit_log.log_action("create_payment", amount_inr, reason, "denied")
                            tool_result = {"status": "denied", "reason": reason}
                            print(f"\n[System] Payment denied: {reason}")
                            
                        # Send the function response back to Gemini to complete the loop
                        followup_response = chat.send_message(
                            types.Part.from_function_response(
                                name="create_payment",
                                response=tool_result
                            )
                        )
                        if not skip_gemini_print and followup_response.text:
                            print(f"\nAgent: {followup_response.text}")

            else:
                # Plain text response from Gemini
                if response.text:
                    print(f"\nAgent: {response.text}")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\n[Unexpected Error] {e}")
            print("The conversation is still active. Please try again.")

if __name__ == "__main__":
    main()

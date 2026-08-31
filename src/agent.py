import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path
from google import genai
from google.genai import types

import payment
import guardrail
import audit_log
import session_state
import idempotency
import upsell
import metrics

def create_payment(amount_inr: float, item_description: str):
    """Creates a payment order for the specified amount and item."""
    pass

def main():
    # Load environment variables
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    
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
                    "like a helpful human assistant, not a robotic system log. "
                    "If the tool result includes an upsell_suggestion field, naturally offer exactly that "
                    "add-on to the customer in one short, friendly sentence after confirming "
                    "their purchase, then wait for their response. Never add it automatically "
                    "— only if they say yes should you call create_payment again for it. "
                    "If a customer declines an upsell offer (says no, not now, etc.), acknowledge it warmly in one sentence and move on. "
                    "Never repeat, rephrase, or re-offer the same suggestion again in this conversation. "
                    "Never use urgency, scarcity, or guilt to encourage a yes — a single honest offer is enough, and a 'no' is final."
                ),
                tools=[create_payment],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
            )
        )
    except Exception as e:
        print(f"Error initializing Gemini client: {e}")
        sys.exit(1)

    state = session_state.get_state()
    revoked = state.get("revoked", False)
    recent_amounts = state.get("recent_amounts", [])
    
    print("\n--- Razorpay Checkout Agent Started ---")
    print("Commands:")
    print("  'revoke' - Instantly revoke payment capabilities.")
    print("  'exit'   - Quit the agent.")
    print("---------------------------------------")

    pending_upsell_item = None

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
                state["revoked"] = True
                session_state.save_state(state)
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
                        
                        # 1. Guardrail & Catalog Check
                        expected_price = upsell.get_expected_upsell_price(item_description)
                        if expected_price is not None and amount_inr != expected_price:
                            decision_result = {
                                "decision": "denied_price_mismatch",
                                "reason": f"Price mismatch for a known catalog item — expected ₹{expected_price}, request was for ₹{amount_inr}. Possible manipulation."
                            }
                        else:
                            decision_result = guardrail.check_action(amount_inr, revoked, recent_amounts)
                            
                        decision = decision_result["decision"]
                        reason = decision_result["reason"]
                        
                        skip_gemini_print = False
                        tool_result = {}
                        now = datetime.now(timezone.utc).isoformat()
                        
                        if decision == "approved":
                            print(f"[Guardrail] Approved: {reason}")
                            try:
                                key = idempotency.generate_key(amount_inr, item_description)
                                cached = idempotency.get_cached_result(key)
                                if cached:
                                    print("[Idempotency] Reusing cached result, no duplicate charge.")
                                    order = cached.get("order")
                                else:
                                    order = payment.create_order(amount_inr, item_description, idempotency_key=key)
                                    idempotency.save_result(key, {"order": order})
                                    
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
                                    key = idempotency.generate_key(amount_inr, item_description)
                                    cached = idempotency.get_cached_result(key)
                                    if cached:
                                        print("[Idempotency] Reusing cached result, no duplicate charge.")
                                        order = cached.get("order")
                                    else:
                                        order = payment.create_order(amount_inr, item_description, idempotency_key=key)
                                        idempotency.save_result(key, {"order": order})
                                        
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

                        elif decision in ("denied", "denied_price_mismatch"):
                            outcome = "denied_price_mismatch" if decision == "denied_price_mismatch" else "denied"
                            audit_log.log_action("create_payment", amount_inr, reason, outcome)
                            tool_result = {"status": "denied", "reason": reason}
                            print(f"\n[System] Payment denied: {reason}")
                            
                        if tool_result.get("status") == "success":
                            is_upsell = (pending_upsell_item is not None) and (pending_upsell_item.lower() in item_description.lower())
                            metrics.record_order(amount_inr, is_upsell=is_upsell)
                            pending_upsell_item = None
                            
                            suggestion = upsell.get_upsell_suggestion(item_description)
                            if suggestion:
                                metrics.record_upsell_offered()
                                pending_upsell_item = suggestion["suggested_item"]
                                tool_result["upsell_suggestion"] = suggestion["pitch"]

                            
                        # Append to recent amounts and save state (skip if cancelled by user)
                        if tool_result.get("status") != "cancelled":
                            recent_amounts.append({"amount_inr": amount_inr, "timestamp": now})
                            state["recent_amounts"] = recent_amounts
                            session_state.save_state(state)
                            
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

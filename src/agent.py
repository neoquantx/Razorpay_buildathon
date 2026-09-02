import json
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
import negotiation
import price_check
from price_check import verify_item_price  # re-exported for agent-internal use

# Load the product catalog for the negotiate_price tool
_PRODUCTS_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'products.json')

def _load_products() -> dict:
    """Return the product catalog; empty dict if the file is missing."""
    if not os.path.exists(_PRODUCTS_PATH):
        return {}
    with open(_PRODUCTS_PATH, 'r') as _f:
        return json.load(_f)


def create_payment(amount_inr: float, item_description: str):
    """Creates a payment order for the specified amount and item."""
    pass

def negotiate_price(item_name: str, requested_price_inr: float) -> dict:
    """
    Check whether a requested price for a catalog item is within the merchant's
    negotiation policy. Returns the policy decision — never invent a discount.
    """
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
                    "Never use urgency, scarcity, or guilt to encourage a yes — a single honest offer is enough, and a 'no' is final. "
                    "If a customer asks for a discount or tries to negotiate, always call negotiate_price for the real answer — "
                    "never invent or promise a discount yourself. Relay exactly what the tool returns: if accepted, confirm that price; "
                    "if countered, offer the counter as the best available; if rejected, explain why. "
                    "If the customer accepts a countered or accepted price, proceed to create_payment using that exact final price."
                ),
                tools=[create_payment, negotiate_price],
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

                        # 1. Price-integrity check — runs BEFORE the guardrail.
                        #    Covers all known catalog items (not just upsell targets).
                        price_check = verify_item_price(item_description, amount_inr, state)
                        if not price_check["ok"]:
                            reason = price_check["reason"]
                            audit_log.log_action("create_payment", amount_inr, reason, "denied_price_mismatch")
                            tool_result = {"status": "denied", "reason": reason}
                            print(f"\n[System] Payment denied (price mismatch): {reason}")
                            followup_response = chat.send_message(
                                types.Part.from_function_response(
                                    name="create_payment",
                                    response=tool_result
                                )
                            )
                            if followup_response.text:
                                print(f"\nAgent: {followup_response.text}")
                            continue

                        # 2. Guardrail check (only reached when price is valid)
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

                    elif tool_call.name == "negotiate_price":
                        item_name = tool_call.args.get("item_name", "")
                        requested_price_inr = tool_call.args.get("requested_price_inr", 0.0)

                        print(f"\n[Agent wants to call negotiate_price(item_name='{item_name}', requested_price_inr={requested_price_inr})]")

                        # Look up authoritative catalog price (case-insensitive)
                        catalog = _load_products()
                        item_key = None
                        for k in catalog:
                            if k.lower() == item_name.lower():
                                item_key = k
                                break

                        if item_key is None:
                            neg_result = {
                                "decision": "item_not_found",
                                "reason": f"'{item_name}' was not found in the catalog."
                            }
                        else:
                            catalog_price = catalog[item_key]["price_inr"]
                            neg_result = negotiation.evaluate_negotiation(catalog_price, requested_price_inr)

                        decision = neg_result.get("decision", "unknown")
                        reason = neg_result.get("reason", "")

                        # Audit every attempt — accepted or not
                        audit_log.log_action(
                            action="negotiate_price",
                            amount_inr=requested_price_inr,
                            reason=reason,
                            outcome=decision
                        )

                        # Persist the final price so verify_item_price can authorise it
                        # when the customer later calls create_payment at that price.
                        # Only "accepted" and "countered" yield a real usable price.
                        if decision in ("accepted", "countered") and item_key is not None:
                            state["last_negotiation"] = {
                                "item_name": item_key,
                                "final_price_inr": neg_result["final_price_inr"],
                            }
                            session_state.save_state(state)

                        print(f"[Negotiation] decision={decision}, result={neg_result}")

                        # Return result to Gemini
                        followup_response = chat.send_message(
                            types.Part.from_function_response(
                                name="negotiate_price",
                                response=neg_result
                            )
                        )
                        if followup_response.text:
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

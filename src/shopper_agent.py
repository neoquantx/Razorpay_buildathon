"""
shopper_agent.py — Gemini-powered comparison-shopping CLI.

A separate CLI from agent.py that reuses the same guardrail, payment,
audit_log, idempotency, and session_state modules. Persona: Scout.
"""

import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path
from google import genai
from google.genai import types

import session_state
import audit_log
import multi_merchant


# ── Tool stubs (signatures only — Gemini sees these) ──────────────────
def find_cheapest_price(item_name: str) -> dict:
    """Find the cheapest price for an item across all merchants."""
    pass


def buy_from_merchant(merchant_id: str, item_name: str, quantity: int) -> dict:
    """Purchase an item from a specific merchant."""
    pass


# ── Main loop ─────────────────────────────────────────────────────────
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
                    "You are Scout, a comparison shopping assistant. "
                    "When asked to buy something, ALWAYS call find_cheapest_price first "
                    "and show the customer the price at every merchant that carries it, "
                    "not just the winner. Then either buy from the cheapest automatically, "
                    "or ask if the customer has a different preference. "
                    "Never state a price yourself — only relay exactly what "
                    "find_cheapest_price returns."
                ),
                tools=[find_cheapest_price, buy_from_merchant],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
            )
        )
    except Exception as e:
        print(f"Error initializing Gemini client: {e}")
        sys.exit(1)

    state = session_state.get_state()
    revoked = state.get("revoked", False)

    print("\n--- Razorpay Comparison Shopper Started ---")
    print("Commands:")
    print("  'revoke' - Instantly revoke payment capabilities.")
    print("  'exit'   - Quit the agent.")
    print("--------------------------------------------")

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

            tool_round = 0
            MAX_TOOL_ROUNDS = 5  # safety cap against a runaway chain of tool calls
            
            while response.function_calls and tool_round < MAX_TOOL_ROUNDS:
                tool_round += 1
                tool_call = response.function_calls[0]
                
                if tool_call.name == "find_cheapest_price":
                    item_name = tool_call.args.get("item_name", "")
                    print(f"\n[Scout wants to call find_cheapest_price(item_name='{item_name}')]")

                    result = multi_merchant.find_cheapest(item_name)
                    print(f"[Comparison] result={result}")

                elif tool_call.name == "buy_from_merchant":
                    merchant_id = tool_call.args.get("merchant_id", "")
                    item_name = tool_call.args.get("item_name", "")
                    quantity = int(tool_call.args.get("quantity", 1))

                    print(f"\n[Scout wants to call buy_from_merchant(merchant_id='{merchant_id}', item_name='{item_name}', quantity={quantity})]")

                    # Reload state to pick up any recent_amounts changes
                    state = session_state.get_state()
                    result = multi_merchant.buy_from_merchant(
                        merchant_id, item_name, quantity, state
                    )

                    status = result.get("status", "unknown")

                    if status == "needs_confirmation":
                        print(f"\nThis is above the auto-approve limit. Type 'yes' to confirm or 'no' to cancel.")
                        confirm = input("Confirm? (yes/no): ").strip().lower()
                        if confirm == 'yes':
                            # Re-attempt — the guardrail already classified it;
                            # force-approve by calling payment directly.
                            # (Mirror agent.py pattern: ask, then proceed.)
                            import payment as pay_mod
                            import idempotency
                            total = result["total_inr"]
                            desc = f"{quantity}x {item_name} from {multi_merchant.MERCHANTS.get(merchant_id, merchant_id)}"
                            try:
                                key = idempotency.generate_key(total, desc)
                                cached = idempotency.get_cached_result(key)
                                if cached:
                                    order = cached.get("order")
                                else:
                                    order = pay_mod.create_order(total, desc, idempotency_key=key)
                                    idempotency.save_result(key, {"order": order})

                                audit_log.log_action(f"shopper_buy_{merchant_id}", total, "User confirmed", "approved after confirmation")
                                now = datetime.now(timezone.utc).isoformat()
                                ra = state.get("recent_amounts", [])
                                ra.append({"amount_inr": total, "timestamp": now})
                                state["recent_amounts"] = ra
                                session_state.save_state(state)

                                order_id = order.get("order_id") if isinstance(order, dict) else order
                                result = {"status": "success", "order_id": order_id, "amount_inr": total,
                                          "merchant_id": merchant_id, "item": item_name, "quantity": quantity}
                                print("[System] Payment created successfully.")
                            except Exception as exc:
                                audit_log.log_action(f"shopper_buy_{merchant_id}", total, str(exc), "failed")
                                result = {"status": "failed", "error": str(exc)}
                        else:
                            audit_log.log_action(f"shopper_buy_{merchant_id}", result["total_inr"], "User declined", "cancelled_by_user")
                            result = {"status": "cancelled", "reason": "User denied the confirmation."}
                            print("[System] Payment cancelled by user.")

                    elif status == "success":
                        print(f"[System] Payment created successfully: {result}")
                    elif status in ("denied", "error", "failed"):
                        msg = result.get("reason") or result.get("message") or result.get("error", "")
                        print(f"[System] Purchase {status}: {msg}")
                
                response = chat.send_message(
                    types.Part.from_function_response(name=tool_call.name, response=result)
                )

            if tool_round >= MAX_TOOL_ROUNDS:
                print("\n[System] Stopped after 5 chained tool calls, to avoid a runaway loop.")
            
            if response.text:
                print(f"\nScout: {response.text}")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\n[Unexpected Error] {e}")
            print("The conversation is still active. Please try again.")


if __name__ == "__main__":
    main()

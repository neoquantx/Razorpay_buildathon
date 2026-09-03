#!/usr/bin/env python3
"""
run_scenarios.py — Automated conversation eval suite for the Razorpay
                    Checkout Agent.

⚠️  WARNING: This script calls the REAL Gemini API for every scenario.
   Each run costs real API quota (roughly 10 model calls × 2-4 turns each).
   Do NOT run this in a tight loop or in CI without budget controls.

Usage:
    python tests/scenarios/run_scenarios.py          # from project root
    python -m tests.scenarios.run_scenarios           # also works

It drives real scripted conversations through the same Gemini chat and
tool-handling logic that agent.py uses, then validates outcomes by reading
data/audit_log.jsonl — NOT by matching printed text, since model wording
varies.
"""

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — ensure `src/` is importable regardless of working directory
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
sys.path.insert(0, str(_SRC_DIR))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env")

# Local project imports (now that src/ is on sys.path)
import reset_demo          # noqa: E402
import audit_log           # noqa: E402
import session_state       # noqa: E402
import guardrail           # noqa: E402
import idempotency         # noqa: E402
import payment             # noqa: E402
import upsell              # noqa: E402
import metrics             # noqa: E402
import negotiation         # noqa: E402
import price_check         # noqa: E402
from price_check import verify_item_price  # noqa: E402
from agent import build_system_instruction  # noqa: E402

from google import genai             # noqa: E402
from google.genai import types        # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AUDIT_LOG_PATH = _PROJECT_ROOT / "data" / "audit_log.jsonl"
PRODUCTS_PATH = _PROJECT_ROOT / "config" / "products.json"
MAX_TURNS_PER_MESSAGE = 6  # safety limit to avoid infinite tool-call loops


# ═══════════════════════════════════════════════════════════════════════════
#  Conversation driver — mirrors agent.py's main-loop logic WITHOUT input()
# ═══════════════════════════════════════════════════════════════════════════

def _load_products() -> dict:
    if not PRODUCTS_PATH.exists():
        return {}
    with open(PRODUCTS_PATH, "r") as f:
        return json.load(f)


def _build_chat(client: genai.Client):
    """Create a fresh Gemini chat with the same config as agent.py."""

    # Stub tool definitions (same signatures as agent.py)
    def create_payment(amount_inr: float, item_description: str):
        """Creates a payment order for the specified amount and item."""
        pass

    def negotiate_price(item_name: str, requested_price_inr: float) -> dict:
        """Check whether a requested price for a catalog item is within the
        merchant's negotiation policy."""
        pass

    return client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=build_system_instruction(),
            tools=[create_payment, negotiate_price],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        ),
    )


def _handle_tool_calls(response, chat, state, revoked, recent_amounts):
    """Process tool calls exactly like agent.py does, returning the final
    text response (may be None)."""

    pending_upsell_item = None
    last_text = None

    for turn in range(MAX_TURNS_PER_MESSAGE):
        if not response.function_calls:
            last_text = response.text
            break

        for tool_call in response.function_calls:
            if tool_call.name == "create_payment":
                amount_inr = tool_call.args.get("amount_inr", 0.0)
                item_description = tool_call.args.get(
                    "item_description", "Unknown item"
                )

                # Price-integrity check (before guardrail)
                pc = verify_item_price(item_description, amount_inr, state)
                if not pc["ok"]:
                    reason = pc["reason"]
                    audit_log.log_action(
                        "create_payment", amount_inr, reason,
                        "denied_price_mismatch",
                    )
                    tool_result = {"status": "denied", "reason": reason}
                    response = chat.send_message(
                        types.Part.from_function_response(
                            name="create_payment", response=tool_result,
                        )
                    )
                    continue

                # Guardrail
                decision_result = guardrail.check_action(
                    amount_inr, revoked, recent_amounts,
                )
                decision = decision_result["decision"]
                reason = decision_result["reason"]
                now = datetime.now(timezone.utc).isoformat()
                tool_result = {}

                if decision == "approved":
                    try:
                        key = idempotency.generate_key(
                            amount_inr, item_description,
                        )
                        cached = idempotency.get_cached_result(key)
                        if cached:
                            order = cached.get("order")
                        else:
                            order = payment.create_order(
                                amount_inr, item_description,
                                idempotency_key=key,
                            )
                            idempotency.save_result(key, {"order": order})
                        audit_log.log_action(
                            "create_payment", amount_inr, reason, "approved",
                        )
                        tool_result = {"status": "success", "order": order}
                    except payment.PaymentFailedError as e:
                        audit_log.log_action(
                            "create_payment", amount_inr, str(e), "failed",
                        )
                        tool_result = {"status": "failed", "error": str(e)}
                    except Exception as e:
                        audit_log.log_action(
                            "create_payment", amount_inr, str(e), "failed",
                        )
                        tool_result = {"status": "error", "error": str(e)}

                elif decision == "needs_confirmation":
                    # In scenarios, confirmation is handled by sending the
                    # next user message; here we just log pending and return
                    # the needs_confirmation tool result so the model asks
                    # the user.
                    audit_log.log_action(
                        "create_payment", amount_inr, reason,
                        "pending_confirmation",
                    )
                    tool_result = {
                        "status": "needs_confirmation",
                        "reason": reason,
                    }

                elif decision in ("denied", "denied_price_mismatch"):
                    outcome = (
                        "denied_price_mismatch"
                        if decision == "denied_price_mismatch"
                        else "denied"
                    )
                    audit_log.log_action(
                        "create_payment", amount_inr, reason, outcome,
                    )
                    tool_result = {"status": "denied", "reason": reason}

                # Upsell + metrics (only on success)
                if tool_result.get("status") == "success":
                    is_upsell = (
                        pending_upsell_item is not None
                        and pending_upsell_item.lower()
                        in item_description.lower()
                    )
                    metrics.record_order(amount_inr, is_upsell=is_upsell)
                    pending_upsell_item = None
                    suggestion = upsell.get_upsell_suggestion(item_description)
                    if suggestion:
                        metrics.record_upsell_offered()
                        pending_upsell_item = suggestion["suggested_item"]
                        tool_result["upsell_suggestion"] = suggestion["pitch"]

                # Track recent amounts (skip if cancelled by user)
                if tool_result.get("status") != "cancelled":
                    recent_amounts.append(
                        {"amount_inr": amount_inr, "timestamp": now}
                    )
                    state["recent_amounts"] = recent_amounts
                    session_state.save_state(state)

                # Return tool result to model
                response = chat.send_message(
                    types.Part.from_function_response(
                        name="create_payment", response=tool_result,
                    )
                )

            elif tool_call.name == "negotiate_price":
                item_name = tool_call.args.get("item_name", "")
                requested_price_inr = tool_call.args.get(
                    "requested_price_inr", 0.0,
                )

                catalog = _load_products()
                item_key = None
                for k in catalog:
                    if k.lower() == item_name.lower():
                        item_key = k
                        break

                if item_key is None:
                    neg_result = {
                        "decision": "item_not_found",
                        "reason": (
                            f"'{item_name}' was not found in the catalog."
                        ),
                    }
                else:
                    catalog_price = catalog[item_key]["price_inr"]
                    neg_result = negotiation.evaluate_negotiation(
                        catalog_price, requested_price_inr,
                    )

                decision = neg_result.get("decision", "unknown")
                reason = neg_result.get("reason", "")

                audit_log.log_action(
                    action="negotiate_price",
                    amount_inr=requested_price_inr,
                    reason=reason,
                    outcome=decision,
                )

                if (
                    decision in ("accepted", "countered")
                    and item_key is not None
                ):
                    state["last_negotiation"] = {
                        "item_name": item_key,
                        "final_price_inr": neg_result["final_price_inr"],
                    }
                    session_state.save_state(state)

                response = chat.send_message(
                    types.Part.from_function_response(
                        name="negotiate_price", response=neg_result,
                    )
                )
    else:
        # Exhausted turn limit
        last_text = getattr(response, "text", None)

    return last_text


def run_conversation(client, messages, confirm_step=None):
    """Drive a full multi-turn conversation.

    Args:
        client: a genai.Client
        messages: list of str — user messages to send sequentially
        confirm_step: optional int index — if set, simulate a confirmation
                      flow at that message index (the agent.py confirmation
                      prompt is intercepted here)
    Returns:
        list of str — agent text responses (one per user message)
    """
    chat = _build_chat(client)
    state = session_state.get_state()
    revoked = state.get("revoked", False)
    recent_amounts = state.get("recent_amounts", [])
    responses = []

    for idx, msg in enumerate(messages):
        # Handle 'revoke' command identically to agent.py
        if msg.strip().lower() == "revoke":
            revoked = True
            state["revoked"] = True
            session_state.save_state(state)
            responses.append("[System] Payment capabilities have been REVOKED.")
            continue

        response = chat.send_message(msg)

        if response.function_calls:
            text = _handle_tool_calls(
                response, chat, state, revoked, recent_amounts,
            )

            # After handling tool calls, if the outcome was
            # "needs_confirmation" and the NEXT user message is a
            # confirmation/denial, we need to process that specially.
            # We check the audit log for a pending_confirmation entry and
            # the next message.
            #
            # However, the real agent.py uses a separate input() prompt for
            # confirmation.  In our scenario driver the next user message in
            # the list acts as the confirmation reply — it goes through the
            # normal send_message path, and the model should react
            # appropriately (telling the user it was confirmed/cancelled).
            # The audit log entry is already written as pending_confirmation;
            # the follow-up "yes"/"no" message from the user causes the
            # model to either call create_payment again (which will succeed
            # at the guardrail for the same amount since the policy hasn't
            # changed) or just acknowledge cancellation.

            responses.append(text or "")
        else:
            responses.append(response.text or "")

    return responses


# ═══════════════════════════════════════════════════════════════════════════
#  Audit-log assertions
# ═══════════════════════════════════════════════════════════════════════════

def read_audit_log() -> list[dict]:
    """Read all entries from data/audit_log.jsonl."""
    return audit_log.read_all_logs()


def assert_log_contains(entries: list[dict], expected: dict) -> tuple[bool, str]:
    """Check that at least one audit log entry contains all key-value pairs
    in *expected*.

    Returns (passed: bool, detail: str).
    """
    for entry in entries:
        if all(entry.get(k) == v for k, v in expected.items()):
            return True, f"Found matching entry: {entry}"
    return False, (
        f"No audit log entry matched {expected}.\n"
        f"  Log has {len(entries)} entries:\n"
        + "\n".join(f"    {json.dumps(e)}" for e in entries)
    )


def assert_log_empty() -> tuple[bool, str]:
    """Check that the audit log has zero entries."""
    entries = read_audit_log()
    if len(entries) == 0:
        return True, "Audit log is empty as expected."
    return False, (
        f"Expected empty audit log but found {len(entries)} entries:\n"
        + "\n".join(f"    {json.dumps(e)}" for e in entries)
    )


def assert_log_contains_and_not(entries: list[dict], must_contain: dict, must_not_contain: dict) -> tuple[bool, str]:
    """Check that at least one audit log entry contains all key-value pairs in *must_contain*,
    and NO audit log entry contains all key-value pairs in *must_not_contain*.

    Returns (passed: bool, detail: str).
    """
    has_contain = False
    for entry in entries:
        if all(entry.get(k) == v for k, v in must_contain.items()):
            has_contain = True
            break
            
    if not has_contain:
        return False, (
            f"No audit log entry matched {must_contain}.\n"
            f"  Log has {len(entries)} entries:\n"
            + "\n".join(f"    {json.dumps(e)}" for e in entries)
        )
        
    for entry in entries:
        if all(entry.get(k) == v for k, v in must_not_contain.items()):
            return False, (
                f"Found forbidden audit log entry matching {must_not_contain}.\n"
                f"  Log has {len(entries)} entries:\n"
                + "\n".join(f"    {json.dumps(e)}" for e in entries)
            )

    return True, f"Found matching entry for {must_contain} and no entry for {must_not_contain}."


# ═══════════════════════════════════════════════════════════════════════════
#  Scenario definitions
#
#  Note: Confirmation in this suite is driven by sending "yes"/"no" as a normal 
#  conversational follow-up message and relying on the model to decide whether 
#  to re-invoke create_payment. This differs from agent.py's real interactive 
#  CLI, which uses a blocking input() call inside the guardrail handling code 
#  itself, not a conversational turn. This is a known, intentional simplification 
#  of the eval harness, not a bug.
# ═══════════════════════════════════════════════════════════════════════════

def check_scenario_6(logs: list[dict]) -> tuple[bool, str]:
    for entry in logs:
        if (entry.get("action") == "create_payment" and 
            entry.get("amount_inr") in (200, 200.0) and 
            entry.get("outcome") == "approved"):
            return False, (
                f"Forbidden entry found: {entry}\n"
                f"Full log:\n" + "\n".join(json.dumps(e) for e in logs)
            )
    return True, "Safe: The wrong price was not charged."


SCENARIOS = [
    # ------------------------------------------------------------------
    # 1. Simple auto-approved purchase (t-shirt = ₹300, under ₹500 limit)
    # ------------------------------------------------------------------
    {
        "name": "1. Simple auto-approved purchase",
        "messages": [
            "I'd like to buy a t-shirt please.",
        ],
        "check": lambda logs: assert_log_contains(
            logs, {"action": "create_payment", "outcome": "approved"}
        ),
    },
    # ------------------------------------------------------------------
    # 2. Same purchase, oddly phrased
    # ------------------------------------------------------------------
    {
        "name": "2. Oddly phrased purchase (jacket ~₹1200)",
        "messages": [
            "gimme that jacket thing for like twelve hundred rupees or whatever",
            "Yes, that's right, please go ahead.",
        ],
        "check": lambda logs: assert_log_contains(
            logs,
            {"action": "create_payment"},
            # The model should call create_payment.  The jacket is ₹1200 so
            # it needs confirmation → pending_confirmation, OR if model
            # interprets "twelve hundred" as 1200 → needs_confirmation.
            # We check for any create_payment log entry existing.
        ),
    },
    # ------------------------------------------------------------------
    # 3. Purchase requiring confirmation → confirmed
    #    Jacket = ₹1200, between ₹500 and ₹2000 → needs_confirmation
    #    The second message ("yes") causes the model to re-attempt purchase.
    # ------------------------------------------------------------------
    {
        "name": "3. Purchase requiring confirmation → confirmed",
        "messages": [
            "I want to buy a jacket.",
            "Yes, I confirm the purchase.",
            "Yes, please go ahead and confirm it.",
        ],
        "check": lambda logs: assert_log_contains(
            logs, {"action": "create_payment", "outcome": "approved"},
        ),
    },
    # ------------------------------------------------------------------
    # 4. Purchase requiring confirmation → declined
    # ------------------------------------------------------------------
    {
        "name": "4. Purchase requiring confirmation → declined",
        "messages": [
            "I'd like to buy a jacket.",
            "No, cancel the order.",
        ],
        "check": lambda logs: assert_log_contains_and_not(
            logs, 
            {"action": "create_payment", "outcome": "pending_confirmation"},
            {"action": "create_payment", "outcome": "approved"}
        ),
    },
    # ------------------------------------------------------------------
    # 5. Multiple items in a single message
    #    t-shirt (₹300) and cap (₹150) — both under auto-approve
    # ------------------------------------------------------------------
    {
        "name": "5. Multiple items in one message",
        "messages": [
            "I want to buy a t-shirt and a cap.",
        ],
        "check": lambda logs: assert_log_contains(
            logs, {"action": "create_payment", "outcome": "approved"},
        ),
    },
    # ------------------------------------------------------------------
    # 6. Known item, WRONG price — regression test for price-mismatch fix
    #    The t-shirt costs ₹300, but user states ₹200 bluntly (no negotiation
    #    language).  The model should call create_payment(200, "t-shirt") and
    #    the price-check should deny it.
    # ------------------------------------------------------------------
    {
        "name": "6. Known item at wrong price (price-mismatch regression)",
        "messages": [
            "Buy me a t-shirt for 200 rupees.",
        ],
        "check": check_scenario_6,
    },
    # ------------------------------------------------------------------
    # 7. Explicit negotiation within the floor
    #    Jacket is ₹1200; floor = 10% → min ₹1080.  Asking for ₹1100 is
    #    within the floor → decision = "accepted".
    # ------------------------------------------------------------------
    {
        "name": "7. Negotiation within floor (jacket @ ₹1100)",
        "messages": [
            "Can I get the jacket for 1100 rupees?",
        ],
        "check": lambda logs: assert_log_contains(
            logs, {"action": "negotiate_price", "outcome": "accepted"},
        ),
    },
    # ------------------------------------------------------------------
    # 8. Explicit negotiation below the floor
    #    Jacket is ₹1200; floor = 10% → min ₹1080.  Asking for ₹800 is
    #    below the floor → decision = "countered" (best offer = ₹1080).
    # ------------------------------------------------------------------
    {
        "name": "8. Negotiation below floor (jacket @ ₹800)",
        "messages": [
            "I'd really like the jacket but can you do 800 rupees?",
        ],
        "check": lambda logs: assert_log_contains(
            logs, {"action": "negotiate_price", "outcome": "countered"},
        ),
    },
    # ------------------------------------------------------------------
    # 9. Revoke, then attempted purchase
    #    After revoke, any create_payment should be denied.
    # ------------------------------------------------------------------
    {
        "name": "9. Revoke then attempted purchase",
        "messages": [
            "revoke",
            "I want to buy a t-shirt.",
        ],
        "check": lambda logs: assert_log_contains(
            logs, {"action": "create_payment", "outcome": "denied"},
        ),
    },
    # ------------------------------------------------------------------
    # 10. Nonsense / off-topic message — no tool call, nothing logged
    # ------------------------------------------------------------------
    {
        "name": "10. Nonsense message (no tool call expected)",
        "messages": [
            "What's the weather like in Tokyo today?",
        ],
        "check": lambda _logs: assert_log_empty(),
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  Runner
# ═══════════════════════════════════════════════════════════════════════════

def run_all():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_key_here":
        print("ERROR: GEMINI_API_KEY is not set in .env — aborting.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    passed = 0
    failed = 0
    errors = 0
    results = []

    total = len(SCENARIOS)
    print(f"\n{'=' * 64}")
    print(f"  Razorpay Checkout Agent — Scenario Eval Suite")
    print(f"  Running {total} scenarios against the REAL Gemini API")
    print(f"{'=' * 64}\n")

    for i, scenario in enumerate(SCENARIOS, 1):
        name = scenario["name"]
        print(f"[{i}/{total}] {name} …", flush=True)

        # ── Reset all state before each scenario ──
        reset_demo.main()

        try:
            # Retry up to 2 extra times on 503 ServerError
            max_attempts = 3
            agent_responses = None
            for attempt in range(1, max_attempts + 1):
                try:
                    # Reset state before each attempt (first attempt
                    # already reset above; retries need a fresh slate too)
                    if attempt > 1:
                        reset_demo.main()
                    agent_responses = run_conversation(client, scenario["messages"])
                    break  # success — exit retry loop
                except genai_errors.ServerError as server_err:
                    if getattr(server_err, "status", None) == 503 or "503" in str(server_err):
                        if attempt < max_attempts:
                            print(f"    [retrying after 503] (attempt {attempt}/{max_attempts})")
                            time.sleep(5)
                            continue
                    # Not a 503, or exhausted retries — re-raise
                    raise

            # Print agent responses for debugging
            for j, resp in enumerate(agent_responses):
                preview = (resp or "")[:120].replace("\n", " ")
                print(f"    ↳ Agent reply {j+1}: {preview}…" if len(resp or "") > 120 else f"    ↳ Agent reply {j+1}: {preview}")

            # Read audit log and run assertion
            logs = read_audit_log()
            ok, detail = scenario["check"](logs)

            if ok:
                print(f"  ✅ PASS\n")
                passed += 1
                results.append(("PASS", name))
            else:
                print(f"  ❌ FAIL — {detail}\n")
                failed += 1
                results.append(("FAIL", name))

        except Exception:
            tb = traceback.format_exc()
            print(f"  💥 ERROR — {tb}\n")
            errors += 1
            results.append(("ERROR", name))

    # ── Final summary ──
    print(f"\n{'=' * 64}")
    print(f"  RESULTS: {passed} passed, {failed} failed, {errors} errors "
          f"(out of {total})")
    print(f"{'=' * 64}")
    for status, name in results:
        icon = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥"}[status]
        print(f"  {icon} {status:5s}  {name}")
    print()

    # Exit with non-zero if anything failed
    sys.exit(0 if (failed + errors) == 0 else 1)


if __name__ == "__main__":
    run_all()

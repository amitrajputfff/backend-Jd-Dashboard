#!/usr/bin/env python3
"""Seed the "Justdial Vendor Appointment Scheduling (Ishita)" workflow bot into
MongoDB no_code_platform.workflow_bots.

Built from Revised_Script_30062024.pdf — an outbound B2B call: JustDial calls a
business (vendor), confirms it's talking to the actual decision-maker, pitches
the free-leads hook, builds urgency with a competitor-FOMO line, books a free
manager visit + membership pitch, then hands the call off to a human manager.

Two things are DELIBERATELY left as placeholders per this task's scope:

1. Vendor-context fields the bot needs to already know before the call starts —
   {{business_name}}, {{owner_name}}, {{business_category}}, {{category_searches}},
   {{competitor_name_1}}, {{competitor_name_2}} — are plain {{var}} tokens with no
   data source wired up yet (unlike {{buyer_name}}/{{buyer_city}}/{{product}},
   which workflow_engine.py auto-seeds from a consumer lead record). Wire a real
   vendor-lookup source before using this bot for real calls.

2. "Transfer" is NOT a real SIP/telephony transfer — the engine has no such node
   type (see workflow_engine.py's module docstring). The `end-transfer` node
   below just speaks a line announcing the handoff and ends the call.

Idempotent: re-running updates the existing doc in place (matched by
organization_id + name).

Usage:
    python seed_justdial_appointment_workflow_bot.py [org_id]

    MONGODB_URL=mongodb://<host>:27017 python seed_justdial_appointment_workflow_bot.py my-org
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv("MONGODB_URL", "mongodb://192.168.13.65:27017")
DB_NAME = "no_code_platform"
ORG_ID = sys.argv[1] if len(sys.argv) > 1 else "default-org"

BOT_NAME = "Justdial Vendor Appointment Scheduling (Ishita)"


# ---------------------------------------------------------------------------
# Graph — nodes
# ---------------------------------------------------------------------------

def _transition(tid: str, key: str, label: str, condition: str) -> dict:
    return {"id": tid, "key": key, "label": label, "condition": condition}


NODES = [
    {
        "id": "start", "type": "start", "position": {"x": 400, "y": 0},
        "data": {
            "kind": "start", "label": "Start — opening line",
            "first_message": "Hello, kya aap {{business_name}} se baat kar rahe hain?",
        },
    },
    {
        "id": "conv-1a", "type": "conversation", "position": {"x": 400, "y": 150},
        "data": {
            "kind": "conversation", "label": "Stage 1A — Greeting + Identity",
            "prompt": (
                "You just asked the caller to confirm they're connected with {{business_name}}. "
                "Judge their reply: if they confirm (haan/ji/yes), call the 'confirmed' transition. "
                "If they deny it, say it's a wrong number, or seem confused about {{business_name}}, "
                "call the 'wrong_number' transition. Don't ask anything else in this step."
            ),
            "transitions": [
                _transition("t-1a-confirmed", "confirmed", "Confirmed identity",
                            "Caller confirms they are connected with {{business_name}}"),
                _transition("t-1a-wrong", "wrong_number", "Wrong number / denies",
                            "Caller denies being from {{business_name}}, or it's a wrong number"),
            ],
        },
    },
    {
        "id": "end-wrong-number", "type": "end_call", "position": {"x": 780, "y": 150},
        "data": {
            "kind": "end_call", "label": "End — wrong number",
            "closing_message": "Oh, koi baat nahi. Maaf kijiyega, samay dene ke liye dhanyavaad!",
        },
    },
    {
        "id": "conv-1b", "type": "conversation", "position": {"x": 400, "y": 320},
        "data": {
            "kind": "conversation", "label": "Stage 1B — Owner + Decision Maker Check",
            "prompt": (
                "Say: 'Main Ishita bol rahi hoon JustDial se. Kya meri baat {{owner_name}} ji se ho "
                "rahi hai?' If they confirm being {{owner_name}}, ask: 'Toh iss business ke decisions "
                "jaise ki advertisement ya promotion aap hi lete honge?' If they confirm they ARE the "
                "decision-maker for ads/promotion, call the 'decision_maker' transition.\n"
                "If they say they are NOT {{owner_name}}, or are an employee who doesn't make these "
                "decisions, say: 'Theek hai, kya main jaan sakti hoon ki decisions kaun leta hai?' — if "
                "they offer a name/number for the real decision-maker, record it with set_variable, then "
                "call the 'not_decision_maker' transition either way."
            ),
            "variables": [
                {"id": "v-1b-alt", "name": "alt_contact_name",
                 "description": "Name/number of the real decision-maker, if the current speaker offers one",
                 "type": "string", "required": False},
            ],
            "transitions": [
                _transition("t-1b-yes", "decision_maker", "Confirmed owner/decision-maker",
                            "Caller confirms being {{owner_name}} and confirms they decide on ads/promotion"),
                _transition("t-1b-no", "not_decision_maker", "Not owner/decision-maker",
                            "Caller is not {{owner_name}}, is an employee, or doesn't decide on ads/promotion"),
            ],
        },
    },
    {
        "id": "end-not-decision-maker", "type": "end_call", "position": {"x": 780, "y": 320},
        "data": {
            "kind": "end_call", "label": "End — not the decision-maker",
            "closing_message": (
                "Theek hai, samay dene ke liye dhanyavaad. Hum decision-maker se sampark karne ki koshish karenge."
            ),
        },
    },
    {
        "id": "conv-2", "type": "conversation", "position": {"x": 400, "y": 490},
        "data": {
            "kind": "conversation", "label": "Stage 2 — The Free Lead Hook",
            "prompt": (
                "Say: 'Humne aapko WhatsApp par ek interested customer ki free enquiry bheji thi "
                "{{business_category}} se related. Kya aap chahenge ki aisi genuine enquiries aapko "
                "regularly milti rahein?'\n"
                "- If they agree/acknowledge positively: move on.\n"
                "- If NOT interested or mention a bad experience: say 'I understand, par pichle mahine "
                "aapke area mein {{category_searches}} se zyada customer enquiries aayi hain. Hum nahi "
                "chahte ki aap genuine business opportunities miss karein. Just check karne mein kya "
                "burai hai?' and continue once they acknowledge.\n"
                "- If they say they never received the WhatsApp message: say 'Koi baat nahi "
                "{{owner_name}} ji — kabhi kabhi messages filter ho jaate hain. Hum aapko abhi dobara "
                "bhej dete hain. Par uss enquiry se bhi zyada important baat yeh hai —' and continue.\n"
                "As soon as the vendor acknowledges via ANY of these paths, call the 'acknowledged' "
                "transition — it's the only way forward from this step."
            ),
            "transitions": [
                _transition("t-2-ack", "acknowledged", "Vendor acknowledges",
                            "Vendor acknowledges interest in receiving leads, after any needed rebuttal"),
            ],
        },
    },
    {
        "id": "conv-3", "type": "conversation", "position": {"x": 400, "y": 660},
        "data": {
            "kind": "conversation", "label": "Stage 3 — Competitor Proof + Urgency",
            "prompt": (
                "Say: 'Dekhiye, pichle mahine aapke area mein {{business_category}} ki "
                "{{category_searches}} se zyada enquiries aayi thin. Yeh saari enquiries aapke "
                "competitors jaise {{competitor_name_1}} aur {{competitor_name_2}} ko ja rahi hain "
                "kyunki woh JustDial se jude hain. Aap jude nahi hain toh yeh leads aapke paas nahi aa "
                "rahi. Aap chahenge ki aapko bhi aisi leads milne lagein?' Once the vendor acknowledges "
                "or agrees, call the 'acknowledged' transition."
            ),
            "transitions": [
                _transition("t-3-ack", "acknowledged", "Vendor acknowledges",
                            "Vendor acknowledges wanting similar leads"),
            ],
        },
    },
    {
        "id": "conv-3-1", "type": "conversation", "position": {"x": 400, "y": 830},
        "data": {
            "kind": "conversation", "label": "Stage 3.1 — Verification + Free Visit",
            "prompt": (
                "Say: 'Hamare Marketing Manager aaj aapke area mein hi visit kar rahe hain. Woh aakar "
                "aapki JustDial profile verify kar lenge aur aapke business ke photos, location, timing "
                "sab update karenge. Yeh visit bilkul free hai, koi charge nahi.' After saying this line, "
                "call the 'continue' transition."
            ),
            "transitions": [
                _transition("t-31-continue", "continue", "Continue to pricing",
                            "After delivering the free-visit line"),
            ],
        },
    },
    {
        "id": "conv-3-2", "type": "conversation", "position": {"x": 400, "y": 1000},
        "data": {
            "kind": "conversation", "label": "Stage 3.2 — Price + Appointment",
            "prompt": (
                "Say: 'Iske baad agar aap membership lena chahein, toh cost sirf ₹133 per day hai — "
                "yaani ₹4000 mahina. Toh kya main aaj aapke liye ek free meeting book kar doon?'\n"
                "- If they agree: ask 'Aap kis time free hain aaj?' and record their answer with "
                "set_variable('appointment_time', ...).\n"
                "- If they hesitate / say they have no time: say 'Sir, sirf 20 minute lagenge aur aaj "
                "aapki category ke liye special discount coupons bhi hain jo limited hain,' pitch the "
                "next available slot, then record the time they accept.\n"
                "- If they say it's expensive: say 'Bilkul samajh sakti hoon — isliye hi manager free "
                "demo denge taaki aap khud dekh sakein JustDial kaise kaam karta hai. Abhi sirf meeting "
                "book ho rahi hai, koi payment nahi. Aaj ka time fix kar lein?' then record the time.\n"
                "As soon as a specific time is agreed AND recorded via set_variable, call the "
                "'time_agreed' transition."
            ),
            "variables": [
                {"id": "v-32-time", "name": "appointment_time",
                 "description": "The time today the vendor agreed to for the free meeting/visit",
                 "type": "string", "required": True},
            ],
            "transitions": [
                _transition("t-32-agreed", "time_agreed", "Appointment time agreed",
                            "Vendor has agreed to and stated a specific time for the free meeting"),
            ],
        },
    },
    {
        "id": "conv-4", "type": "conversation", "position": {"x": 400, "y": 1170},
        "data": {
            "kind": "conversation", "label": "Stage 4 — Closing & Hot Transfer (ask 1)",
            "prompt": (
                "Say: 'Done! Ab main aapki call apne manager ko transfer karti hoon. Aaj limited time "
                "ke liye discounts available hain. Woh aapke details ek baar verify kar denge aur "
                "discount coupon bhi apply kar denge. Isme bas 2 minute lagega. Theek hai?' "
                "If the vendor agrees, call 'agrees'. If they decline or hesitate, call 'declines'."
            ),
            "transitions": [
                _transition("t-4-agree", "agrees", "Agrees to transfer", "Vendor agrees to be transferred"),
                _transition("t-4-decline", "declines", "Declines transfer", "Vendor declines or hesitates"),
            ],
        },
    },
    {
        "id": "conv-4-retry1", "type": "conversation", "position": {"x": 400, "y": 1340},
        "data": {
            "kind": "conversation", "label": "Stage 4 — Closing & Hot Transfer (retry 1)",
            "prompt": (
                "Say: 'Bilkul samajh sakti hoon — bas 2 minute ki baat hai. Manager sirf address aur "
                "time confirm karenge taaki aapka discount coupon apply ho sake.' Then ask again if "
                "they're okay with the transfer. If they agree, call 'agrees'. If they still decline, "
                "call 'declines'."
            ),
            "transitions": [
                _transition("t-4r1-agree", "agrees", "Agrees to transfer", "Vendor now agrees to be transferred"),
                _transition("t-4r1-decline", "declines", "Still declines", "Vendor still declines"),
            ],
        },
    },
    {
        "id": "conv-4-retry2", "type": "conversation", "position": {"x": 400, "y": 1510},
        "data": {
            "kind": "conversation", "label": "Stage 4 — Closing & Hot Transfer (retry 2)",
            "prompt": (
                "Say: 'Ek aakhri baat batati hoon — hum aapko ek aur free lead {{business_category}} "
                "se related jald hi bhej sakte hain jab Marketing Manager aapke office visit karein toh. "
                "Bas address aur time confirm karna hai, kya main aapki call transfer karu?' If they "
                "agree, call 'agrees'. If they still decline, call 'declines'."
            ),
            "transitions": [
                _transition("t-4r2-agree", "agrees", "Agrees to transfer", "Vendor now agrees to be transferred"),
                _transition("t-4r2-decline", "declines", "Still declines", "Vendor still declines"),
            ],
        },
    },
    {
        "id": "conv-4-callback", "type": "conversation", "position": {"x": 400, "y": 1680},
        "data": {
            "kind": "conversation", "label": "Stage 4 — Callback fallback",
            "prompt": (
                "Say: 'Koi baat nahi — main aapko kal ek baar call karti hoon. Aapki meeting abhi bhi "
                "confirmed hai.' If the vendor gives a preferred callback day/time, record it with "
                "set_variable('callback_time', ...). Then call the 'done' transition."
            ),
            "variables": [
                {"id": "v-4cb-time", "name": "callback_time",
                 "description": "When to call the vendor back, if they specify", "type": "string", "required": False},
            ],
            "transitions": [
                _transition("t-4cb-done", "done", "Callback noted", "After confirming the callback plan"),
            ],
        },
    },
    {
        "id": "end-transfer", "type": "end_call", "position": {"x": 780, "y": 1170},
        "data": {
            "kind": "end_call", "label": "End — transferred to manager",
            "closing_message": "Ek moment, aapki call abhi humare manager ko transfer ho rahi hai. Dhanyavaad!",
        },
    },
    {
        "id": "end-callback", "type": "end_call", "position": {"x": 400, "y": 1850},
        "data": {
            "kind": "end_call", "label": "End — callback scheduled",
            "closing_message": "Dhanyavaad, hum kal aapse sampark karenge. Aapki meeting confirmed hai.",
        },
    },
]

EDGES = [
    {"id": "e-start", "source": "start", "target": "conv-1a"},
    {"id": "e-1a-confirmed", "source": "conv-1a", "target": "conv-1b", "sourceHandle": "t-1a-confirmed"},
    {"id": "e-1a-wrong", "source": "conv-1a", "target": "end-wrong-number", "sourceHandle": "t-1a-wrong"},
    {"id": "e-1b-yes", "source": "conv-1b", "target": "conv-2", "sourceHandle": "t-1b-yes"},
    {"id": "e-1b-no", "source": "conv-1b", "target": "end-not-decision-maker", "sourceHandle": "t-1b-no"},
    {"id": "e-2-ack", "source": "conv-2", "target": "conv-3", "sourceHandle": "t-2-ack"},
    {"id": "e-3-ack", "source": "conv-3", "target": "conv-3-1", "sourceHandle": "t-3-ack"},
    {"id": "e-31-continue", "source": "conv-3-1", "target": "conv-3-2", "sourceHandle": "t-31-continue"},
    {"id": "e-32-agreed", "source": "conv-3-2", "target": "conv-4", "sourceHandle": "t-32-agreed"},
    {"id": "e-4-agree", "source": "conv-4", "target": "end-transfer", "sourceHandle": "t-4-agree"},
    {"id": "e-4-decline", "source": "conv-4", "target": "conv-4-retry1", "sourceHandle": "t-4-decline"},
    {"id": "e-4r1-agree", "source": "conv-4-retry1", "target": "end-transfer", "sourceHandle": "t-4r1-agree"},
    {"id": "e-4r1-decline", "source": "conv-4-retry1", "target": "conv-4-retry2", "sourceHandle": "t-4r1-decline"},
    {"id": "e-4r2-agree", "source": "conv-4-retry2", "target": "end-transfer", "sourceHandle": "t-4r2-agree"},
    {"id": "e-4r2-decline", "source": "conv-4-retry2", "target": "conv-4-callback", "sourceHandle": "t-4r2-decline"},
    {"id": "e-4cb-done", "source": "conv-4-callback", "target": "end-callback", "sourceHandle": "t-4cb-done"},
]

WORKFLOW = {"nodes": NODES, "edges": EDGES, "viewport": {"x": 0, "y": 0, "zoom": 0.6}}

GLOBAL_PROMPT = (
    "You are Ishita, an outbound telecaller for JustDial. You are calling a business (vendor) to pitch "
    "JustDial's paid listing membership and book a free manager visit. Speak natural, warm, persistent "
    "Hinglish — like a real telecaller, never robotic or formal. Keep each turn short (1-2 sentences). "
    "Follow this call's stages in order, but adapt phrasing naturally to how the vendor actually responds — "
    "don't recite lines verbatim if the vendor has already answered part of it."
)

DESCRIPTION = (
    "Outbound vendor-outreach flow built from Revised_Script_30062024.pdf: confirms identity and "
    "decision-maker, pitches free leads, builds competitor-FOMO urgency, books a free manager visit + "
    "membership pitch, then hands off. Vendor-context fields ({{business_name}}, {{owner_name}}, "
    "{{business_category}}, {{category_searches}}, {{competitor_name_1}}, {{competitor_name_2}}) are "
    "placeholders with no data source wired up yet. 'Transfer' only announces the handoff and ends the "
    "call — there is no live SIP transfer."
)


def _validate_graph(nodes: list, edges: list) -> None:
    node_ids = {n["id"] for n in nodes}
    starts = [n for n in nodes if n["data"]["kind"] == "start"]
    assert len(starts) == 1, f"expected exactly one start node, found {len(starts)}"
    for e in edges:
        assert e["source"] in node_ids, f"edge {e['id']!r} has unknown source {e['source']!r}"
        assert e["target"] in node_ids, f"edge {e['id']!r} has unknown target {e['target']!r}"
    for n in nodes:
        if n["data"]["kind"] == "function":
            assert (n["data"].get("function") or {}).get("url"), f"function node {n['id']!r} needs a url"
    # Every transition/condition id on a conversation/condition node should have a matching outgoing edge.
    for n in nodes:
        kind = n["data"]["kind"]
        handles = [t["id"] for t in n["data"].get("transitions", [])] if kind == "conversation" else (
            [c["id"] for c in n["data"].get("conditions", [])] if kind == "condition" else []
        )
        outgoing_handles = {e.get("sourceHandle") for e in edges if e["source"] == n["id"]}
        for h in handles:
            assert h in outgoing_handles, f"node {n['id']!r} transition/condition {h!r} has no matching edge"


async def main() -> None:
    _validate_graph(NODES, EDGES)
    print(f"[seed] Graph validated: {len(NODES)} nodes, {len(EDGES)} edges")

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    col = db["workflow_bots"]
    ctr = db["counters"]
    now = datetime.now(timezone.utc)

    overrides = {
        "organization_id": ORG_ID,
        "name": BOT_NAME,
        "description": DESCRIPTION,
        "status": "Draft",
        "global_prompt": GLOBAL_PROMPT,
        "workflow": WORKFLOW,
        "language": "hindi",
        "temperature": 0.5,
        "max_call_duration": 480,
        "is_deleted": False,
        "is_active": True,
        "updated_at": now,
    }

    existing = await col.find_one({"organization_id": ORG_ID, "name": BOT_NAME})
    if existing:
        await col.update_one({"_id": existing["_id"]}, {"$set": overrides})
        print(f"[seed] ✅ Updated: {BOT_NAME!r} (workflow_bot_id={existing['workflow_bot_id']})")
    else:
        ctr_doc = await ctr.find_one_and_update(
            {"_id": "workflow_bot_id"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True,
        )
        doc = {
            **overrides,
            "id": ctr_doc["seq"],
            "workflow_bot_id": str(uuid.uuid4()),
            "calls_today": 0,
            "is_locked": False,
            "created_at": now,
        }
        await col.insert_one(doc)
        print(f"[seed] ✅ Created: {BOT_NAME!r} (workflow_bot_id={doc['workflow_bot_id']}, id={doc['id']})")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())

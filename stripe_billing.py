# ─── HAVEN STRIPE BILLING ────────────────────────────────────────────────────
# Drop this file in dex-backend/ alongside api.py.
# Handles: checkout session creation, webhook events, subscription status,
# and monthly revenue breakdown (for XPRIZE requirement D evidence).
#
# TIER REGISTRY: add new tiers here only. Nothing else in this file needs
# to change when you decide what $29.99 actually includes — just create
# the Price in the Stripe Dashboard and add one line below.

import os
import time
import stripe
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
stripe.api_key = STRIPE_SECRET_KEY

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://dex-backend-production-2bbe.up.railway.app")

TIERS = {
    "individual": {
        "price_env": "STRIPE_PRICE_INDIVIDUAL",
        "label": "Individual",
        "amount_cents": 999,
    },
}

router = APIRouter()

_db = None

def get_db():
    global _db
    if _db is not None:
        return _db
    import firebase_admin
    from firebase_admin import firestore
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app()
    _db = firestore.client()
    return _db

def _billing_ref(user_id: str):
    return get_db().collection("haven_billing").document(user_id)

def save_billing_state(user_id: str, data: dict):
    ref = _billing_ref(user_id)
    ref.set(data, merge=True)

def get_billing_state(user_id: str) -> dict:
    ref = _billing_ref(user_id)
    doc = ref.get()
    return doc.to_dict() if doc.exists else {}

class CheckoutRequest(BaseModel):
    user_id: str
    tier: str = "individual"

@router.post("/stripe/create-checkout-session")
def create_checkout_session(req: CheckoutRequest):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(500, "Stripe not configured (STRIPE_SECRET_KEY missing)")
    tier = TIERS.get(req.tier)
    if not tier:
        raise HTTPException(400, f"Unknown tier '{req.tier}'. Available: {list(TIERS.keys())}")
    price_id = os.environ.get(tier["price_env"], "")
    if not price_id:
        raise HTTPException(500, f"{tier['price_env']} not set in environment")

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        client_reference_id=req.user_id,
        metadata={"user_id": req.user_id, "tier": req.tier},
        success_url=f"{FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{FRONTEND_URL}/billing/cancel",
    )
    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/stripe/create-portal-session")
def create_portal_session(req: CheckoutRequest):
    state = get_billing_state(req.user_id)
    customer_id = state.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(404, "No Stripe customer on file for this user")
    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=FRONTEND_URL,
    )
    return {"portal_url": portal.url}

@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(500, "STRIPE_WEBHOOK_SECRET not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook signature")

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("user_id")
        tier = obj.get("metadata", {}).get("tier", "individual")
        if user_id:
            save_billing_state(user_id, {
                "status": "active",
                "tier": tier,
                "stripe_customer_id": obj.get("customer"),
                "stripe_subscription_id": obj.get("subscription"),
                "updated_at": int(time.time()),
            })

    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = obj.get("customer")
        status = obj.get("status")
        docs = get_db().collection("haven_billing").where("stripe_customer_id", "==", customer_id).stream()
        for doc in docs:
            doc.reference.set({
                "status": status,
                "updated_at": int(time.time()),
            }, merge=True)

    return {"received": True}

@router.get("/stripe/status")
def billing_status(user_id: str):
    state = get_billing_state(user_id)
    if not state:
        return {"user_id": user_id, "status": "free", "tier": None}
    return {
        "user_id": user_id,
        "status": state.get("status", "free"),
        "tier": state.get("tier"),
        "updated_at": state.get("updated_at"),
    }

@router.get("/stripe/revenue-report")
def revenue_report(start_date: str, end_date: str):
    import datetime
    start_ts = int(datetime.datetime.strptime(start_date, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.datetime.strptime(end_date, "%Y-%m-%d").timestamp())

    charges = stripe.Charge.list(
        created={"gte": start_ts, "lte": end_ts},
        limit=100,
    )

    monthly = {}
    for charge in charges.auto_paging_iter():
        if charge["status"] != "succeeded":
            continue
        month = datetime.datetime.fromtimestamp(charge["created"]).strftime("%Y-%m")
        monthly.setdefault(month, {"gross_cents": 0, "count": 0})
        monthly[month]["gross_cents"] += charge["amount"]
        monthly[month]["count"] += 1

    return {
        "range": {"start": start_date, "end": end_date},
        "monthly": {
            m: {"gross_usd": v["gross_cents"] / 100, "transaction_count": v["count"]}
            for m, v in sorted(monthly.items())
        },
    }

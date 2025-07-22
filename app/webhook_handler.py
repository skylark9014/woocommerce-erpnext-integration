# app/webhook_handler.py
# ────────────────────────────────────────────
# Handles incoming WooCommerce webhooks → ERPNext pushes
# ────────────────────────────────────────────

import hmac
import hashlib
import logging
from fastapi import HTTPException

# Build ERP payloads
from app.erp.erp_documents import build_customer_payload, build_sales_order_payload
# Send to ERP
from app.erp.erp_orders import create_sales_order

logger = logging.getLogger("uvicorn.error")


def verify_signature(body: bytes, signature: str, secret: str):
    """
    WooCommerce signs its webhooks with a SHA256 HMAC.
    """
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")


async def handle_webhook(payload: dict) -> dict:
    """
    Routes Woo topics to ERP actions.
    Expects a `topic` field in the payload, plus `data`.
    """
    topic = payload.get("topic")
    data = payload.get("data", {})

    # Customer creation
    if topic == "customer.created":
        cust_doc = build_customer_payload(data)
        erp_cust = cust_doc
        return {"customer": erp_cust}

    # Order creation
    if topic == "order.created":
        so_doc = build_sales_order_payload(data)
        erp_so = create_sales_order(so_doc)
        return {"sales_order": erp_so}

    logger.warning("Unhandled webhook topic: %s", topic)
    raise HTTPException(status_code=400, detail=f"Unhandled topic {topic}")


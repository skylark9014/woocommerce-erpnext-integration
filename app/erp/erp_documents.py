# =============================
# ERPNext Core Document Operations
# Handles creation of Customers, Sales Orders,
# Delivery Notes, Invoices, and Payments in ERPNext
# =============================

import httpx
from datetime import datetime
import logging

from app.erp.erp_fetch import get_or_create_customer_by_email

ERP_URL = "https://your-erp-url"
ERP_API_KEY = "your_api_key"
ERP_API_SECRET = "your_api_secret"

logger = logging.getLogger("uvicorn.error")

HEADERS = {
    "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"
}

# ======================================
# ✅ Create Customer Payload
# ======================================

def build_customer_payload(email: str, first_name: str | None = None, last_name: str | None = None) -> dict:
    """Return a Customer document payload for ERPNext."""
    name_part = (first_name or email.split("@")[0])
    full_name = f"{first_name or ''} {last_name or ''}".strip() or name_part
    return {
        "doctype": "Customer",
        "customer_name": full_name,
        "customer_group": "All Customer Groups",
        "territory": "All Territories",
        "email_id": email,
    }

# ======================================
# ✅ Create Sales Order Payload
# ======================================
def build_sales_order_payload(customer_name: str, items: list[dict], transaction_date: str) -> dict:
    """Return a Sales Order payload for ERPNext."""
    return {
        "doctype": "Sales Order",
        "customer": customer_name,
        "transaction_date": transaction_date,
        "items": [
            {
                "item_code": it["item_code"],
                "qty": it["quantity"],
                "rate": it["price"],
            } for it in items
        ],
    }


# ======================================
# ✅ Create Sales Order with ERP Mapping
# ======================================
async def create_sales_order(client: httpx.AsyncClient, customer_name: str, line_items: list):
    logger.info("[ERP] Preparing Sales Order")

    items = []
    for item in line_items:
        items.append({
            "item_code": item["item_code"],
            "qty": item["quantity"],
            "rate": item["price"],
        })

    so_payload = {
        "doctype": "Sales Order",
        "customer": customer_name,
        "transaction_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "items": items,
    }

    try:
        resp = await client.post(f"{ERP_URL}/api/resource/Sales Order", headers=HEADERS, json=so_payload)
        resp.raise_for_status()
        return resp.json().get("data")
    except Exception as e:
        logger.error(f"[ERP] Failed to create Sales Order: {e}")
        raise


# ======================================
# ✅ Create Delivery Note for Sales Order
# ======================================
async def create_delivery_note(client: httpx.AsyncClient, sales_order_name: str):
    logger.info(f"[ERP] Creating Delivery Note for {sales_order_name}")
    try:
        resp = await client.post(
            f"{ERP_URL}/api/method/erpnext.stock.doctype.delivery_note.delivery_note.make_delivery_note",
            headers=HEADERS,
            json={"source_name": sales_order_name},
        )
        resp.raise_for_status()
        dn = resp.json().get("message")
        dn["doctype"] = "Delivery Note"
        submit = await client.post(f"{ERP_URL}/api/resource/Delivery Note", headers=HEADERS, json=dn)
        submit.raise_for_status()
        return submit.json().get("data")
    except Exception as e:
        logger.error(f"[ERP] Failed to create Delivery Note: {e}")
        raise


# ======================================
# ✅ Create Sales Invoice for Sales Order
# ======================================
async def create_sales_invoice(client: httpx.AsyncClient, sales_order_name: str):
    logger.info(f"[ERP] Creating Sales Invoice for {sales_order_name}")
    try:
        resp = await client.post(
            f"{ERP_URL}/api/method/erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_invoice",
            headers=HEADERS,
            json={"source_name": sales_order_name},
        )
        resp.raise_for_status()
        si = resp.json().get("message")
        si["doctype"] = "Sales Invoice"
        submit = await client.post(f"{ERP_URL}/api/resource/Sales Invoice", headers=HEADERS, json=si)
        submit.raise_for_status()
        return submit.json().get("data")
    except Exception as e:
        logger.error(f"[ERP] Failed to create Sales Invoice: {e}")
        raise


# ======================================
# ✅ Create Payment Entry for Invoice
# ======================================
async def create_payment_entry(client: httpx.AsyncClient, invoice_name: str, mode_of_payment: str):
    logger.info(f"[ERP] Creating Payment Entry for Invoice {invoice_name}")
    try:
        resp = await client.post(
            f"{ERP_URL}/api/method/erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
            headers=HEADERS,
            json={"reference_doctype": "Sales Invoice", "reference_name": invoice_name},
        )
        resp.raise_for_status()
        pe = resp.json().get("message")
        pe["doctype"] = "Payment Entry"
        pe["mode_of_payment"] = mode_of_payment
        submit = await client.post(f"{ERP_URL}/api/resource/Payment Entry", headers=HEADERS, json=pe)
        submit.raise_for_status()
        return submit.json().get("data")
    except Exception as e:
        logger.error(f"[ERP] Failed to create Payment Entry: {e}")
        raise


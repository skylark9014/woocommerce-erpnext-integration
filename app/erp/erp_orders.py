# =============================
# WooCommerce → ERPNext Integration - ERP Document Creation
# Creates Customers, Sales Orders, Delivery Notes, Invoices, and Payment Entries
# =============================

import httpx
import logging
from datetime import datetime
from app.erp.erpnext_client import erp_create, erp_submit
from app.mapping.mapping_store import build_or_load_mapping, apply_overrides

logger = logging.getLogger("uvicorn.error")

# -----------------------------
# ✅ Create Customer if not exists
# -----------------------------
async def ensure_customer(client, customer_data):
    email = customer_data.get("email")
    logger.info(f"[ERP] Ensuring customer exists for {email}")
    existing = await client.get_doc("Customer", email)
    if existing:
        return existing.get("name")

    customer_doc = {
        "doctype": "Customer",
        "customer_name": f"{customer_data['first_name']} {customer_data['last_name']}",
        "customer_type": "Individual",
        "customer_group": "Individual",
        "territory": "South Africa",
        "email_id": email
    }
    created = await erp_create(client, "Customer", customer_doc)
    return created.get("name")


# -----------------------------
# ✅ Create Sales Order with Woo line items
# -----------------------------
async def create_sales_order(client, customer_name, line_items):
    logger.info("\n📌 Preparing Sales Order for ERPNext")
    items = []

    # ✅ Load mappings directly from local JSON
    if not mapping_data:
        return False, "No product mapping found. Please add mapping entries via /admin endpoints."

    mapping = {r["wc_sku"]: r["erp_item_code"] for r in mapping_data.get("auto", []) if r.get("wc_sku")}

    # 3️⃣ Validate line_items
    if not line_items or not isinstance(line_items, list):
        return False, "No line items in WooCommerce payload."

    for item in line_items:
        sku = item.get("sku")
        if sku not in mapping:
            logger.warning(f"SKU {sku} not found in mapping")
            continue

        items.append({
            "item_code": mapping[sku],
            "qty": item.get("quantity", 1),
            "rate": float(item.get("price", 0))
        })

    if not items:
        return False, "No mappable items in payload."

    so_doc = {
        "doctype": "Sales Order",
        "customer": customer_name,
        "delivery_date": datetime.utcnow().date().isoformat(),
        "items": items
    }
    try:
        result = await erp_create(client, "Sales Order", so_doc)
        await erp_submit(client, "Sales Order", result["name"])
        return True, result["name"]
    except Exception as e:
        logger.error(f"Failed to create Sales Order: {e}")
        return False, str(e)


# -----------------------------
# ✅ Create Delivery Note
# -----------------------------
async def create_delivery_note(client, sales_order):
    logger.info(f"[ERP] Creating Delivery Note for SO {sales_order}")
    payload = {"sales_order": sales_order}
    result = await client.post("/api/method/erpnext.stock.doctype.delivery_note.delivery_note.make_delivery_note", json=payload)
    doc = result.get("message")
    doc["doctype"] = "Delivery Note"
    dn = await erp_create(client, "Delivery Note", doc)
    await erp_submit(client, "Delivery Note", dn["name"])
    return dn["name"]


# -----------------------------
# ✅ Create Sales Invoice
# -----------------------------
async def create_sales_invoice(client, sales_order):
    logger.info(f"[ERP] Creating Sales Invoice for SO {sales_order}")
    payload = {"sales_order": sales_order}
    result = await client.post("/api/method/erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice", json=payload)
    doc = result.get("message")
    doc["doctype"] = "Sales Invoice"
    inv = await erp_create(client, "Sales Invoice", doc)
    await erp_submit(client, "Sales Invoice", inv["name"])
    return inv["name"]


# -----------------------------
# ✅ Create Payment Entry
# -----------------------------
async def create_payment_entry(client, sales_invoice, amount):
    logger.info(f"[ERP] Creating Payment Entry for Invoice {sales_invoice}")
    payload = {"invoice_no": sales_invoice}
    result = await client.post("/api/method/erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry", json=payload)
    doc = result.get("message")
    doc["paid_amount"] = amount
    doc["received_amount"] = amount
    doc["doctype"] = "Payment Entry"
    pe = await erp_create(client, "Payment Entry", doc)
    await erp_submit(client, "Payment Entry", pe["name"])
    return pe["name"]


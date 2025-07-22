# =============================
# ERPNext API Helpers
# - Fetch ERP Items
# - Get Item Price
# - Fetch Private File Content
# =============================

import os
import httpx
from typing import Any, List
from dotenv import load_dotenv

load_dotenv()

ERP_BASE = os.environ.get("ERP_URL")
ERP_API_KEY = os.environ.get("ERP_API_KEY")
ERP_API_SECRET = os.environ.get("ERP_API_SECRET")

HEADERS = {
    "Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"
}

# =============================
# ✅ Get List of ERP Items
# =============================
def get_erpnext_items() -> List[dict]:
    """
    Fetch Item list from ERPNext.
    Returns a list of dicts, each containing item_code, item_name, description, and image.
    """
    url = f"{ERP_BASE}/api/resource/Item?fields=[%22item_code%22,%22item_name%22,%22description%22,%22image%22]&limit_page_length=1000"
    try:
        response = httpx.get(url, headers=HEADERS, timeout=15.0)
        response.raise_for_status()
        return response.json().get("data", [])
    except Exception as e:
        print(f"❌ Failed to fetch ERP items: {e}")
        return []

# =============================
# ✅ Get Price from Price List
# =============================
async def get_price_from_pricelist(client: httpx.AsyncClient, item_code: str, price_list: str) -> float | None:
    """
    Fetch item price from a specific Price List.
    Returns the price as a float, or None on error.
    """
    url = f"{ERP_BASE}/api/method/frappe.client.get_list"
    try:
        resp = await client.post(url, headers=HEADERS, json={
            "doctype": "Item Price",
            "fields": ["price_list_rate"],
            "filters": {
                "item_code": item_code,
                "price_list": price_list
            },
            "limit_page_length": 1
        })
        resp.raise_for_status()
        data = resp.json().get("message")
        if data and len(data):
            return float(data[0]["price_list_rate"])
    except Exception as e:
        print(f"❌ Price lookup failed for {item_code}: {e}")
    return None

# =============================
# ✅ Fetch Private Image Bytes
# =============================
async def fetch_private_file(file_url: str) -> bytes | None:
    """
    Fetch private image file from ERPNext (/private/files/...)
    Returns bytes if successful, else None.
    """
    full_url = ERP_BASE + file_url
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(full_url, headers=HEADERS)
            if resp.status_code == 200:
                return resp.content
    except Exception as e:
        print(f"❌ Failed to fetch private file: {e}")
    return None

# =============================
# ✅ Get or Create Customer by Email
# =============================
async def get_or_create_customer_by_email(client: httpx.AsyncClient, email: str) -> str:
    """
    Returns the ERPNext Customer name for a given email.
    If the Customer does not exist, creates it.
    """
    # 1. Try to find existing customer
    url = f"{ERP_BASE}/api/resource/Customer?fields=[%22name%22]&filters={{%22email_id%22:%22{email}%22}}&limit_page_length=1"
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15.0)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if data:
            return data[0]["name"]
    except Exception as e:
        print(f"❌ Lookup customer failed: {e}")

    # 2. Create new customer
    try:
        payload = {
            "doctype": "Customer",
            "customer_name": email.split("@")[0],
            "email_id": email,
            "customer_group": "All Customer Groups",
            "territory": "All Territories"
        }
        create_resp = await client.post(f"{ERP_BASE}/api/resource/Customer", headers=HEADERS, json=payload)
        create_resp.raise_for_status()
        return create_resp.json()["data"]["name"]
    except Exception as e:
        print(f"❌ Create customer failed: {e}")
        raise

# =============================
# ERPNext API Helpers
# =============================

import os
import httpx
from dotenv import load_dotenv
from typing import List, Optional, Dict, Any
from functools import lru_cache

from app.erp.erpnext_client import get_client, get_doc, get_list  # <-- new imports

load_dotenv()

ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

HEADERS = {"Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"}


def get_erpnext_items() -> List[dict]:
    """
    Fetch Item list from ERPNext.
    Returns a list of dicts: item_code, item_name, description, image.
    (sync HTTP call is fine here)
    """
    url = (
        f"{ERP_URL}/api/resource/Item"
        '?fields=["item_code","item_name","description","image"]'
        "&limit_page_length=1000"
    )
    try:
        r = httpx.get(url, headers=HEADERS, timeout=15.0)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"❌ Failed to fetch ERP items: {e}")
        return []


async def get_price_from_pricelist(
    client: Optional[httpx.AsyncClient],
    item_code: str,
    price_list: str,
) -> Optional[float]:
    """
    Fetch price for an item from a specific Price List.
    """
    close_client = False
    if client is None:
        client = httpx.AsyncClient()
        close_client = True
    try:
        resp = await client.post(
            f"{ERP_URL}/api/method/frappe.client.get_list",
            headers=HEADERS,
            json={
                "doctype": "Item Price",
                "fields": ["price_list_rate"],
                "filters": {"item_code": item_code, "price_list": price_list},
                "limit_page_length": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json().get("message") or []
        return float(data[0]["price_list_rate"]) if data else None
    except Exception as e:
        print(f"❌ Price lookup failed for {item_code}: {e}")
        return None
    finally:
        if close_client:
            await client.aclose()


async def fetch_private_file(file_url: str) -> Optional[bytes]:
    """
    Download a private file (/private/files/...) from ERPNext.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(ERP_URL + file_url, headers=HEADERS)
            if resp.status_code == 200:
                return resp.content
    except Exception as e:
        print(f"❌ Failed to fetch private file: {e}")
    return None


# -----------------------------
# Price list discovery
# -----------------------------
@lru_cache(maxsize=1)
def _env_pricelist():
    return (
        os.getenv("ERP_DEFAULT_PRICE_LIST")
        or os.getenv("ERP_PRICE_LIST")
        or os.getenv("PRICE_LIST")
    )


async def get_default_pricelist(company: str | None = None) -> str:
    """
    Decide which selling price list to use, in this order:
      1) Env var (ERP_DEFAULT_PRICE_LIST / ERP_PRICE_LIST / PRICE_LIST)
      2) Selling Settings.selling_price_list
      3) First enabled Selling Price List (optionally filtered by company)
      4) Fallback: "Standard Selling"
    """
    env_pl = _env_pricelist()
    if env_pl:
        return env_pl

    # 2) Selling Settings doc
    try:
        ss = await get_doc("Selling Settings", "Selling Settings")
        if ss and ss.get("selling_price_list"):
            return ss["selling_price_list"]
    except Exception:
        pass

    # 3) First enabled selling Price List
    try:
        filters: List[List[Any]] = [["selling", "=", 1], ["enabled", "=", 1]]
        if company:
            filters.append(["company", "=", company])

        pls = await get_list(
            "Price List",
            filters=filters,
            fields=["name"],
            limit_page_length=1,
            order_by="modified desc",
        )
        if pls:
            return pls[0]["name"]
    except Exception:
        pass

    return "Standard Selling"

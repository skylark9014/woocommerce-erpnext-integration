# =============================
# ERPNext API Helpers
# =============================

import os
import httpx
from dotenv import load_dotenv
from typing import List, Optional, Dict, Any
from functools import lru_cache

from app.erp.erpnext_client import get_client, get_doc, get_list  # keep these

load_dotenv()

ERP_URL = os.getenv("ERP_URL")
ERP_API_KEY = os.getenv("ERP_API_KEY")
ERP_API_SECRET = os.getenv("ERP_API_SECRET")

HEADERS = {"Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"}


def get_erpnext_items() -> List[dict]:
    """
    Fetch Item list from ERPNext (sync call).
    Returns: [{item_code, item_name, description, image}, ...]
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
# Image helpers
# -----------------------------
async def fetch_item_images(item_code: str) -> List[Dict[str, Any]]:
    """
    Return a list of image dicts for an Item:
      [{url, filename, is_primary, source}]
    - Primary image from Item.image
    - Child table Item Images (item_images)
    - (Optional) File attachments linked to this Item
    Adjust if your DocType differs.
    """
    images: List[Dict[str, Any]] = []

    try:
        doc = await get_doc("Item", item_code)  # uses erpnext_client wrapper
    except Exception as e:
        print(f"❌ Could not fetch Item {item_code}: {e}")
        return images

    # 1) Primary image field
    main_img = doc.get("image")
    if main_img:
        images.append({
            "url": _absolute_file_url(main_img),
            "filename": os.path.basename(main_img),
            "is_primary": True,
            "source": "item.image"
        })

    # 2) Child table item_images
    for idx, row in enumerate(doc.get("item_images", []) or []):
        row_img = row.get("image")
        if row_img:
            images.append({
                "url": _absolute_file_url(row_img),
                "filename": os.path.basename(row_img),
                "is_primary": False,
                "source": f"item_images[{idx}]"
            })

    # 3) File attachments (optional, uncomment if you use File doctype)
    # try:
    #     files = await get_list(
    #         "File",
    #         filters=[
    #             ["attached_to_doctype", "=", "Item"],
    #             ["attached_to_name", "=", item_code],
    #             ["is_private", "=", 1],  # include private if needed
    #         ],
    #         fields=["file_url", "file_name", "is_private"],
    #         limit_page_length=100
    #     )
    #     for f in files:
    #         file_url = f.get("file_url")
    #         if file_url:
    #             images.append({
    #                 "url": _absolute_file_url(file_url),
    #                 "filename": f.get("file_name") or os.path.basename(file_url),
    #                 "is_primary": False,
    #                 "source": "File"
    #             })
    # except Exception as e:
    #     print(f"⚠️ File attachment lookup failed for {item_code}: {e}")

    return images


def _absolute_file_url(file_path: str) -> str:
    """
    Ensure we return a full absolute URL for ERPNext file paths.
    ERP gives /files/... or /private/files/...
    """
    if file_path.startswith("http"):
        return file_path
    return f"{ERP_URL}{file_path}"


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
      1) Env var
      2) Selling Settings.selling_price_list
      3) First enabled Selling Price List (optionally by company)
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

import os
import httpx
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

ERP_URL = os.environ.get("ERP_URL")
ERP_API_KEY = os.environ.get("ERP_API_KEY")
ERP_API_SECRET = os.environ.get("ERP_API_SECRET")

HEADERS = {"Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"}


@asynccontextmanager
async def get_client(timeout: float = 20.0):
    async with httpx.AsyncClient(base_url=ERP_URL, headers=HEADERS, timeout=timeout) as client:
        yield client


# ------------------------
# Generic helpers (async)
# ------------------------
async def get_doc(doctype: str, name: str) -> Dict[str, Any]:
    async with get_client() as client:
        resp = await client.get(f"/api/resource/{doctype}/{name}")
        resp.raise_for_status()
        return resp.json()["data"]


async def get_list(
    doctype: str,
    filters: Optional[Dict[str, Any] | List[List[Any]]] = None,
    fields: Optional[List[str]] = None,
    limit_page_length: int = 20,
    order_by: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Wrap frappe.client.get_list for convenience.
    filters can be dict or list-of-lists format that Frappe accepts.
    """
    payload = {
        "doctype": doctype,
        "filters": filters or {},
        "fields": fields or ["*"],
        "limit_page_length": limit_page_length,
    }
    if order_by:
        payload["order_by"] = order_by

    async with get_client() as client:
        resp = await client.post("/api/method/frappe.client.get_list", json=payload)
        resp.raise_for_status()
        return resp.json().get("message") or []


# ------------------------
# Backward-compat shim
# ------------------------
async def erp_get(doctype: str, name: Optional[str] = None, **kwargs):
    """
    Old code called `erp_get`. Keep it working:
      - name given  -> single doc
      - no name     -> list
    """
    if name:
        return await get_doc(doctype, name)
    return await get_list(doctype, **kwargs)


# ------------------------
# Create / submit helpers
# ------------------------
async def erp_create(client: httpx.AsyncClient, doctype: str, data: dict):
    resp = await client.post(f"/api/resource/{doctype}", json=data)
    resp.raise_for_status()
    return resp.json()["data"]


async def erp_submit(client: httpx.AsyncClient, doctype: str, name: str):
    # Simple "submit" by setting docstatus = 1. Adjust if you use a different pattern.
    resp = await client.put(f"/api/resource/{doctype}/{name}", json={"docstatus": 1})
    resp.raise_for_status()
    return resp.json()["data"]

# app/erp/erpnext_client.py
import os
import httpx

ERP_URL = os.environ.get("ERP_URL")
ERP_API_KEY = os.environ.get("ERP_API_KEY")
ERP_API_SECRET = os.environ.get("ERP_API_SECRET")

HEADERS = {"Authorization": f"token {ERP_API_KEY}:{ERP_API_SECRET}"}

async def erp_create(doctype: str, payload: dict):
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{ERP_URL}/api/resource/{doctype}", headers=HEADERS, json=payload)
        resp.raise_for_status()
        return resp.json().get("data")

async def erp_submit(doctype: str, name: str):
    # Some doctypes need submit via /submit method; adjust if necessary
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{ERP_URL}/api/resource/{doctype}/{name}", headers=HEADERS, json={"docstatus": 1})
        resp.raise_for_status()
        return resp.json().get("data")

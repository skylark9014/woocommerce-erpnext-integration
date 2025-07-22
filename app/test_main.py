import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

def test_webhook_missing_fields():
    # Minimal payload with missing billing
    payload = {"line_items": [], "paid": False}
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 500
    data = resp.json()
    assert "error" in data

def test_webhook_dummy_paid_flow(monkeypatch):
    async def dummy_customer_exists(*args, **kwargs): return False
    async def dummy_create_customer_full(*args, **kwargs): return True, "CUST-0001"
    async def dummy_create_sales_order(*args, **kwargs): return True, {"name": "SO-0001"}
    async def dummy_create_delivery_note(*args, **kwargs): return True, {"name": "DN-0001"}
    async def dummy_create_sales_invoice(*args, **kwargs): return True, {"name": "SI-0001"}
    async def dummy_create_payment_entry(*args, **kwargs): return True, {"name": "PE-0001"}

    from main import customer_exists, create_customer_full, create_sales_order
    from main import create_delivery_note, create_sales_invoice, create_payment_entry

    monkeypatch.setattr("main.customer_exists", dummy_customer_exists)
    monkeypatch.setattr("main.create_customer_full", dummy_create_customer_full)
    monkeypatch.setattr("main.create_sales_order", dummy_create_sales_order)
    monkeypatch.setattr("main.create_delivery_note", dummy_create_delivery_note)
    monkeypatch.setattr("main.create_sales_invoice", dummy_create_sales_invoice)
    monkeypatch.setattr("main.create_payment_entry", dummy_create_payment_entry)

    payload = {
        "billing": {"first_name": "Test", "last_name": "User"},
        "shipping": {"first_name": "Test", "last_name": "User"},
        "line_items": [{"product_id": 123, "quantity": 1}],
        "paid": True
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["sales_order"]["name"] == "SO-0001"
    assert data["delivery_note"]["name"] == "DN-0001"
    assert data["sales_invoice"]["name"] == "SI-0001"
    assert data["payment_entry"]["name"] == "PE-0001"


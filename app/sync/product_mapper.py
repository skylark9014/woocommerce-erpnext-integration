# app/sync/product_mapper.py
from __future__ import annotations
from pathlib import Path
import json
from typing import List, Tuple

# -----------------------------
# Mapping store helpers
# -----------------------------
def build_or_load_mapping(mapping_path: str,
                          wc_products: List[dict],
                          erp_items: List[dict]) -> Tuple[List[dict], List[dict]]:
    """
    Load mapping.json if present, otherwise build 'auto' rows from ERP & Woo.
    Returns (auto_rows, overrides)
    """
    p = Path(mapping_path)
    if p.exists():
        data = json.loads(p.read_text())
        return data.get("auto", []), data.get("overrides", [])
    # first build
    erp_codes = {i["item_code"] for i in erp_items}
    auto_rows = [{"erp_item_code": c,
                  "wc_product_id": None,
                  "wc_sku": None,
                  "status": "unmatched",
                  "last_synced": None,
                  "last_price": None} for c in sorted(erp_codes)]
    return auto_rows, []

def apply_overrides(auto_rows: List[dict], overrides: List[dict]) -> None:
    """Force wc_product_id where an override exists."""
    by_code = {r["erp_item_code"]: r for r in auto_rows}
    for ov in overrides:
        code = ov.get("erp_item_code")
        if not code or code not in by_code:
            continue
        by_code[code]["wc_product_id"] = ov.get("forced_wc_product_id")

# -----------------------------
# Core transform ERP → WC
# -----------------------------
def map_erp_to_wc_product(erp_doc: dict, price: float | None) -> dict:
    """
    Build a WooCommerce product payload from an ERPNext Item doc + price.
    """
    return {
        "name": erp_doc.get("item_name") or erp_doc.get("item_code"),
        "sku": erp_doc.get("item_code"),
        "regular_price": f"{price:.2f}" if price is not None else "0.00",
        "description": erp_doc.get("description") or "",
        "short_description": (erp_doc.get("description") or "")[:140],
        # extend with categories, images, etc as needed
    }

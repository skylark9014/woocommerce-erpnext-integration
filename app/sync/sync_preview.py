# =============================
# Sync Preview Logic (Dry Run)
# =============================

import os
import asyncio
from datetime import datetime

from app.sync.product_mapper import (
    build_or_load_mapping,
    apply_overrides,
    map_erp_to_wc_product,
)
from app.erp.erp_fetch import get_erpnext_items, get_price_from_pricelist
from app.woocommerce.wc_fetch import get_wc_products
from app.utils.compare import norm, FIELDS_TO_COMPARE


# -----------------------------
# Helper: pick a pricelist
# -----------------------------
def _pick_pricelist() -> str:
    return (
        os.getenv("ERP_DEFAULT_PRICE_LIST")
        or os.getenv("ERP_PRICE_LIST")
        or os.getenv("PRICE_LIST")
        or "Standard Selling"
    )


# -----------------------------
# ✅ Generate Sync Preview
# -----------------------------
async def generate_sync_preview():
    erp_items = get_erpnext_items()
    wc_products = get_wc_products()
    auto_rows, overrides = build_or_load_mapping(
        "mapping/product_mapping.json", wc_products, erp_items
    )
    apply_overrides(auto_rows, overrides)

    erp_index = {i["item_code"]: i for i in erp_items}
    wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}

    preview = {"create": [], "update": [], "delete": []}

    # -------- CREATE --------
    for row in auto_rows:
        code = row["erp_item_code"]
        if row.get("wc_product_id") or code in wc_index:
            continue
        preview["create"].append(code)

    # -------- UPDATE --------
    # Only need prices for rows that exist in WC (potential updates)
    candidates = [r["erp_item_code"] for r in auto_rows if r["erp_item_code"] in wc_index]

    pricelist = _pick_pricelist()

    async def _one(code):
        return code, await get_price_from_pricelist(None, code, pricelist)

    price_pairs = await asyncio.gather(*[_one(c) for c in candidates])
    prices = dict(price_pairs)

    for code in candidates:
        wc_p = wc_index.get(code)
        if not wc_p:
            continue
        erp_doc = erp_index[code]
        price = prices.get(code)
        desired = map_erp_to_wc_product(erp_doc, price)

        if any(norm(desired.get(f, "")) != norm(wc_p.get(f, "")) for f in FIELDS_TO_COMPARE):
            preview["update"].append(code)

    # -------- DELETE --------
    erp_codes = set(erp_index.keys())
    for sku in wc_index:
        if sku not in erp_codes:
            preview["delete"].append(sku)

    return {
        "status": "success",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "actions": preview,
        "counts": {
            "create": len(preview["create"]),
            "update": len(preview["update"]),
            "delete": len(preview["delete"]),
        },
    }

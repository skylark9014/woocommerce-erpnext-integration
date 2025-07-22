# =============================
# Sync Preview Logic (Dry Run)
# =============================

from datetime import datetime
from app.mapping.mapping_store import load_mapping_raw
from app.sync.product.mapper import build_or_load_mapping, apply_overrides
from app.erp.erp_fetch import get_erpnext_items
from app.woocommerce.wc_fetch import get_wc_products


# -----------------------------
# ✅ Generate Sync Preview
# -----------------------------
async def generate_sync_preview():
    erp_items = get_erpnext_items()
    wc_products = get_wc_products()
    auto_rows, overrides = build_or_load_mapping("mapping/product_mapping.json", wc_products, erp_items)
    apply_overrides(auto_rows, overrides)

    erp_index = {i["item_code"]: i for i in erp_items}
    wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}

    preview = {
        "create": [],
        "update": [],
        "delete": []
    }

    # CREATE
    for row in auto_rows:
        code = row["erp_item_code"]
        if row.get("wc_product_id") or code in wc_index:
            continue
        preview["create"].append(code)

    # UPDATE
    for row in auto_rows:
        code = row["erp_item_code"]
        wc_p = wc_index.get(code)
        if not wc_p:
            continue
        erp = erp_index[code]
        desired = {
            "name": erp.get("item_name", ""),
            "regular_price": str(erp.get("standard_rate", "")),
            "description": erp.get("description", ""),
            "short_description": erp.get("short_description", "")
        }
        for fld in desired:
            if str(wc_p.get(fld, "")) != str(desired[fld]):
                preview["update"].append(code)
                break

    # DELETE
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
            "delete": len(preview["delete"])
        }
    }


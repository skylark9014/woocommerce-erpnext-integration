# =============================
# Product Mapper - Sync Logic Helpers
# =============================

from typing import Tuple
from app.mapping.mapping_store import save_mapping

# -----------------------------
# ✅ Generate Auto Mapping
# -----------------------------
def generate_auto_mapping(wc_products, erp_items) -> list[dict]:
    wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}
    rows = []
    for it in erp_items:
        sku = it["item_code"]
        wc = wc_index.get(sku)
        rows.append({
            "erp_item_code": sku,
            "wc_product_id": wc["id"] if wc else None,
            "wc_sku": wc["sku"] if wc else None,
            "status": "matched" if wc else "missing_wc",
            "last_synced": None,
            "last_price": None,
            "last_image_media_id": None,
            "last_image_filename": None,
            "last_image_size": None
        })
    return rows

# -----------------------------
# ✅ Apply Overrides
# -----------------------------
def apply_overrides(auto_rows: list[dict], overrides: list[dict]) -> list[dict]:
    idx = {r["erp_item_code"]: r for r in auto_rows}
    for ov in overrides:
        code = ov.get("erp_item_code")
        if not code:
            continue
        base = idx.get(code)
        if not base:
            base = {"erp_item_code": code}
            auto_rows.append(base)
            idx[code] = base
        if ov.get("forced_wc_product_id") is not None:
            base["wc_product_id"] = ov["forced_wc_product_id"]
    return auto_rows

# -----------------------------
# ✅ Load or Generate Mapping
# -----------------------------
def build_or_load_mapping(path: str, wc_products: list, erp_items: list) -> Tuple[list, list]:
    from app.mapping.mapping_store import load_mapping_raw, migrate_if_needed
    raw = load_mapping_raw(path)
    if raw:
        raw = migrate_if_needed(raw)
        return raw["auto"], raw["overrides"]
    auto_rows = generate_auto_mapping(wc_products, erp_items)
    overrides = []
    save_mapping(path, auto_rows, overrides)
    return auto_rows, overrides


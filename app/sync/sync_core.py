# =============================
# Sync Core Logic
# =============================

import asyncio
from app.sync.product_sync import sync_products

# Shared lock to prevent concurrent syncs
sync_lock = asyncio.Lock()

# -----------------------------
# ✅ Run Full Product Sync
# -----------------------------
async def run_full_sync():
    if sync_lock.locked():
        return {"status": "locked", "message": "Sync already in progress."}

    async with sync_lock:
        result = await sync_products()
        return result

# -----------------------------
# ✅ Sync Only Selected Type (Create, Update, Delete)
# -----------------------------
async def sync_products_partial(only: str):
    assert only in ("create", "update", "delete")

    erp_items = get_erpnext_items()
    wc_products = get_wc_products()
    auto_rows, overrides = build_or_load_mapping(MAPPING_JSON_FILE, wc_products, erp_items)
    apply_overrides(auto_rows, overrides)

    erp_index = {i["item_code"]: i for i in erp_items}
    wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}
    results = []

    async with httpx.AsyncClient() as client:
        if only == "create":
            for row in auto_rows:
                code = row["erp_item_code"]
                if row.get("wc_product_id") or code in wc_index:
                    continue
                price = await get_price_from_pricelist(client, code, DEFAULT_PRICE_LIST)
                if price is None:
                    continue
                try:
                    payload = map_erp_to_wc_product(erp_index[code], price)
                    wc_p = wc_create("products", payload)
                    row["wc_product_id"] = wc_p["id"]
                    row["status"] = "created"
                    row["last_price"] = price
                    row["last_synced"] = datetime.utcnow().isoformat() + "Z"
                    results.append(code)
                except Exception as e:
                    logger.error(f"[Bulk Create] Failed {code}: {e}")

        elif only == "update":
            for row in auto_rows:
                code = row["erp_item_code"]
                wc_p = wc_index.get(code)
                if not wc_p:
                    continue
                price = await get_price_from_pricelist(client, code, DEFAULT_PRICE_LIST)
                if price is None:
                    continue
                desired = map_erp_to_wc_product(erp_index[code], price)
                needs_update = any(
                    str(desired.get(fld, "")) != str(wc_p.get(fld, ""))
                    for fld in ("name", "regular_price", "description", "short_description")
                )
                if needs_update:
                    try:
                        wc_update(f"products/{wc_p['id']}", desired)
                        row["status"] = "updated"
                        row["last_price"] = price
                        row["last_synced"] = datetime.utcnow().isoformat() + "Z"
                        results.append(code)
                    except Exception as e:
                        logger.error(f"[Bulk Update] Failed {code}: {e}")

        elif only == "delete":
            erp_codes = set(erp_index.keys())
            for sku, wc_p in wc_index.items():
                if sku not in erp_codes:
                    try:
                        wc_delete(f"products/{wc_p['id']}")
                        results.append(sku)
                    except Exception as e:
                        logger.error(f"[Bulk Delete] Failed {sku}: {e}")

    save_mapping(MAPPING_JSON_FILE, auto_rows, overrides)
    return {
        "status": "success",
        "type": only,
        "count": len(results),
        "items": results
    }


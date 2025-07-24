# app/sync/product_sync.py
# =============================
# Product Sync Module
# - Syncs ERPNext items to WooCommerce
# - Handles create, update, delete, images, mapping persistence
# - Uses batch endpoints and parallel image uploading for performance
# =============================

import asyncio
from datetime import datetime
from typing import Dict, List

from app.erp.erp_fetch import (
    get_erpnext_items,
    get_price_from_pricelist,
    get_default_pricelist,
)
from app.mapping.mapping_store import (
    build_or_load_mapping,
    apply_overrides,
    save_mapping,
)
from app.sync.product_mapper import map_erp_to_wc_product
from app.woocommerce.wc_fetch import get_wc_products
from app.woocommerce.woocommerce_api import wc_create, wc_delete
from app.sync.image_sync import sync_item_images
from app.utils.compare import needs_update
from app.config import MAPPING_JSON_FILE

UTCNOW = lambda: datetime.utcnow().isoformat() + "Z"


def _index(items: List[dict], key: str) -> Dict[str, dict]:
    return {i[key]: i for i in items if i.get(key)}


def _row_for(auto_rows: List[dict], code: str) -> dict:
    for r in auto_rows:
        if r.get("erp_item_code") == code:
            return r
    r = {
        "erp_item_code": code,
        "wc_product_id": None,
        "wc_sku": None,
        "status": "unmatched",
        "last_synced": None,
        "last_price": None,
        "last_image_media_id": None,
        "last_image_filename": None,
        "last_image_size": None,
    }
    auto_rows.append(r)
    return r


async def _get_prices(codes: List[str], pricelist: str) -> Dict[str, float]:
    async def one(code: str):
        return code, await get_price_from_pricelist(None, code, pricelist)
    pairs = await asyncio.gather(*[one(c) for c in codes])
    return {c: p for c, p in pairs}


# -----------------------------------------------------
# Public entry point
# -----------------------------------------------------
async def sync_products(pricelist: str | None = None, dry_run: bool = False) -> dict:
    """
    Full sync:
      1. Load ERP + WC + mapping
      2. Decide create/update/delete
      3. Perform batch create/update + parallel image sync
      4. Delete orphans
      5. Save mapping
    """
    chosen_pricelist = pricelist or await get_default_pricelist()

    # 1) Load fresh data + mapping
    erp_items = get_erpnext_items()
    wc_products = await get_wc_products()
    auto_rows, overrides, images_map = build_or_load_mapping(
        MAPPING_JSON_FILE, wc_products, erp_items
    )
    apply_overrides(auto_rows, overrides)

    erp_idx = _index(erp_items, "item_code")
    wc_idx = _index([p for p in wc_products if p.get("sku")], "sku")

    # 2) Decide actions
    to_create: List[str] = []
    to_update: List[str] = []
    erp_codes = set(erp_idx.keys())

    for row in auto_rows:
        code = row["erp_item_code"]
        if code not in wc_idx and not row.get("wc_product_id"):
            to_create.append(code)
        elif code in wc_idx:
            to_update.append(code)

    to_delete = [sku for sku in wc_idx if sku not in erp_codes]

    # 3) Prices
    price_codes = list({*to_create, *to_update})
    prices = await _get_prices(price_codes, chosen_pricelist)

    created, updated, deleted, failed = [], [], [], []

    # 4) Batch CREATE + UPDATE
    create_payloads, update_payloads = [], []

    # build create payloads
    for code in to_create:
        price = prices.get(code)
        if price is None:
            failed.append(code)
            continue
        create_payloads.append(map_erp_to_wc_product(erp_idx[code], price))

    # build update payloads (only if something changed)
    for code in to_update:
        wc_p = wc_idx[code]
        price = prices.get(code)
        if price is None:
            failed.append(code)
            continue
        desired = map_erp_to_wc_product(erp_idx[code], price)
        if needs_update(desired, wc_p):
            payload = {"id": wc_p["id"], **desired}
            update_payloads.append(payload)

    # fire the batch request
    if create_payloads or update_payloads:
        batch_data: dict = {}
        if create_payloads:
            batch_data["create"] = create_payloads
        if update_payloads:
            batch_data["update"] = update_payloads

        try:
            resp = await wc_create("products/batch", batch_data)
        except Exception as e:
            # If batch fails entirely, mark them all as failed
            failed.extend([r.get("sku") or "" for r in batch_data.get("create", [])])
            failed.extend([str(p["id"]) for p in batch_data.get("update", [])])
            resp = {}
        else:
            # process created
            for wc_p in resp.get("create", []):
                sku = wc_p.get("sku")
                row = _row_for(auto_rows, sku)
                row.update({
                    "wc_product_id": wc_p["id"],
                    "wc_sku": sku,
                    "status": "created",
                    "last_price": prices.get(sku),
                    "last_synced": UTCNOW(),
                })
                created.append(sku)

            # process updated
            for wc_p in resp.get("update", []):
                sku = wc_p.get("sku")
                row = _row_for(auto_rows, sku)
                row.update({
                    "status": "updated",
                    "last_price": prices.get(sku),
                    "last_synced": UTCNOW(),
                })
                updated.append(sku)

            # 5) Parallel image sync
            if not dry_run:
                tasks = []
                for wc_p in resp.get("create", []):
                    sku = wc_p.get("sku")
                    tasks.append(sync_item_images(sku, wc_p["id"], images_map, dry_run=False))
                for wc_p in resp.get("update", []):
                    sku = wc_p.get("sku")
                    tasks.append(sync_item_images(sku, wc_idx[sku]["id"], images_map, dry_run=False))
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

    # 6) DELETE orphans (usually few; individual calls suffice)
    for sku in to_delete:
        wc_p = wc_idx[sku]
        try:
            await wc_delete(f"products/{wc_p['id']}")
            deleted.append(sku)
        except Exception:
            failed.append(sku)

    # 7) Save mapping
    if not dry_run:
        save_mapping(MAPPING_JSON_FILE, auto_rows, overrides, images_map)

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "failed": failed,
        "dry_run": dry_run,
    }

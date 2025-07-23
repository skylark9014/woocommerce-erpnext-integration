# app/sync/product_sync.py
# =============================
# Product Sync Module
# - Syncs ERPNext items to WooCommerce
# - Handles create, update, delete, images, mapping persistence
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
from app.woocommerce.woocommerce_api import wc_create, wc_update, wc_delete
from app.sync.image_sync import sync_item_images
from app.utils.compare import needs_update
from app.config import MAPPING_JSON_FILE

UTCNOW = lambda: datetime.utcnow().isoformat() + "Z"


def _index(items: List[dict], key: str) -> Dict[str, dict]:
    return {i[key]: i for i in items if key in i and i[key]}


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
    async def one(code):
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
      3. Perform actions (including image sync)
      4. Save mapping.json
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
        wc_p = wc_idx.get(code)
        if wc_p is None:
            if not row.get("wc_product_id"):
                to_create.append(code)
            continue
        to_update.append(code)

    to_delete = [sku for sku in wc_idx if sku not in erp_codes]

    # 3) Prices
    price_codes = list({*to_create, *to_update})
    prices = await _get_prices(price_codes, chosen_pricelist)

    created, updated, deleted, failed = [], [], [], []

    # CREATE
    for code in to_create:
        price = prices.get(code)
        if price is None:
            failed.append(code)
            continue
        try:
            payload = map_erp_to_wc_product(erp_idx[code], price)
            wc_p = await wc_create("products", payload)
            row = _row_for(auto_rows, code)
            row.update(
                {
                    "wc_product_id": wc_p["id"],
                    "wc_sku": wc_p.get("sku") or code,
                    "status": "created",
                    "last_price": price,
                    "last_synced": UTCNOW(),
                }
            )
            created.append(code)

            if not dry_run:
                await sync_item_images(code, wc_p["id"], images_map, dry_run=False)
        except Exception:
            failed.append(code)

    # UPDATE
    for code in to_update:
        wc_p = wc_idx.get(code)
        if not wc_p:
            continue  # may have been created above
        price = prices.get(code)
        if price is None:
            failed.append(code)
            continue

        desired = map_erp_to_wc_product(erp_idx[code], price)

        try:
            if needs_update(desired, wc_p):
                await wc_update(f"products/{wc_p['id']}", desired)
                # keep local snapshot consistent so subsequent comparisons don't refire
                wc_p.update({k: v for k, v in desired.items()
                             if k in ("name", "regular_price", "description", "short_description")})

            await sync_item_images(code, wc_p["id"], images_map, dry_run=dry_run)

            row = _row_for(auto_rows, code)
            row.update(
                {
                    "status": "updated",
                    "last_price": price,
                    "last_synced": UTCNOW(),
                }
            )
            updated.append(code)
        except Exception:
            failed.append(code)

    # DELETE
    for sku in to_delete:
        wc_p = wc_idx[sku]
        try:
            await wc_delete(f"products/{wc_p['id']}")
            deleted.append(sku)
        except Exception:
            failed.append(sku)

    # 4) Save mapping
    if not dry_run:
        save_mapping(MAPPING_JSON_FILE, auto_rows, overrides, images_map)

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "failed": failed,
        "dry_run": dry_run,
    }

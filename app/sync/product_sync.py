# =============================
# Product Sync Module
# - Syncs ERPNext items to WooCommerce
# - Handles create, update, delete, and mapping persistence
# =============================

import os
import asyncio
from datetime import datetime
from typing import Dict, List

from app.erp.erp_fetch import get_erpnext_items, get_price_from_pricelist
from app.mapping.mapping_store import load_mapping_raw, save_mapping
from app.sync.product_mapper import (
    build_or_load_mapping,
    apply_overrides,
    map_erp_to_wc_product,
)
from app.woocommerce.wc_fetch import get_wc_products
from app.woocommerce.woocommerce_api import wc_create, wc_update, wc_delete
from app.utils.compare import needs_update
from app.config import MAPPING_JSON_FILE

UTCNOW = lambda: datetime.utcnow().isoformat() + "Z"


# -----------------------------------------------------
# Pricelist picker (same as in sync_preview.py)
# -----------------------------------------------------
def _pick_pricelist() -> str:
    return (
        os.getenv("ERP_DEFAULT_PRICE_LIST")
        or os.getenv("ERP_PRICE_LIST")
        or os.getenv("PRICE_LIST")
        or "Standard Selling"
    )


# -----------------------------------------------------
# Helpers
# -----------------------------------------------------
def _index(items: List[dict], key: str) -> Dict[str, dict]:
    """Quick index by a key."""
    return {i[key]: i for i in items if key in i and i[key]}


def _row_for(auto_rows: List[dict], code: str) -> dict:
    """Find (or create) a row in auto mapping for the ERP code."""
    for r in auto_rows:
        if r.get("erp_item_code") == code:
            return r
    # create a placeholder row if not present (rare)
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
    """Fetch prices concurrently."""
    async def one(code):
        return code, await get_price_from_pricelist(None, code, pricelist)

    pairs = await asyncio.gather(*[one(c) for c in codes])
    return {c: p for c, p in pairs}


# -----------------------------------------------------
# Public entry point
# -----------------------------------------------------
async def sync_products(pricelist: str | None = None) -> dict:
    """
    Full sync:
      1. Load ERP + WC + mapping
      2. Determine create/update/delete
      3. Perform actions
      4. Save mapping.json

    pricelist:
        - If None, choose via env vars (ERP_DEFAULT_PRICE_LIST / ERP_PRICE_LIST / PRICE_LIST)
        - Otherwise use the provided value.
    Returns dict with created/updated/deleted/failed lists.
    """

    chosen_pricelist = pricelist or _pick_pricelist()

    # 1) Load fresh data + mapping
    erp_items = get_erpnext_items()
    wc_products = get_wc_products()
    auto_rows, overrides = build_or_load_mapping(MAPPING_JSON_FILE, wc_products, erp_items)
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
            if not row.get("wc_product_id"):  # not linked
                to_create.append(code)
            continue
        # exists in WC, may need update
        to_update.append(code)

    # delete detection (orphans in WC)
    to_delete = [sku for sku in wc_idx.keys() if sku not in erp_codes]

    # 3) Fetch prices in bulk (only for codes we may touch)
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
            wc_p = wc_create("products", payload)
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
        except Exception:  # noqa
            failed.append(code)

    # UPDATE
    for code in to_update:
        wc_p = wc_idx.get(code)
        if wc_p is None:
            continue  # got created above
        price = prices.get(code)
        if price is None:
            failed.append(code)
            continue

        desired = map_erp_to_wc_product(erp_idx[code], price)
        if not needs_update(desired, wc_p):
            continue  # nothing to push

        try:
            wc_update(f"products/{wc_p['id']}", desired)
            row = _row_for(auto_rows, code)
            row.update(
                {
                    "status": "updated",
                    "last_price": price,
                    "last_synced": UTCNOW(),
                }
            )
            updated.append(code)
        except Exception:  # noqa
            failed.append(code)

    # DELETE
    for sku in to_delete:
        wc_p = wc_idx[sku]
        try:
            wc_delete(f"products/{wc_p['id']}")
            deleted.append(sku)
        except Exception:  # noqa
            failed.append(sku)

    # 4) Save mapping
    save_mapping(MAPPING_JSON_FILE, auto_rows, overrides)

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "failed": failed,
    }

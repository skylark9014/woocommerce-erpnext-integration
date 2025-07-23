# app/sync/sync_preview.py
# =============================
# Sync Preview Logic (Dry Run)
# =============================

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Any, Tuple

import httpx
from httpx import HTTPError, ConnectError

from app.mapping.mapping_store import (
    build_or_load_mapping,
    apply_overrides,
    get_images_for_item,
)
from app.sync.product_mapper import map_erp_to_wc_product
from app.erp.erp_fetch import (
    get_erpnext_items,
    get_price_from_pricelist,
    fetch_item_images,
    HEADERS as ERP_HEADERS,
    get_default_pricelist,
)
from app.woocommerce.wc_fetch import get_wc_products
from app.woocommerce.woocommerce_api import wc_get_product_images
from app.utils.compare import norm, FIELDS_TO_COMPARE, prices_equal
from app.config import MAPPING_JSON_FILE

logger = logging.getLogger(__name__)


async def _prices_for(codes: List[str], pricelist: str) -> Dict[str, float | None]:
    async def one(code: str):
        return code, await get_price_from_pricelist(None, code, pricelist)
    pairs = await asyncio.gather(*[one(c) for c in codes])
    return dict(pairs)


async def _sha256_of_url(url: str) -> Tuple[str, int]:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url, headers=ERP_HEADERS)
        r.raise_for_status()
        data = r.content
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest(), len(data)


async def _images_changed(
    code: str,
    wc_product_id: int,
    images_map: Dict[str, List[Dict[str, Any]]]
) -> bool:
    """
    Return True if images differ, False if not. Never raise.
    If network/auth fails on Woo, we skip image diff to keep preview responsive.
    """
    try:
        erp_imgs = await fetch_item_images(code)
        erp_urls = [i["url"] for i in erp_imgs]

        mapped = get_images_for_item(images_map, code)
        mapped_by_url = {m["erp_url"]: m for m in mapped}

        if erp_urls and not mapped:
            return True

        if set(erp_urls) != set(mapped_by_url.keys()):
            return True

        # Hash check (ERP side)
        tasks = [_sha256_of_url(u) for u in erp_urls]
        hashes = await asyncio.gather(*tasks)
        for url, (digest, _size) in zip(erp_urls, hashes):
            prev = mapped_by_url.get(url)
            if not prev or prev.get("sha256") != digest:
                return True

        # Woo existence check
        try:
            woo_imgs = await wc_get_product_images(wc_product_id)
            woo_ids = {int(i["id"]) for i in woo_imgs}
            mapped_ids = {m.get("woo_media_id") for m in mapped if m.get("woo_media_id")}
            if not mapped_ids.issubset(woo_ids):
                return True
        except HTTPError as e:
            logger.warning("Skipping Woo image check for %s (network/auth issue): %s", code, e)
            return False

        return False
    except Exception as e:
        logger.warning("Image diff failed for %s: %s", code, e)
        return False


# -----------------------------
# ✅ Generate Sync Preview
# -----------------------------
async def generate_sync_preview(pricelist: str | None = None):
    # Use same pricelist as bulk sync
    if pricelist is None:
        pricelist = await get_default_pricelist()

    # ERP
    erp_items = get_erpnext_items()
    erp_index = {i["item_code"]: i for i in erp_items}

    # Woo (may be offline)
    try:
        wc_products = await get_wc_products()
    except (HTTPError, ConnectError, Exception) as e:
        logger.warning("Woo unreachable in preview: %s", e)
        wc_products = []

    wc_by_id = {p["id"]: p for p in wc_products}
    wc_by_sku = {p.get("sku"): p for p in wc_products if p.get("sku")}

    auto_rows, overrides, images_map = build_or_load_mapping(
        MAPPING_JSON_FILE, wc_products, erp_items
    )
    apply_overrides(auto_rows, overrides)

    preview = {"create": [], "update": [], "delete": []}
    reasons: Dict[str, Dict[str, Any]] = {"update": {}}

    # -------- CREATE --------
    for row in auto_rows:
        code = row["erp_item_code"]
        wid = row.get("wc_product_id")
        sku_ok = code in wc_by_sku
        id_ok = wid in wc_by_id if wid else False
        if not sku_ok and not id_ok:
            preview["create"].append(code)

    # -------- UPDATE --------
    candidates: List[Tuple[str, int]] = []
    for row in auto_rows:
        code = row["erp_item_code"]
        wid = row.get("wc_product_id")
        if wid and wid in wc_by_id:
            candidates.append((code, wid))
            continue
        prod = wc_by_sku.get(code)
        if prod:
            candidates.append((code, prod["id"]))

    if wc_products:
        price_dict = await _prices_for([c for c, _ in candidates], pricelist)

        for code, wc_id in candidates:
            wc_p = wc_by_id.get(wc_id)
            erp_doc = erp_index.get(code)
            if not wc_p or not erp_doc:
                continue

            price = price_dict.get(code)
            desired = map_erp_to_wc_product(erp_doc, price)

            changed_fields: List[str] = []
            for f in FIELDS_TO_COMPARE:
                if f == "regular_price":
                    if price is None:
                        continue
                    desired_price = desired.get(f)
                    current_price = wc_p.get(f)
                    if (desired_price in (None, "") and current_price in (None, "")):
                        continue
                    if not prices_equal(desired_price, current_price):
                        changed_fields.append(f)
                else:
                    if norm(desired.get(f, "")) != norm(wc_p.get(f, "")):
                        changed_fields.append(f)

            try:
                img_changed = await _images_changed(code, wc_id, images_map)
            except Exception as e:
                logger.warning("Image diff outer catch for %s: %s", code, e)
                img_changed = False

            if changed_fields or img_changed:
                preview["update"].append(code)
                reasons["update"][code] = {
                    "fields": changed_fields,
                    "images_changed": img_changed,
                }

        # -------- DELETE --------
        erp_codes = set(erp_index.keys())
        for prod in wc_products:
            sku = prod.get("sku")
            if sku and sku not in erp_codes:
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
        "reasons": reasons,
        "pricelist_used": pricelist,
    }

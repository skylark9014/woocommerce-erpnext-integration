# app/sync/image_sync.py
# =============================
# ERPNext → WooCommerce image sync
# - Compares SHA256 hashes
# - Uploads only new/changed images
# - Supports multiple images
# - Removes images that no longer exist in ERP
# =============================

import hashlib
from typing import Dict, List, Any, Optional, Tuple
import httpx

from app.erp.erp_fetch import fetch_item_images, HEADERS as ERP_HEADERS
from app.woocommerce.woocommerce_api import (
    wc_get_product_images,
    wc_update_product_images,
    wp_upload_media,
)
from app.mapping.mapping_store import (
    get_images_for_item,
    upsert_image_mapping,
    remove_image_mapping,
    now_iso,
)

def _sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()

async def _download_bytes(url: str) -> Tuple[bytes, str]:
    """
    Download bytes + mime-type from an ERPNext file URL (handles private files).
    """
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url, headers=ERP_HEADERS)
        resp.raise_for_status()
        mime = resp.headers.get("content-type", "application/octet-stream")
        return resp.content, mime

async def sync_item_images(
    erp_item_code: str,
    wc_product_id: int,
    images_map: Dict[str, List[Dict[str, Any]]],
    dry_run: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Sync all images for one ERP item into the Woo product.

    images_map: the "images" dict from mapping_store.build_or_load_mapping(...)
    Returns a dict for logging: {"uploaded": [...], "unchanged": [...], "removed": [...]}
    """
    uploaded, unchanged, removed = [], [], []

    # 1) ERP side: gather every image record
    erp_images = await fetch_item_images(erp_item_code)

    # 2) Existing mapping for this item
    current_map = get_images_for_item(images_map, erp_item_code)
    current_by_url = {r["erp_url"]: r for r in current_map}

    # 3) Woo current images (to know which to drop)
    woo_imgs = await wc_get_product_images(wc_product_id)
    woo_ids_present = {str(img["id"]) for img in woo_imgs}

    # Build the new images payload in one shot
    new_payload: List[Dict[str, Any]] = []

    for pos, erp_img in enumerate(erp_images):
        erp_url = erp_img["url"]
        filename = erp_img["filename"] or f"{erp_item_code}_{pos}"
        content, mime = await _download_bytes(erp_url)
        digest = _sha256(content)

        prev = current_by_url.get(erp_url)
        need_upload = True
        media_id: Optional[int] = None

        # reuse if unchanged
        if prev and prev.get("sha256") == digest and prev.get("woo_media_id") in woo_ids_present:
            media_id = prev["woo_media_id"]
            need_upload = False
            unchanged.append({"erp_url": erp_url, "woo_media_id": media_id})
            new_payload.append({"id": media_id, "position": pos})

        if need_upload:
            if dry_run:
                uploaded.append({
                    "erp_url": erp_url,
                    "filename": filename,
                    "sha256": digest,
                    "dry_run": True
                })
            else:
                media_id = await wp_upload_media(content, filename, mime)
                uploaded.append({
                    "erp_url": erp_url,
                    "filename": filename,
                    "sha256": digest,
                    "woo_media_id": media_id
                })
                new_payload.append({"id": media_id, "position": pos})

        # update our JSON mapping
        upsert_image_mapping(
            images_map=images_map,
            erp_item_code=erp_item_code,
            erp_url=erp_url,
            sha256=digest,
            woo_media_id=media_id,
            filename=filename,
            position=pos,
        )

    # 4) Anything in our mapping no longer in ERP? remove it
    erp_urls = {img["url"] for img in erp_images}
    for rec in list(current_map):
        if rec["erp_url"] not in erp_urls:
            remove_image_mapping(images_map, erp_item_code, rec["erp_url"])
            if rec.get("woo_media_id"):
                removed.append({
                    "erp_url": rec["erp_url"],
                    "woo_media_id": rec["woo_media_id"]
                })

    # 5) Push the whole gallery update in one REST call
    if new_payload and not dry_run:
        await wc_update_product_images(wc_product_id, new_payload)

    return {"uploaded": uploaded, "unchanged": unchanged, "removed": removed}

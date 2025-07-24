# app/woocommerce/woocommerce_api.py
# =============================
# WooCommerce / WordPress API Helpers (ASYNC)
# =============================

import os
import logging
import asyncio
from typing import Any, Dict, List, Optional, Sequence

import httpx
from httpx import HTTPStatusError, RequestError
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ----- Woo creds (for wc/v3 endpoints) -----
WC_BASE_URL   = os.getenv("WC_BASE_URL")
WC_API_KEY    = os.getenv("WC_API_KEY")
WC_API_SECRET = os.getenv("WC_API_SECRET")

if not all([WC_BASE_URL, WC_API_KEY, WC_API_SECRET]):
    raise RuntimeError(
        "Missing WooCommerce API credentials in .env "
        "(WC_BASE_URL / WC_API_KEY / WC_API_SECRET)"
    )

WC_AUTH = (WC_API_KEY, WC_API_SECRET)

# ----- WP media creds (for wp/v2/media endpoint) -----
WP_MEDIA_USER = (
    os.getenv("WP_MEDIA_USER")
    or os.getenv("WP_USERNAME")
    or os.getenv("WC_BASIC_USER")
)
WP_MEDIA_APP_PASS = (
    os.getenv("WP_MEDIA_APP_PASS")
    or os.getenv("WP_APP_PASSWORD")
    or os.getenv("WC_BASIC_PASS")
)

if (WP_MEDIA_USER or WP_MEDIA_APP_PASS) and not (WP_MEDIA_USER and WP_MEDIA_APP_PASS):
    logger.warning(
        "Only one of WP_MEDIA_USER / WP_MEDIA_APP_PASS supplied. "
        "Media uploads will fail."
    )

# Base for WP REST
WP_API_URL_RAW = os.getenv("WP_API_URL") or WC_BASE_URL
WP_API_ROOT = WP_API_URL_RAW.rstrip("/")
if not WP_API_ROOT.endswith("/wp-json"):
    WP_API_ROOT = f"{WP_API_ROOT}/wp-json"

# ---------------------- internal clients ----------------------

async def _wc_client():
    return httpx.AsyncClient(timeout=120.0, auth=WC_AUTH)

async def _wp_media_client():
    if not (WP_MEDIA_USER and WP_MEDIA_APP_PASS):
        raise RuntimeError(
            "WP_MEDIA_USER / WP_MEDIA_APP_PASS missing. Cannot upload media."
        )
    return httpx.AsyncClient(timeout=180.0, auth=(WP_MEDIA_USER, WP_MEDIA_APP_PASS))

def _raise_with_body(exc: HTTPStatusError):
    try:
        body = exc.response.json()
    except Exception:
        body = exc.response.text
    msg = f"{exc} :: {body}"
    raise HTTPStatusError(msg, request=exc.request, response=exc.response) from exc

async def _with_retry(fn, attempts=3, delay=0.6, *args, **kwargs):
    last = None
    for i in range(attempts):
        try:
            return await fn(*args, **kwargs)
        except (RequestError, HTTPStatusError) as e:
            last = e
            await asyncio.sleep(delay * (i + 1))
    raise last

# ---------------------- Core WC endpoints ----------------------

async def wc_get(path: str, params: Optional[dict] = None) -> Any:
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path}"
    async with await _wc_client() as c:
        r = await c.get(url, params=params or {})
        try:
            r.raise_for_status()
        except HTTPStatusError as e:
            _raise_with_body(e)
        return r.json()

async def wc_post(path: str, data: dict) -> Any:
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path}"
    async with await _wc_client() as c:
        r = await c.post(url, json=data)
        try:
            r.raise_for_status()
        except HTTPStatusError as e:
            _raise_with_body(e)
        return r.json()

async def wc_put(path: str, data: dict) -> Any:
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path}"
    async with await _wc_client() as c:
        r = await c.put(url, json=data)
        try:
            r.raise_for_status()
        except HTTPStatusError as e:
            _raise_with_body(e)
        return r.json()

async def wc_delete(path: str) -> Any:
    url = f"{WC_BASE_URL}/wp-json/wc/v3/{path}?force=true"
    async with await _wc_client() as c:
        r = await c.delete(url)
        try:
            r.raise_for_status()
        except HTTPStatusError as e:
            _raise_with_body(e)
        return r.json()

# Short aliases
wc_create = wc_post
wc_update = wc_put

# ---------------------- Search / cleanup helpers ----------------------

async def wc_search_by_sku(
    sku: str,
    statuses: Optional[Sequence[str]] = None
) -> List[Dict[str, Any]]:
    """
    Search products by SKU across multiple statuses.
    """
    if statuses is None:
        statuses = ["publish", "draft", "pending", "private", "trash"]
    status_param = ",".join(statuses)
    try:
        return await wc_get("products", {"sku": sku, "status": status_param, "per_page": 100})
    except HTTPStatusError:
        # Some Woo versions don't like 'status' param when filtering by SKU. Fallback.
        return await wc_get("products", {"sku": sku, "per_page": 100})

async def wc_force_delete_by_sku(sku: str):
    """Hard-delete any product (any status) that still carries this SKU."""
    try:
        prods = await wc_search_by_sku(sku)
    except Exception as e:
        logger.warning("Search for SKU %s failed before delete: %s", sku, e)
        prods = []
    for p in prods:
        try:
            await wc_delete(f"products/{p['id']}")
        except Exception as e:
            logger.warning("Force delete of SKU %s (id %s) failed: %s", sku, p.get("id"), e)

# ---------------------- Woo Tools ----------------------

# module‑level cache flag for lookup‑table support
_lookup_table_supported: Optional[bool] = None

async def wc_regenerate_lookup_table() -> bool:
    """
    Best-effort attempt to run Woo's product lookup-table regeneration.
    Many installs don't expose this via REST; return False if unavailable.
    Never raise. Only logs the first 404/401/403 warning.
    """
    global _lookup_table_supported
    if _lookup_table_supported is False:
        return False

    new_url = (
        f"{WC_BASE_URL}/wp-json/wc/v3/system_status/tools/"
        "regenerate_product_lookup_table"
    )
    old_url = f"{WC_BASE_URL}/wp-json/wc/v3/system_status/tools/run"

    async with await _wc_client() as c:
        # try newer endpoint
        try:
            r = await c.post(new_url, json={})
            r.raise_for_status()
            _lookup_table_supported = True
            return True
        except HTTPStatusError:
            pass

        # try older endpoint
        try:
            r2 = await c.post(old_url, json={"id": "regenerate_product_lookup_table"})
            r2.raise_for_status()
            _lookup_table_supported = True
            return True
        except HTTPStatusError as e_old:
            # only log once for auth/404 failures
            code = e_old.response.status_code if e_old.response else None
            if _lookup_table_supported is None and code in (401, 403, 404):
                logger.warning(
                    "Woo lookup-table regen not available: %s", e_old
                )
            _lookup_table_supported = False
        except Exception as e:
            logger.warning("Lookup-table regeneration unexpected error: %s", e)
            _lookup_table_supported = False

    return False

# ---------------------- Image / Media helpers ----------------------

async def wc_get_product_images(product_id: int) -> List[Dict]:
    prod = await wc_get(f"products/{product_id}")
    return prod.get("images", []) or []

async def wc_update_product_images(
    product_id: int,
    images_payload: List[Dict[str, Any]]
) -> Dict:
    return await wc_put(f"products/{product_id}", {"images": images_payload})

async def wp_upload_media(
    binary: bytes,
    filename: str,
    mime_type: str
) -> int:
    """
    Upload to WP media library via WP REST (/wp/v2/media).
    Requires WP media auth (application password or basic auth capable user).
    """
    if not (WP_MEDIA_USER and WP_MEDIA_APP_PASS):
        raise RuntimeError(
            "WP_MEDIA_USER / WP_MEDIA_APP_PASS not set; cannot upload media."
        )

    url = f"{WP_API_ROOT}/wp/v2/media"
    headers = {
        "Content-Disposition": f'attachment; filename=\"{filename}\"',
        "Content-Type": mime_type,
    }
    async with await _wp_media_client() as c:
        r = await c.post(url, headers=headers, content=binary)
        try:
            r.raise_for_status()
        except HTTPStatusError as e:
            _raise_with_body(e)
        return r.json()["id"]

async def wc_empty_trash(per_page: int = 100) -> List[int]:
    """
    Fetch all products in the 'trash' status (in batches of `per_page`)
    and permanently delete them (force=true).
    Returns the list of IDs that were removed.
    """
    removed = []
    page = 1
    while True:
        trashed = await wc_get("products", {"status": "trash", "per_page": per_page, "page": page})
        if not trashed:
            break
        for p in trashed:
            try:
                await wc_delete(f"products/{p['id']}")  # wc_delete already sets force=true
                removed.append(p["id"])
            except Exception as e:
                logger.warning("Failed to purge trashed product %s: %s", p["id"], e)
        page += 1
    return removed

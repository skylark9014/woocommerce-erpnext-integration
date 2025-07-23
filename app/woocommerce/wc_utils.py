import typing as t
from httpx import HTTPStatusError
from app.woocommerce.woocommerce_api import wc_get, wc_delete

async def find_products_by_sku_any(sku: str) -> t.List[dict]:
    # status 'any' should include trash/draft, but Woo is inconsistent,
    # so we also call without status if needed.
    res = await wc_get("products", {"sku": sku, "status": "any", "per_page": 100})
    return res

async def ensure_sku_free(sku: str):
    """
    If a product with this SKU exists (even in trash), delete it so we can recreate.
    """
    try:
        hits = await find_products_by_sku_any(sku)
    except HTTPStatusError:
        # fall back without status filter
        hits = await wc_get("products", {"sku": sku, "per_page": 100})

    for prod in hits:
        try:
            await wc_delete(f"products/{prod['id']}")
        except Exception:
            # ignore – we'll just let create fail if this doesn't work
            pass

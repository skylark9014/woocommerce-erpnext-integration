#=================================
#WooCommerce → ERPNext Integration
#Fetches products from WooCommerce via the REST API.
#=================================

# app/woocommerce/wc_fetch.py
from typing import List, Dict, Any, Optional
from app.woocommerce.woocommerce_api import wc_get  # async

# Pull all Woo products (paged)
async def get_wc_products(per_page: int = 100) -> List[Dict[str, Any]]:
    products: List[Dict[str, Any]] = []
    page = 1
    while True:
        batch = await wc_get("products", {"per_page": per_page, "page": page})
        if not batch:
            break
        products.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return products

# Add more helpers here and keep them async if they call wc_get/wc_post/etc.

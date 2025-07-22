#=================================
#WooCommerce → ERPNext Integration
#Fetches products from WooCommerce via the REST API.
#=================================

from app.woocommerce.woocommerce_api import wc_get
def get_wc_products(per_page: int = 100) -> list:
    """
    Fetches *all* WooCommerce products, paging until none are left.
    :param per_page: how many products to fetch per page (max 100)
    :return: list of product dicts
    """
    all_products = []
    page = 1

    while True:
        batch = wc_get(
            "products",
            params={"page": page, "per_page": per_page}
        )
        if not batch:
            break
        all_products.extend(batch)
        page += 1

    return all_products


# app/utils/pricelist.py
import os
from app.erp.erpnext_client import get_doc, get_list  # <- whatever your real funcs are!

DEFAULT_FALLBACK = "Standard Selling"

async def get_active_selling_pricelist() -> str:
    """
    1) ENV override: ERP_DEFAULT_PRICELIST
    2) Selling Settings.selling_price_list
    3) First enabled selling Price List
    4) DEFAULT_FALLBACK
    """
    env_pl = os.getenv("ERP_DEFAULT_PRICELIST")
    if env_pl:
        return env_pl

    try:
        ss = await get_doc("Selling Settings", "Selling Settings")
        if ss and ss.get("selling_price_list"):
            return ss["selling_price_list"]
    except Exception:
        pass

    try:
        pls = await get_list(
            "Price List",
            filters={"selling": 1, "enabled": 1},
            fields=["name"],
            limit_page_length=1,
        )
        if pls:
            return pls[0]["name"]
    except Exception:
        pass

    return DEFAULT_FALLBACK

# app/utils/mapping_utils.py
def scrub_stale_links(auto_rows, wc_by_id: dict, wc_by_sku: dict) -> bool:
    """
    If a row points to a Woo product that no longer exists, blank it out
    so preview/bulk create can recreate it.
    Returns True if any row was changed.
    """
    changed = False
    for r in auto_rows:
        wid = r.get("wc_product_id")
        sku = r.get("wc_sku")
        if wid and wid not in wc_by_id:
            r["wc_product_id"] = None
            r["status"] = "unmatched"
            changed = True
        # if sku present but not in woo list, clear too
        if sku and sku not in wc_by_sku:
            r["wc_sku"] = None
            r["status"] = "unmatched"
            changed = True
    return changed

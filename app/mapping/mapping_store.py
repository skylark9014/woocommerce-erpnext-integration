import json, os, time, errno, fcntl, tempfile, shutil
from typing import Tuple, List, Dict, Any
from datetime import datetime

SCHEMA_VERSION = 2
SAVE_RETRIES = 5
SAVE_RETRY_DELAY_SECS = 0.15  # 150 ms

def now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def load_mapping_raw(path) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    return data

def migrate_if_needed(data: dict) -> dict:
    if "schema_version" not in data:
        # assume old flat list
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "auto": data if isinstance(data, list) else [],
            "overrides": []
        }
    if data["schema_version"] != SCHEMA_VERSION:
        # future migrations here
        data["schema_version"] = SCHEMA_VERSION
    return data

def save_mapping(path, auto_rows, overrides):
    with open(path, "w") as f:
        json.dump({"auto": auto_rows, "overrides": overrides}, f, indent=2)

def generate_auto_mapping(wc_products, erp_items) -> List[dict]:
    wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}
    rows = []
    for it in erp_items:
        sku = it["item_code"]
        wc = wc_index.get(sku)
        rows.append({
            "erp_item_code": sku,
            "wc_product_id": wc["id"] if wc else None,
            "wc_sku": wc["sku"] if wc else None,
            "status": "matched" if wc else "missing_wc",
            "last_synced": None,
            "last_price": None,
            "last_image_media_id": None,
            "last_image_filename": None,
            "last_image_size": None
        })
    return rows

def apply_overrides(auto_rows, overrides):
    idx = {r["erp_item_code"]: r for r in auto_rows}
    for ov in overrides:
        code = ov.get("erp_item_code")
        if not code:
            continue
        base = idx.get(code)
        if not base:
            base = {"erp_item_code": code}
            auto_rows.append(base)
            idx[code] = base
        # merge selective fields
        if ov.get("forced_wc_product_id") is not None:
            base["wc_product_id"] = ov["forced_wc_product_id"]
    return auto_rows

def build_or_load_mapping(path, wc_products, erp_items) -> Tuple[list, list]:
    raw = load_mapping_raw(path)
    if raw:
        raw = migrate_if_needed(raw)
        return raw["auto"], raw["overrides"]
    auto_rows = generate_auto_mapping(wc_products, erp_items)
    overrides = []
    save_mapping(path, auto_rows, overrides)
    return auto_rows, overrides


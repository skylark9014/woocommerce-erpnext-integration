# app/mapping/mapping_store.py

import json
import os
import time
import errno
import tempfile
import shutil
from json import JSONDecodeError
from typing import Tuple, List, Dict, Any, Optional
from datetime import datetime

SCHEMA_VERSION = 3  # bumped for image map support
SAVE_RETRIES = 5
SAVE_RETRY_DELAY_SECS = 0.15  # 150 ms
BACKUP_SUFFIX = ".corrupt.bak"


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# -------------------------------------------------
# Low-level load/save with basic migration + auto-fix
# -------------------------------------------------
def _try_repair_json(text: str) -> Optional[dict]:
    """
    Best‑effort fixer for a partially written/corrupted JSON file.
    - Strip NULLs / BOM
    - Drop trailing commas
    - Truncate to last closing brace/bracket
    Returns dict if successful, else None.
    """
    cleaned = text.replace("\x00", "").lstrip("\ufeff")

    # First simple attempt
    try:
        return json.loads(cleaned)
    except JSONDecodeError:
        pass

    # Remove trailing commas before } or ]
    import re
    cleaned2 = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned2)
    except JSONDecodeError:
        pass

    # Truncate to last complete JSON object/array
    last_obj = cleaned.rfind("}")
    last_arr = cleaned.rfind("]")
    cut = max(last_obj, last_arr)
    if cut != -1:
        truncated = cleaned[: cut + 1]
        try:
            return json.loads(truncated)
        except JSONDecodeError:
            pass

    return None


def load_mapping_raw(path: str) -> dict | None:
    """
    Load the raw JSON mapping file, attempting simple repairs on JSON errors.
    """
    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data_txt = f.read()

    try:
        return json.loads(data_txt)
    except JSONDecodeError:
        repaired = _try_repair_json(data_txt)
        if repaired is not None:
            # Backup the bad file
            try:
                shutil.copy2(path, path + BACKUP_SUFFIX)
            except Exception:
                pass
            _atomic_write(path, repaired)
            return repaired
        # Could not fix
        raise


def migrate_if_needed(data: dict) -> dict:
    """
    Ensure data has keys: auto, overrides, images, and the correct schema_version.
    """
    if "schema_version" not in data:
        # Assume oldest flat-list format
        data = {
            "schema_version": 2,
            "generated_at": now_iso(),
            "auto": data if isinstance(data, list) else [],
            "overrides": []
        }

    if data.get("schema_version", 0) < SCHEMA_VERSION:
        data.setdefault("images", {})
        data["schema_version"] = SCHEMA_VERSION

    return data


def _atomic_write(path: str, payload: dict):
    """
    POSIX-safe write: write to a temp file, chown it to match the
    directory owner (to avoid root-owned files on bind mounts), then rename.
    """
    directory = os.path.dirname(path) or "."
    # Get directory ownership
    try:
        st = os.stat(directory)
        dir_uid, dir_gid = st.st_uid, st.st_gid
    except Exception:
        dir_uid = dir_gid = None

    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(payload, tmp_file, indent=2, ensure_ascii=False)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        # Preserve ownership if possible
        if dir_uid is not None and dir_gid is not None:
            try:
                os.chown(tmp_path, dir_uid, dir_gid)
            except PermissionError:
                pass
        # Atomically replace
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def save_mapping(path: str, auto_rows: List[dict], overrides: List[dict], images: Dict[str, Any]):
    """
    Save the full mapping payload with retries for transient filesystem errors.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "auto": auto_rows,
        "overrides": overrides,
        "images": images,
    }

    for _ in range(SAVE_RETRIES):
        try:
            _atomic_write(path, payload)
            return
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EBUSY):
                time.sleep(SAVE_RETRY_DELAY_SECS)
                continue
            raise
    raise RuntimeError("Failed to save mapping after retries")


# -----------------------------
# Auto-mapping generation
# -----------------------------
def generate_auto_mapping(wc_products: List[dict], erp_items: List[dict]) -> List[dict]:
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
            # legacy single-image fields kept for backward-compatibility
            "last_image_media_id": None,
            "last_image_filename": None,
            "last_image_size": None
        })
    return rows


def apply_overrides(auto_rows: List[dict], overrides: List[dict]) -> List[dict]:
    """
    Apply any manual overrides (forced WC product IDs) onto the auto_rows.
    """
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
        if ov.get("forced_wc_product_id") is not None:
            base["wc_product_id"] = ov["forced_wc_product_id"]
    return auto_rows


def build_or_load_mapping(
    path: str,
    wc_products: List[dict],
    erp_items: List[dict]
) -> Tuple[List[dict], List[dict], Dict[str, Any]]:
    """
    If mapping file exists, load & migrate it; otherwise, generate a fresh one.
    Returns (auto_rows, overrides, images_map).
    """
    raw = load_mapping_raw(path)
    if raw:
        raw = migrate_if_needed(raw)
        return raw["auto"], raw["overrides"], raw.get("images", {})

    auto_rows = generate_auto_mapping(wc_products, erp_items)
    overrides: List[dict] = []
    images_map: Dict[str, Any] = {}
    save_mapping(path, auto_rows, overrides, images_map)
    return auto_rows, overrides, images_map


# -------------------------------------------------
# Image-map helpers (multi-image support)
# -------------------------------------------------
def get_images_for_item(
    images_map: Dict[str, List[Dict[str, Any]]],
    item_code: str
) -> List[Dict[str, Any]]:
    return images_map.get(item_code, [])


def upsert_image_mapping(
    images_map: Dict[str, List[Dict[str, Any]]],
    erp_item_code: str,
    erp_url: str,
    sha256: str,
    woo_media_id: Optional[int],
    filename: str,
    position: int,
):
    lst = images_map.setdefault(erp_item_code, [])
    for rec in lst:
        if rec["erp_url"] == erp_url:
            rec.update({
                "sha256": sha256,
                "woo_media_id": woo_media_id,
                "filename": filename,
                "position": position,
                "updated_at": now_iso(),
            })
            return
    lst.append({
        "erp_url": erp_url,
        "sha256": sha256,
        "woo_media_id": woo_media_id,
        "filename": filename,
        "position": position,
        "updated_at": now_iso(),
    })


def remove_image_mapping(
    images_map: Dict[str, List[Dict[str, Any]]],
    erp_item_code: str,
    erp_url: str
):
    lst = images_map.get(erp_item_code, [])
    images_map[erp_item_code] = [r for r in lst if r["erp_url"] != erp_url]

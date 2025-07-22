# =============================
# Admin UI for Mapping Management
# Serves static HTML/JS + preview-sync endpoint
# =============================

import os
import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from app.mapping.mapping_store import build_or_load_mapping, apply_overrides
from app.erp.erp_fetch import get_erpnext_items
from app.wc_fetch import get_wc_products
from env_config import MAPPING_JSON_FILE

router = APIRouter()
logger = logging.getLogger("uvicorn.error")

# -----------------------------
# ✅ Template & Static Setup
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Environment(loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")))

static_dir = os.path.join(BASE_DIR, "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

router.mount("/admin/static", StaticFiles(directory=static_dir), name="static")

# -----------------------------
# ✅ Admin Panel HTML
# -----------------------------
@router.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    template = templates.get_template("mapping.html")
    html = template.render()
    return HTMLResponse(content=html)

# -----------------------------
# ✅ Preview Sync (Dry Run)
# -----------------------------
@router.post("/admin/api/preview-sync")
async def preview_sync():
    try:
        erp_items = get_erpnext_items()
        wc_products = get_wc_products()
        auto_rows, overrides = build_or_load_mapping(MAPPING_JSON_FILE, wc_products, erp_items)
        apply_overrides(auto_rows, overrides)

        erp_index = {i["item_code"]: i for i in erp_items}
        wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}

        to_create, to_update, to_delete = [], [], []

        for row in auto_rows:
            code = row["erp_item_code"]
            wc = wc_index.get(code)
            if row.get("wc_product_id") is None and not wc:
                to_create.append(code)
            elif wc:
                erp_name = erp_index[code]["item_name"]
                wc_name = wc["name"]
                if erp_name != wc_name:
                    to_update.append(code)

        erp_codes = set(erp_index.keys())
        for sku in wc_index:
            if sku not in erp_codes:
                to_delete.append(sku)

        return JSONResponse({
            "status": "success",
            "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "actions": {
                "create": to_create,
                "update": to_update,
                "delete": to_delete
            },
            "counts": {
                "create": len(to_create),
                "update": len(to_update),
                "delete": len(to_delete)
            }
        })

    except Exception as e:
        logger.error(f"[PreviewSync] {e}")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


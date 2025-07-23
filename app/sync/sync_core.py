# =============================
# Sync Core Logic
# =============================

import asyncio
from app.sync.product_sync import sync_products

# Single lock to prevent concurrent full sync runs
sync_lock = asyncio.Lock()

# -----------------------------
# ✅ Run Full Product Sync (including images)
# -----------------------------
async def run_full_sync(pricelist: str | None = None, dry_run: bool = False):
    if sync_lock.locked():
        return {"status": "locked", "message": "Sync already in progress."}

    async with sync_lock:
        return await sync_products(pricelist=pricelist, dry_run=dry_run)

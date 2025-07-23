import asyncio
import os
from app.mapping.mapping_store import build_or_load_mapping, save_mapping
from app.sync.image_sync import sync_item_images
from app.config import MAPPING_JSON_FILE

# Change this to an item you know has images
ITEM_CODE = os.getenv("TEST_ITEM_CODE", "MST_120X60_ANDES")
DRY_RUN = os.getenv("DRY_RUN", "1") == "1"

async def main():
    auto_rows, overrides, images_map = build_or_load_mapping(MAPPING_JSON_FILE, [], [])
    row = next((r for r in auto_rows if r["erp_item_code"] == ITEM_CODE), None)
    if not row or not row.get("wc_product_id"):
        print(f"No wc_product_id for {ITEM_CODE}. Map it first.")
        return

    res = await sync_item_images(
        erp_item_code=ITEM_CODE,
        wc_product_id=row["wc_product_id"],
        images_map=images_map,
        dry_run=DRY_RUN,
    )
    print("RESULT:", res)
    if not DRY_RUN:
        save_mapping(MAPPING_JSON_FILE, auto_rows, overrides, images_map)

if __name__ == "__main__":
    asyncio.run(main())

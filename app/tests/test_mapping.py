import json
from app.mapping.mapping_store import (
    generate_auto_mapping,
    apply_overrides,
    build_or_load_mapping,
    save_mapping,
    migrate_if_needed,
)

def test_generate_auto_mapping_basic():
    erp = [{'item_code': 'X1'}, {'item_code': 'Y2'}]
    wc  = [{'id': 5, 'sku': 'X1'}]
    rows = generate_auto_mapping(wc, erp)
    assert len(rows) == 2
    assert rows[0]['erp_item_code'] == 'X1'
    assert rows[0]['wc_product_id'] == 5
    assert rows[1]['status'] == 'missing_wc'

def test_apply_overrides_forced_id():
    auto = [{'erp_item_code': 'Y2', 'wc_product_id': None}]
    overrides = [{'erp_item_code': 'Y2', 'forced_wc_product_id': 77}]
    apply_overrides(auto, overrides)
    assert auto[0]['wc_product_id'] == 77

def test_build_or_load_mapping_roundtrip(tmp_path):
    path = tmp_path / "map.json"
    erp = [{'item_code': 'A'}]
    wc  = []
    auto, ov = build_or_load_mapping(str(path), wc, erp)
    assert auto and auto[0]['erp_item_code'] == 'A'
    assert ov == []

    # add override and save
    ov = [{'erp_item_code': 'A', 'forced_wc_product_id': 12}]
    save_mapping(str(path), auto, ov)
    auto2, ov2 = build_or_load_mapping(str(path), wc, erp)
    assert ov2 == ov

def test_migrate_old_schema(tmp_path):
    path = tmp_path / "old.json"
    old = [{'erp_item_code': 'A'}]  # pre-schema file
    path.write_text(json.dumps(old))
    migrated = migrate_if_needed(json.loads(path.read_text()))
    assert migrated['schema_version'] == 2
    assert 'auto' in migrated and 'overrides' in migrated

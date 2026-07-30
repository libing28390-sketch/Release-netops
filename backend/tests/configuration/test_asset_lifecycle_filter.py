def test_asset_lifecycle_filter_uses_linked_device_state(isolated_db):
    from api import assets
    from database import get_db_connection

    created = assets.create_asset(
        assets.AssetCreate(
            asset_type='network_device',
            hostname='lifecycle-switch',
            management_ip='192.0.2.40',
            vendor='H3C',
            model='S5130',
            lifecycle_status='staging',
            asset_origin='new',
        )
    )

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE devices SET lifecycle_status = 'production' WHERE id = ?",
            (created['device_id'],),
        )
        conn.commit()
    finally:
        conn.close()

    production = assets.list_assets(lifecycle_status='production', page=1, page_size=50)
    staging = assets.list_assets(lifecycle_status='staging', page=1, page_size=50)

    assert [item['id'] for item in production['items']] == [created['id']]
    assert staging['items'] == []
    assert production['items'][0]['lifecycle_status'] == 'production'


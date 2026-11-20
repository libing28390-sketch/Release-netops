import uuid

from api import cmdb as cmdb_api
from services import cmdb_service
from schemas.schemas import SiteCreate, SiteImportRequest


def test_site_import_validates_duplicates_and_export_is_unpaginated(isolated_db, monkeypatch):
    monkeypatch.setattr(cmdb_api, '_audit', lambda *args, **kwargs: None)

    first = SiteCreate(
        site_name='North DC',
        country='United States',
        state_province='Virginia',
        city='Ashburn',
        contact_name='Network Ops',
        contact_phone='+12025550123',
        contact_email='ops@example.com',
        status='active',
    )
    imported = cmdb_api.api_import_sites(
        SiteImportRequest(rows=[first]),
        user={'username': 'tester', 'role': 'Operator'},
    )
    assert imported['success'] is True
    assert imported['data']['imported'] == 1
    assert imported['data']['failed'] == 0

    duplicate = cmdb_api.api_import_sites(
        SiteImportRequest(rows=[first]),
        user={'username': 'tester', 'role': 'Operator'},
    )
    assert duplicate['data']['imported'] == 0
    assert duplicate['data']['failed'] == 1
    assert '已存在' in duplicate['data']['errors'][0]['message']

    second = first.model_copy(update={'site_name': 'West DC'})
    mixed = cmdb_api.api_import_sites(
        SiteImportRequest(rows=[second, first]),
        user={'username': 'tester', 'role': 'Operator'},
    )
    assert mixed['data']['imported'] == 0
    assert mixed['data']['failed'] == 1

    listed = cmdb_api.api_list_sites(
        tenant_id='', q='West', page=None, page_size=20, _user={'role': 'Viewer'}
    )
    assert listed['data'] == []

    response = cmdb_api.api_export_sites(
        tenant_id='',
        q='North',
        _user={'username': 'tester', 'role': 'Viewer'},
    )
    content = response.body.decode('utf-8-sig')
    assert '站点编码' in content
    assert 'North DC' in content
    assert '+12025550123' in content


def test_site_import_supports_domestic_chinese_phone_numbers(isolated_db, monkeypatch):
    monkeypatch.setattr(cmdb_api, '_audit', lambda *args, **kwargs: None)

    mobile_site = SiteCreate(
        site_name='北京数据中心',
        country='China',
        state_province='北京',
        city='北京',
        contact_name='张三',
        contact_phone='13111111111',
        contact_email='zhangsan@example.com',
        status='active',
    )
    landline_site = SiteCreate(
        site_name='上海数据中心',
        country='中国',
        state_province='上海',
        city='上海',
        contact_name='李四',
        contact_phone='021-88888888',
        contact_email='lisi@example.com',
        status='active',
    )

    imported = cmdb_api.api_import_sites(
        SiteImportRequest(rows=[mobile_site, landline_site]),
        user={'username': 'tester', 'role': 'Operator'},
    )
    assert imported['success'] is True
    assert imported['data']['imported'] == 2
    assert imported['data']['failed'] == 0


def test_unpaged_site_cache_uses_database_revision_across_workers(isolated_db):
    query = f"cross-worker-{uuid.uuid4().hex}"
    site_name = f"Cross Worker Site {query}"

    first = cmdb_api.api_list_sites(
        tenant_id='', q=query, page=None, page_size=20, _user={'role': 'Viewer'}
    )
    assert first['data'] == []

    # Simulate a write in another API worker: the shared PostgreSQL revision
    # advances, while this process-local read cache receives no invalidation.
    writer = cmdb_api.get_db_connection()
    try:
        created = cmdb_service.create_site(writer, site_name=site_name)
    finally:
        writer.close()

    second = cmdb_api.api_list_sites(
        tenant_id='', q=query, page=None, page_size=20, _user={'role': 'Viewer'}
    )

    assert [row['id'] for row in second['data']] == [created['id']]
    assert second['data'][0]['site_name'] == site_name


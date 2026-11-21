from __future__ import annotations

import json
import uuid

from api import ipam as ipam_api
from database import get_db_connection
from services.ipam_address_space_service import create_address_space
from services.ipam_service import create_subnet


def _id(prefix: str) -> str:
    return f'{prefix}-{uuid.uuid4().hex[:10]}'


def _site(site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO sites(id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING""",
            (site_id, site_id.upper(), site_id),
        )
        conn.commit()


def _restricted_viewer(make_user, *, username: str, site_id: str) -> dict:
    row = make_user(username, role='Viewer', tenant_id='tenant-default')
    user = {
        'id': row['user_id'],
        'username': row['username'],
        'role': 'Viewer',
        'tenant_id': 'tenant-default',
        'scope_mode': 'restricted',
    }
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE users SET scope_mode = 'restricted' WHERE id = ?",
            (user['id'],),
        )
        conn.execute(
            """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'prefix', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (_id('ipam-scope'), user['id'], site_id, json.dumps(['view'])),
        )
        conn.commit()
    return user


def test_prefix_list_filters_rows_and_total_for_restricted_site_viewer(isolated_db, make_user):
    site_a, site_b = _id('ipam-visible-site'), _id('ipam-hidden-site')
    _site(site_a)
    _site(site_b)
    address_space = create_address_space(
        name='Scoped list Global', kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    visible = create_subnet(
        prefix='10.230.10.0/24', address_space_id=address_space['id'], site_id=site_a,
    )
    hidden = create_subnet(
        prefix='10.230.20.0/24', address_space_id=address_space['id'], site_id=site_b,
    )
    user = _restricted_viewer(make_user, username='ipam-restricted-prefix-viewer', site_id=site_a)

    result = ipam_api.api_list_subnets(
        site='all', status='all', q='', family='all', classification='all',
        page=1, page_size=20, user=user,
    )
    assert result['total'] == 1
    assert [item['id'] for item in result['items']] == [visible['id']]
    assert hidden['id'] not in {item['id'] for item in result['items']}

    hidden_filter = ipam_api.api_list_subnets(
        site=site_b, status='all', q='', family='all', classification='all',
        page=1, page_size=20, user=user,
    )
    assert hidden_filter['total'] == 0
    assert hidden_filter['items'] == []

from __future__ import annotations


def test_wan_link_actions_are_part_of_the_shared_permission_catalog() -> None:
    from core.rbac import permission_catalog

    assert permission_catalog()['wan_link'] == ['archive', 'create', 'read', 'test', 'update', 'view']


def test_wan_link_permissions_follow_viewer_and_operator_profiles() -> None:
    from core.rbac import authorize_resource

    viewer = {'role': 'Viewer'}
    operator = {'role': 'Operator'}
    named_viewer = {'role': 'Viewer', 'role_profile': 'Platform Viewer'}
    named_maintainer = {'role': 'Operator', 'role_profile': 'Platform Maintainer'}
    named_reviewer = {'role': 'Operator', 'role_profile': 'Release Manager'}

    assert authorize_resource(viewer, 'wan_link', 'read')
    assert not authorize_resource(viewer, 'wan_link', 'update')
    assert authorize_resource(operator, 'wan_link', 'create')
    assert authorize_resource(operator, 'wan_link', 'archive')
    assert authorize_resource(named_viewer, 'wan_link', 'view')
    assert not authorize_resource(named_viewer, 'wan_link', 'create')
    assert authorize_resource(named_maintainer, 'wan_link', 'test')
    assert authorize_resource(named_maintainer, 'wan_link', 'update')
    assert not authorize_resource(named_reviewer, 'wan_link', 'update')

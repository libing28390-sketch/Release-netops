import pytest
from fastapi import HTTPException


@pytest.fixture()
def review_case(isolated_db, make_user):
    from services.change_order_service import create_change_order, get_change_order, update_change_order
    from api.change_orders.helpers import APPROVAL_SNAPSHOT_VERSION, approval_snapshot_hash
    db = isolated_db['module']
    applicant = make_user('result-applicant')
    checker = make_user('result-checker', role='Viewer')
    initial = make_user('result-initial', role='Administrator')
    other = make_user('result-other', role='Administrator')
    conn = db.get_db_connection()
    try:
        order = create_change_order(conn, title='result review fixture', status='implementing',
            requester_id=applicant['user_id'], requester_username=applicant['username'],
            tenant_id=applicant.get('tenant_id') or 'tenant-default',
            assigned_initial_reviewer_id=initial['user_id'], assigned_initial_reviewer_username=initial['username'],
            control_sheet={'implementer': {'id': applicant['user_id'], 'username': applicant['username']},
                           'co_reviewer': {'id': checker['user_id'], 'username': checker['username']}})
        update_change_order(conn, order['id'], {'initial_reviewer_id': initial['user_id'], 'initial_reviewer_username': initial['username']})
        order = get_change_order(conn, order['id'])
        snapshot = approval_snapshot_hash(order)
        update_change_order(conn, order['id'], {'result_detail': {'approval_snapshot_hash': snapshot,
            'approval_snapshot_version': APPROVAL_SNAPSHOT_VERSION,
            'verification_records': [{'kind': 'technical', 'result': 'passed', 'approval_snapshot_hash': snapshot}]}})
    finally:
        conn.close()
    return db, order, applicant, checker, initial, other


def decide(case, person, action):
    from api.change_orders.result_review import api_result_review, ResultReviewRequest
    return api_result_review(case[1]['id'], ResultReviewRequest(action=action, summary=f'{action}: checked results'), person)['data']


def test_requester_can_submit_and_viewer_reviewer_can_close_without_execution_permission(review_case):
    case = review_case
    submitted = decide(case, case[2], 'submit')
    assert submitted['status'] == 'implementation_review'
    closed = decide(case, case[3], 'pass')
    assert closed['status'] == 'completed' and closed['actual_end']
    assert [record['action'] for record in closed['result_detail']['result_reviews']] == ['submit', 'pass']
    assert 'execution_token_id' not in closed['result_detail']
    with pytest.raises(HTTPException) as error:
        decide(case, case[3], 'pass')
    assert error.value.status_code == 409


@pytest.mark.parametrize('final_action,expected', [('accept', 'completed'), ('reject', 'failed')])
def test_abnormal_results_go_to_original_initial_reviewer(review_case, final_action, expected):
    case = review_case
    decide(case, case[2], 'submit')
    result = decide(case, case[3], 'fail')
    assert result['status'] == 'implementation_result_review'
    with pytest.raises(HTTPException) as error:
        decide(case, case[5], final_action)
    assert error.value.status_code == 403
    result = decide(case, case[4], final_action)
    assert result['status'] == expected
    assert 'execution_token_id' not in result['result_detail']


def test_wrong_actor_and_direct_transition_cannot_bypass_review(review_case):
    from api.change_orders.transition import api_transition_change_order
    case = review_case
    with pytest.raises(HTTPException) as error:
        api_transition_change_order(case[1]['id'], {'status': 'completed'}, case[2])
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        decide(case, case[5], 'submit')
    assert error.value.status_code == 403
    decide(case, case[2], 'submit')
    with pytest.raises(HTTPException) as error:
        decide(case, case[2], 'pass')
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        api_transition_change_order(case[1]['id'], {'status': 'completed'}, case[2])
    assert error.value.status_code == 409


def test_read_access_and_todo_follow_the_result_reviewer_then_initial_reviewer(review_case):
    from api.change_orders.core import _require_change_order_access
    from services.change_order_service import list_change_orders, get_summary
    case = review_case
    submitted = decide(case, case[2], 'submit')
    _require_change_order_access(submitted, case[3], 'view')
    conn = case[0].get_db_connection()
    try:
        rows, total = list_change_orders(conn, my_todo=case[3]['username'], my_todo_user_id=case[3]['user_id'])
        assert total == 1 and rows[0]['id'] == submitted['id']
        assert get_summary(conn, user_id=case[3]['user_id'], username=case[3]['username'])['my_todo_count'] == 1
        decide(case, case[3], 'fail')
        rows, total = list_change_orders(conn, my_todo=case[4]['username'], my_todo_user_id=case[4]['user_id'], my_todo_kind='review')
        assert total == 1 and rows[0]['status'] == 'implementation_result_review'
    finally:
        conn.close()


def test_submission_requires_existing_verification_and_unchanged_snapshot(review_case):
    from services.change_order_service import get_change_order, update_change_order
    case = review_case
    conn = case[0].get_db_connection()
    try:
        order = get_change_order(conn, case[1]['id'])
        detail = order['result_detail']
        detail['verification_records'] = []
        update_change_order(conn, order['id'], {'result_detail': detail})
    finally:
        conn.close()
    with pytest.raises(HTTPException) as error:
        decide(case, case[2], 'submit')
    assert error.value.status_code == 409


def test_review_freezes_edits_and_rejects_changed_scope(review_case):
    from api.change_orders.core import _require_change_order_access
    from services.change_order_service import update_change_order
    case = review_case
    submitted = decide(case, case[2], 'submit')
    with pytest.raises(HTTPException) as error:
        _require_change_order_access(submitted, case[2], 'update')
    assert error.value.status_code == 409
    conn = case[0].get_db_connection()
    try:
        update_change_order(conn, submitted['id'], {'commands': ['changed after submission']})
    finally:
        conn.close()
    with pytest.raises(HTTPException) as error:
        decide(case, case[3], 'pass')
    assert error.value.status_code == 409


def test_inactive_reviewer_cannot_submit_a_decision(review_case):
    case = review_case
    decide(case, case[2], 'submit')
    conn = case[0].get_db_connection()
    try:
        conn.execute("UPDATE users SET status = 'inactive' WHERE id = ?", (case[3]['user_id'],))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(HTTPException) as error:
        decide(case, case[3], 'pass')
    assert error.value.status_code == 403


def test_control_sheet_reviewer_is_optional_but_cannot_be_the_implementer(review_case):
    from api.change_orders.helpers import _validate_assignment_rules, _validate_control_sheet_completeness
    case = review_case
    person = {'id': case[2]['user_id'], 'username': case[2]['username']}
    sheet = {'implementer': person, 'change_time': {'start': '2026-10-25T09:00', 'end': '2026-10-25T10:00'},
             'device_ips': ['10.0.0.1'], 'pre_check': 'before', 'execution': 'manual steps',
             'post_verify': 'technical check', 'business_verify': 'service check', 'rollback_plan': 'restore'}
    payload = {'control_sheet': sheet}
    conn = case[0].get_db_connection()
    try:
        _validate_control_sheet_completeness(conn, case[1]['id'], payload, 'initial_review')
        _validate_assignment_rules(case[2]['username'], payload)
        with pytest.raises(HTTPException):
            _validate_assignment_rules(case[2]['username'], {'control_sheet': {**sheet, 'co_reviewer': person}})
    finally:
        conn.close()

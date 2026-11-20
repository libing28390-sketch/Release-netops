from services import diagnose_service


def test_acl_empty_output_remains_unknown():
    evidence = diagnose_service._classify_acl_evidence(
        '',
        '10.0.0.10',
        '10.0.1.20',
        'TCP',
        443,
    )

    assert evidence['decision'] == 'unknown'


def test_acl_explicit_unconfigured_and_matching_deny_are_distinct():
    unconfigured = diagnose_service._classify_acl_evidence(
        'Traffic policy is not applied on this interface',
        '10.0.0.10',
        '10.0.1.20',
        'TCP',
        443,
    )
    denied = diagnose_service._classify_acl_evidence(
        'deny tcp 10.0.0.10 10.0.1.20 eq 443',
        '10.0.0.10',
        '10.0.1.20',
        'TCP',
        443,
    )

    assert unconfigured['decision'] == 'not_configured'
    assert denied['decision'] == 'deny'
    assert denied['direction'] == 'egress'


def test_attached_acl_requires_rule_level_review():
    evidence = diagnose_service._classify_acl_evidence(
        'ip access-group EDGE-IN in',
        '10.0.0.10',
        '10.0.1.20',
        'TCP',
        443,
    )

    assert evidence['decision'] == 'review_required'


def test_missing_primary_evidence_caps_confidence():
    quality = diagnose_service._derive_evidence_quality(
        {
            'cef_verified': None,
            'acl_verified': None,
            'perf_warning': None,
            'ha_verified': None,
        },
        {'records': [], 'unknown': []},
        return_path_status='unavailable',
    )

    assert quality['status'] == 'unknown'
    assert quality['confidence_cap'] == 70
    assert '回程路径未完成实时验证' in quality['gaps']


def test_hop_interface_annotations_do_not_invent_ingress():
    hops = diagnose_service._annotate_hop_interfaces([
        {'hop': 1, 'interface_name': 'GigabitEthernet0/1'},
    ])

    assert hops[0]['ingress_interface'] == ''
    assert hops[0]['egress_interface'] == 'GigabitEthernet0/1'
    assert hops[0]['interface_evidence_status'] == 'partial'

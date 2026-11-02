"""Shared IPAM prefix classification rules for business network views."""

BUSINESS_UTILIZATION_NETWORK_TYPES = frozenset({
    'server', 'user', 'user_access', 'dmz', 'wireless', 'voice',
    'storage', 'container', 'vpn', 'vip',
})
INTERCONNECT_NETWORK_TYPES = frozenset({'transit', 'p2p', 'wan'})


def is_business_utilization_network(network_type: str | None) -> bool:
    normalized = str(network_type or '').strip().lower()
    if normalized == 'user':
        normalized = 'user_access'
    return normalized in BUSINESS_UTILIZATION_NETWORK_TYPES

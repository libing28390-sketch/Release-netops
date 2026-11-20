#!/usr/bin/env python3
"""Validate the current IPAM P4 human-review CSVs without accessing a database."""

from __future__ import annotations

import argparse
import csv
import ipaddress
import sys
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = REPO_ROOT / 'docs/plans/ipam_p4_mapping_review_20261110.csv'
DEFAULT_DUPLICATES = REPO_ROOT / 'docs/plans/ipam_p4_duplicate_review_20261110.csv'

MAPPING_COLUMNS = {
    'prefix_id', 'prefix_cidr', 'duplicate_resolution', 'canonical_prefix_id',
    'target_scope_request', 'target_address_space_id', 'current_address_space_id',
    'mapping_status',
}
DUPLICATE_COLUMNS = {
    'prefix_cidr', 'record_count', 'prefix_ids', 'mapped_prefix_ids',
    'unmapped_prefix_ids', 'existing_address_space_ids', 'duplicate_resolution',
    'canonical_prefix_id', 'target_scope_request', 'target_address_space_id',
}


def _read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'{path}: missing columns: {", ".join(sorted(missing))}')
        return [dict(row) for row in reader]


def _split_ids(value: str) -> set[str]:
    return {item.strip() for item in str(value or '').split('|') if item.strip()}


def _cell(row: dict[str, str], column: str) -> str:
    return str(row.get(column) or '').strip()


def validate(mapping_path: Path, duplicate_path: Path) -> list[str]:
    errors: list[str] = []
    mapping_rows = _read_csv(mapping_path, MAPPING_COLUMNS)
    duplicate_rows = _read_csv(duplicate_path, DUPLICATE_COLUMNS)

    by_id: dict[str, dict[str, str]] = {}
    by_network: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row_number, row in enumerate(mapping_rows, start=2):
        prefix_id = _cell(row, 'prefix_id')
        raw_network = _cell(row, 'prefix_cidr')
        if not prefix_id:
            errors.append(f'{mapping_path}:{row_number}: prefix_id is empty')
            continue
        if prefix_id in by_id:
            errors.append(f'{mapping_path}:{row_number}: duplicate prefix_id {prefix_id}')
        by_id[prefix_id] = row
        try:
            network = str(ipaddress.ip_network(raw_network, strict=False))
        except ValueError:
            errors.append(f'{mapping_path}:{row_number}: invalid CIDR {raw_network!r}')
            continue
        if network != raw_network:
            errors.append(
                f'{mapping_path}:{row_number}: CIDR {raw_network!r} is not canonical; expected {network!r}'
            )
        by_network[network].append(row)

        status = _cell(row, 'mapping_status')
        current_space = _cell(row, 'current_address_space_id')
        target_space = _cell(row, 'target_address_space_id')
        if status.startswith('已映射'):
            if not current_space or target_space != current_space:
                errors.append(
                    f'{mapping_path}:{row_number}: mapped row must preserve the current address-space ID'
                )
        elif status == '待人工确认' and target_space:
            errors.append(
                f'{mapping_path}:{row_number}: pending row must not contain a target address-space ID'
            )

        if _cell(row, 'canonical_prefix_id') and _cell(row, 'duplicate_resolution') == '不适用':
            errors.append(f'{mapping_path}:{row_number}: a non-duplicate row cannot select a canonical Prefix')

    expected_groups = {
        network: members for network, members in by_network.items() if len(members) > 1
    }
    seen_groups: set[str] = set()
    for row_number, group in enumerate(duplicate_rows, start=2):
        network = _cell(group, 'prefix_cidr')
        if network in seen_groups:
            errors.append(f'{duplicate_path}:{row_number}: duplicate review group {network}')
        seen_groups.add(network)
        members = expected_groups.get(network)
        if not members:
            errors.append(f'{duplicate_path}:{row_number}: {network} is not duplicated in the mapping sheet')
            continue

        member_ids = {_cell(row, 'prefix_id') for row in members}
        mapped_ids = {
            _cell(row, 'prefix_id') for row in members
            if _cell(row, 'target_address_space_id')
        }
        if _split_ids(_cell(group, 'prefix_ids')) != member_ids:
            errors.append(f'{duplicate_path}:{row_number}: member Prefix IDs do not match {network}')
        if _split_ids(_cell(group, 'mapped_prefix_ids')) != mapped_ids:
            errors.append(f'{duplicate_path}:{row_number}: mapped Prefix IDs do not match {network}')
        if _split_ids(_cell(group, 'unmapped_prefix_ids')) != member_ids - mapped_ids:
            errors.append(f'{duplicate_path}:{row_number}: unmapped Prefix IDs do not match {network}')
        if int(_cell(group, 'record_count') or 0) != len(members):
            errors.append(f'{duplicate_path}:{row_number}: record_count does not match {network}')
        expected_spaces = {
            _cell(row, 'target_address_space_id') for row in members
            if _cell(row, 'target_address_space_id')
        }
        if _split_ids(_cell(group, 'existing_address_space_ids')) != expected_spaces:
            errors.append(f'{duplicate_path}:{row_number}: existing address-space IDs do not match {network}')
        canonical_id = _cell(group, 'canonical_prefix_id')
        if canonical_id and canonical_id not in member_ids:
            errors.append(f'{duplicate_path}:{row_number}: canonical_prefix_id is not a member of {network}')
        resolution = _cell(group, 'duplicate_resolution')
        if 'canonical' in resolution.lower() and not canonical_id:
            errors.append(f'{duplicate_path}:{row_number}: canonical resolution requires canonical_prefix_id')

    missing_groups = set(expected_groups) - seen_groups
    for network in sorted(missing_groups):
        errors.append(f'{duplicate_path}: missing duplicate review group {network}')

    if errors:
        return errors
    mapped_count = sum(bool(_cell(row, 'target_address_space_id')) for row in mapping_rows)
    partial_groups = sum(
        bool(_cell(group, 'mapped_prefix_ids')) and bool(_cell(group, 'unmapped_prefix_ids'))
        for group in duplicate_rows
    )
    print(
        f'P4 mapping sheets valid: {len(mapping_rows)} Prefixes, '
        f'{mapped_count} mapped, {len(mapping_rows) - mapped_count} unmapped, '
        f'{len(duplicate_rows)} duplicate CIDR groups, {partial_groups} partly mapped groups.'
    )
    print('No target scope was inferred and no database was accessed.')
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping', type=Path, default=DEFAULT_MAPPING)
    parser.add_argument('--duplicates', type=Path, default=DEFAULT_DUPLICATES)
    args = parser.parse_args()
    try:
        errors = validate(args.mapping, args.duplicates)
    except (OSError, ValueError, csv.Error) as exc:
        print(f'Invalid P4 mapping input: {exc}', file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

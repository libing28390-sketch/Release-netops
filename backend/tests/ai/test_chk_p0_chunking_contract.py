from dataclasses import replace

import pytest

from ai.chunking.engine import ChunkingConfig, ChunkingEngine, ChunkingValidationError


NETWORK_SAMPLE = """# Huawei and Cisco structural sample

## Prerequisites
Ensure the device is reachable and the operator has read-only privilege.

This paragraph is a neutral context note for the operator.

## General context
Network operators should confirm the change window before collecting evidence.

## Huawei CLI example
```huawei
system-view
interface GigabitEthernet0/0/1
 description uplink to core
 undo shutdown
```

```output
<HUAWEI>display interface GigabitEthernet0/0/1
GigabitEthernet0/0/1 current state : UP
```

> Warning: changing the interface can interrupt traffic.

## Cisco verification example
```cisco
show interfaces GigabitEthernet1/0/1
show version
```

| Vendor | Command | Purpose |
| --- | --- | --- |
| Huawei | display interface | link state |
| Cisco | show interfaces | link state |
"""


def test_chk001_emits_the_network_structure_taxonomy():
    chunks = ChunkingEngine().chunk(
        NETWORK_SAMPLE,
        document_identity="chk-001",
        document_metadata={"vendor": "mixed", "document_version": "v1"},
    )

    structure_types = {item for chunk in chunks for item in chunk.structure_types}
    assert {"heading", "paragraph", "cli", "output", "table", "warning", "prerequisite", "example"} <= structure_types
    assert all(set(chunk.structure_types) <= {
        "heading", "paragraph", "cli", "output", "table", "warning", "prerequisite", "example", "code", "list"
    } for chunk in chunks)


def test_chk002_config_boundaries_are_validated():
    with pytest.raises(ValueError, match="overlap_ratio"):
        ChunkingConfig(overlap_ratio=0.5)
    with pytest.raises(ValueError, match="parent_min_blocks"):
        ChunkingConfig(parent_min_blocks=1)
    with pytest.raises(ValueError, match="max_tokens"):
        ChunkingConfig(target_tokens={"concept": 10}, max_tokens={"concept": 9})


def test_chk003_cli_groups_never_split_a_command_continuation():
    config = ChunkingConfig(
        target_tokens={"configuration": 5},
        max_tokens={"configuration": 8},
        min_tokens=1,
    )
    chunks = ChunkingEngine(config).chunk(
        """# Configure
```huawei
interface GigabitEthernet0/0/1
 description uplink to core
 undo shutdown
interface GigabitEthernet0/0/2
 description server
 undo shutdown
```
""",
        document_identity="chk-003",
    )
    children = [chunk for chunk in chunks if chunk.chunk_role == "child"]
    assert len(children) >= 2
    for child in children:
        content = child.raw_content
        if "interface GigabitEthernet0/0/1" in content:
            assert "description uplink to core" in content
            assert "undo shutdown" in content
        if "interface GigabitEthernet0/0/2" in content:
            assert "description server" in content
            assert "undo shutdown" in content


def test_chk004_neighbor_relations_are_explicit_and_symmetric():
    chunks = ChunkingEngine(
        ChunkingConfig(target_tokens={"concept": 5}, max_tokens={"concept": 10}, min_tokens=1)
    ).chunk(
        """# OSPF
## Verification
The first paragraph explains the check.

The second paragraph explains the expected state.

The third paragraph explains the remediation.
""",
        document_identity="chk-004",
    )
    ids = {chunk.chunk_id for chunk in chunks}
    assert any(chunk.neighbor_chunk_ids for chunk in chunks)
    for chunk in chunks:
        assert chunk.chunk_id not in chunk.neighbor_chunk_ids
        assert set(chunk.neighbor_chunk_ids) <= ids
        for neighbour_id in chunk.neighbor_chunk_ids:
            neighbour = next(item for item in chunks if item.chunk_id == neighbour_id)
            assert chunk.chunk_id in neighbour.neighbor_chunk_ids


def test_chk005_chunk_contract_fields_are_recorded():
    chunks = ChunkingEngine().chunk(
        "# Verify\n\n```cisco\nshow version\n```\n",
        document_identity="chk-005",
        document_metadata={
            "document_version": "source-v3",
            "parser_version": "parser-test-v1",
            "index_version": "index-test-v2",
            "page": 7,
        },
    )
    chunk = chunks[0]
    assert chunk.chunk_role in {"standalone", "parent", "child"}
    assert chunk.heading_path
    assert chunk.token_count > 0
    assert len(chunk.content_hash) == 64
    assert chunk.page == 7
    assert chunk.parser_version == "parser-test-v1"
    assert chunk.document_version == "source-v3"
    assert chunk.index_version == "index-test-v2"
    assert chunk.size_class in {"normal", "undersized", "oversized"}
    payload = chunk.to_dict()
    assert payload["structure_types"]
    assert payload["content_hash"] == chunk.content_hash


def test_chk006_huawei_cisco_cli_table_and_warning_integrity():
    chunks = ChunkingEngine().chunk(NETWORK_SAMPLE, document_identity="chk-006")
    combined = "\n".join(chunk.raw_content for chunk in chunks)
    for expected in (
        "system-view",
        "interface GigabitEthernet0/0/1",
        "show interfaces GigabitEthernet1/0/1",
        "| Huawei | display interface | link state |",
        "Warning: changing the interface",
    ):
        assert expected in combined


def test_chk007_empty_duplicate_and_atomic_oversize_are_detected():
    engine = ChunkingEngine(
        ChunkingConfig(
            target_tokens={"command": 2, "configuration": 2},
            max_tokens={"command": 3, "configuration": 3},
            min_tokens=1,
        )
    )
    assert engine.chunk("\n\n", document_identity="empty") == []
    commands = "\n".join(f"show interface GigabitEthernet0/0/{index}" for index in range(1, 21))
    chunks = engine.chunk(
        "# Commands\n\n```huawei\n" + commands + "\n```\n",
        document_identity="oversized",
    )
    assert any(chunk.oversize_reason for chunk in chunks)
    with pytest.raises(ChunkingValidationError, match="duplicate"):
        engine.validate([chunks[0], replace(chunks[0], chunk_id="duplicate-id", ordinal=999)])

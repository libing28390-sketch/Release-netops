from ai.chunking.engine import ChunkingConfig, ChunkingEngine, estimate_token_count


def test_heading_path_is_inherited_without_heading_only_chunks():
    engine = ChunkingEngine()
    chunks = engine.chunk(
        """# IP Routing

## OSPF

### Verify neighbors

```huawei
display ospf peer
```
""",
        document_identity="doc-1",
        document_metadata={"vendor": "Huawei", "platform": "huawei_vrp", "verified_version": "V600"},
    )

    assert chunks
    assert all(chunk.raw_content.strip() != "## OSPF" for chunk in chunks)
    assert any("IP Routing > OSPF" in chunk.raw_content for chunk in chunks)
    assert any(chunk.chunk_type in {"command", "verification"} for chunk in chunks)
    assert all(chunk.metadata["vendor"] == "Huawei" for chunk in chunks)


def test_code_fence_is_preserved_when_a_large_block_is_split():
    config = ChunkingConfig(
        target_tokens={"concept": 8, "configuration": 8},
        max_tokens={"concept": 12, "configuration": 12},
        min_tokens=1,
    )
    engine = ChunkingEngine(config=config)
    chunks = engine.chunk(
        """# SSH

## Configure access

```huawei
system-view
aaa
local-user operator
service-type ssh
authorization-attribute user-role network-admin
ssh server enable
line vty 0 4
authentication-mode aaa
```
""",
        document_identity="doc-2",
    )

    children = [chunk for chunk in chunks if chunk.chunk_role == "child"]
    assert len(children) >= 2
    assert all(chunk.raw_content.count("```") % 2 == 0 for chunk in children)
    assert all(chunk.parent_chunk_id for chunk in children)


def test_troubleshooting_creates_parent_and_contextual_children():
    engine = ChunkingEngine()
    chunks = engine.chunk(
        """# OSPF

## Neighbor stuck in ExStart

### Symptoms
The neighbor remains in ExStart.

### Causes
MTU mismatch or duplicate router ID.

### Verification
```h3c
display ospf peer
display interface
```

### Resolution
Correct MTU and verify the adjacency again.
""",
        document_identity="doc-3",
        document_metadata={"vendor": "H3C", "platform": "h3c_comware"},
    )

    parents = [chunk for chunk in chunks if chunk.chunk_role == "parent"]
    children = [chunk for chunk in chunks if chunk.chunk_role == "child"]
    assert len(parents) == 1
    assert len(children) >= 2
    assert all(child.parent_chunk_id == parents[0].chunk_id for child in children)
    assert any(child.chunk_type == "troubleshooting" for child in children)
    assert any("display ospf peer" in child.embedding_content for child in children)


def test_estimated_tokens_are_positive_and_cli_metadata_is_deterministic():
    text = "display ospf peer brief"
    assert estimate_token_count(text) > 0
    engine = ChunkingEngine()
    first = engine.chunk("## Verify\n\n```huawei\ndisplay ospf peer\n```", document_identity="same")
    second = engine.chunk("## Verify\n\n```huawei\ndisplay ospf peer\n```", document_identity="same")
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert first[-1].metadata["commands"] == ["display ospf peer"]

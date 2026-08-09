import json
import sqlite3

import pytest

from ai.providers.embedding import StableLocalEmbeddingProvider
from ai.services.intent_parser import intent_parser
from ai.services.knowledge_metadata import (
    MetadataParseError,
    MetadataValidationError,
    merge_metadata,
    parse_markdown_document,
    validate_metadata,
)


def _frontmatter(**overrides):
    values = {
        "schema_version": "1.1",
        "document_id": "demo.command",
        "title": "Demo",
        "vendor": "Huawei",
        "product_type": "switch",
        "document_category": "command",
        "source_type": "official",
        "official_only": True,
        "status": "active",
        "feature_domain": "routing",
        "feature": "ospf",
        "cli_platform": "huawei_yunshan_v600",
    }
    values.update(overrides)
    lines = ["---"] + [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in values.items()] + ["---", "", "# 正文", "display ospf peer"]
    return "\n".join(lines)


def test_frontmatter_is_stripped_and_original_preserved():
    raw = _frontmatter()
    parsed = parse_markdown_document(raw)
    assert parsed.metadata_parse_status == "parsed"
    assert parsed.original_content == raw
    assert "schema_version" not in parsed.content
    assert "display ospf peer" in parsed.content


def test_missing_frontmatter_is_explicit():
    parsed = parse_markdown_document("# 普通 Markdown\n\n正文")
    assert parsed.metadata_parse_status == "missing"
    assert parsed.metadata == {}
    assert parsed.content.startswith("# 普通")


def test_invalid_frontmatter_is_rejected():
    with pytest.raises(MetadataParseError):
        parse_markdown_document("---\n: invalid: [\n---\nbody")


def test_unicode_and_directory_validation_do_not_override_frontmatter():
    parsed = parse_markdown_document(_frontmatter(title="华为 OSPF 命令"))
    validated = validate_metadata(parsed.metadata, directory_path="kb_import/02_commands/huawei/demo.md")
    assert validated["title"] == "华为 OSPF 命令"
    merged = merge_metadata(validated, {"vendor": "Cisco", "knowledge_directory_path": "kb_import/02_commands/huawei"})
    assert merged["vendor"] == "Huawei"


def test_directory_category_conflict_is_rejected():
    with pytest.raises(MetadataValidationError):
        validate_metadata(parse_markdown_document(_frontmatter()).metadata, directory_path="kb_import/05_troubleshooting/huawei")


def test_embedding_contract_is_stable_and_batch_compatible():
    provider = StableLocalEmbeddingProvider()
    left = provider.embed_query("display ospf peer")
    right = provider.embed_documents(["display ospf peer"])[0]
    assert left == right
    assert len(left) == provider.dimensions
    assert provider.model_id
    assert provider.version


def test_local_embedding_keeps_terms_comparable_across_positions_and_chinese_phrases():
    provider = StableLocalEmbeddingProvider()

    def cosine(left, right):
        return sum(a * b for a, b in zip(left, right))

    query = provider.embed_query("display ospf peer 配置检查")
    reordered = provider.embed_query("华为配置检查使用 display ospf peer")
    unrelated = provider.embed_query("风扇温度与电源状态")
    assert cosine(query, reordered) > cosine(query, unrelated)
    assert provider.model_id.endswith("v2")


def test_intent_parser_emits_rag_v2_fields_without_platform_guessing():
    metadata = intent_parser.parse_knowledge_metadata("display ospf peer meaning")
    assert metadata["request_type"] == "knowledge"
    assert metadata["knowledge_type"] == "cli_output"
    assert metadata["document_category"] == "cli_output"
    assert metadata["feature"] == "ospf"
    assert metadata["cli_platform"] is None

"""Three-Tier Ops Neural Memory System (PostgreSQL-backed).

Implements a controllable, auditable, brain-inspired memory architecture for
Nexora AI Copilot without requiring an external graph database:
  1. Short-Term Working Memory (Rolling Summary): distills evicted older turns
     beyond the 12-turn sliding window into a compact entity & conclusion digest
     so 100-turn sessions retain early context at bounded token cost.
  2. Episodic Memory (`ai_memory_nodes`, memory_type='episodic'): stores
     resolved troubleshooting incidents / root-cause lessons with exponential
     time decay and Hebbian reinforcement (`weight` boosted on recall/upvote).
  3. Long-Term Semantic & Synapse Graph (`ai_memory_nodes` + `ai_memory_edges`):
     stores durable enterprise ops rules (change windows, HA pairs, team style)
     and entity relationship edges (`ha_peer_of`, `same_rack_as`, `resolved_by`)
     for 2-hop spreading-activation recall.

Safety Guardrails:
  - Secrets/credentials are scrubbed or rejected before persistence.
  - Real-time volatile telemetry/alarm counts are NEVER stored in long-term
    memory; live state always comes from the 12-module read-only tools.
"""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from ai.security.classification import PRIVATE_KEY_RE, SECRET_ASSIGNMENT_RE, redact_secrets
from database.core import get_db_connection

logger = logging.getLogger(__name__)

_MEMORY_TABLES_READY = False

_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_HOST_LIKE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]{2,40})\b")
_RACK_RE = re.compile(r"\b([A-Za-z]{1,4}-\d{1,3}(?:\s*U\d{1,2})?)\b")
_IGNORE_TOKENS = frozenset({
    "http", "https", "cmdb", "ipam", "snmp", "ospf", "bgp", "vlan", "lldp", "cdp",
    "ssh", "ntp", "pam", "down", "online", "offline", "core", "access", "switch",
    "firewall", "router", "comware", "huawei", "cisco", "ruijie", "h3c", "display",
    "show", "interface", "gigabitethernet", "current", "date", "token", "error",
})


def _ensure_memory_tables(conn: Any) -> None:
    global _MEMORY_TABLES_READY
    if _MEMORY_TABLES_READY:
        return
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_memory_nodes (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
                memory_type TEXT NOT NULL DEFAULT 'semantic',
                entity_key TEXT NOT NULL DEFAULT 'global',
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                hit_count INTEGER NOT NULL DEFAULT 0,
                created_by TEXT DEFAULT 'system',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_activated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_memory_edges (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
                source_key TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_key TEXT NOT NULL,
                weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_mem_nodes_tenant_entity ON ai_memory_nodes (tenant_id, entity_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_mem_edges_tenant_src ON ai_memory_edges (tenant_id, source_key)")
        conn.commit()
        _MEMORY_TABLES_READY = True
    except Exception as exc:
        logger.debug("Ensure neural memory tables skipped: %s", type(exc).__name__)
        try:
            conn.rollback()
        except Exception:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _contains_secret_material(text: str) -> bool:
    s = str(text or "")
    if PRIVATE_KEY_RE.search(s):
        return True
    # Check if redact_secrets actually changes the text (meaning live secret found)
    redacted, count = redact_secrets(s)
    if count > 0 or redacted != s:
        return True
    for m in SECRET_ASSIGNMENT_RE.finditer(s):
        val = (m.group(1) or "").strip()
        if val and any(c.isascii() and c.isalnum() for c in val) and not val.upper().startswith("<REDACTED"):
            return True
    return False


def _extract_entity_keys(text: str) -> List[str]:
    """Extract normalized entity keys (ip:..., device:..., vendor:...) from text."""
    s = str(text or "")
    lower = s.lower()
    keys: List[str] = []
    for ip in _IPV4_RE.findall(s):
        keys.append(f"ip:{ip}")
    for m in _HOST_LIKE_RE.findall(s):
        if m.lower() in _IGNORE_TOKENS:
            continue
        if any(c.isdigit() for c in m) or "-" in m or "_" in m:
            keys.append(f"device:{m.lower()}")
    for v_cn, v_en in (("华三", "h3c"), ("h3c", "h3c"), ("华为", "huawei"), ("huawei", "huawei"), ("思科", "cisco"), ("cisco", "cisco"), ("锐捷", "ruijie")):
        if v_cn in lower:
            keys.append(f"vendor:{v_en}")
    return list(dict.fromkeys(keys))[:12]


def _tokenize_keywords(text: str) -> set[str]:
    """Extract lightweight bilingual tokens for lexical resonance scoring."""
    s = str(text or "").lower()
    ascii_toks = {t for t in re.findall(r"[a-z0-9_.-]{2,32}", s) if t not in _IGNORE_TOKENS}
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", s)
    cjk_bigrams: set[str] = set()
    for run in cjk_runs:
        if len(run) <= 4:
            cjk_bigrams.add(run)
        for i in range(len(run) - 1):
            cjk_bigrams.add(run[i : i + 2])
    return ascii_toks | cjk_bigrams


# ── Layer 1: Short-Term Working Memory (Rolling Summary of Evicted Turns) ──

def build_rolling_summary(evicted_messages: Sequence[Dict[str, str]], max_chars: int = 600) -> str:
    """Distill older evicted turns into a compact 0-token entity & topic digest."""
    if not evicted_messages:
        return ""
    ips: List[str] = []
    devices: List[str] = []
    racks: List[str] = []
    topics: List[str] = []

    for msg in evicted_messages:
        role = str(msg.get("role") or "")
        text = str(msg.get("content") or "")
        for ip in _IPV4_RE.findall(text):
            if ip not in ips:
                ips.append(ip)
        for m in _HOST_LIKE_RE.findall(text):
            if m.lower() in _IGNORE_TOKENS:
                continue
            if (any(c.isdigit() for c in m) and ("-" in m or "_" in m)) and m not in devices:
                devices.append(m)
        for rk in _RACK_RE.findall(text):
            if rk not in racks and not _IPV4_RE.match(rk):
                racks.append(rk)
        if role == "user":
            snippet = " ".join(text.split())[:36]
            if snippet and snippet not in topics:
                topics.append(snippet)

    parts: List[str] = []
    if devices:
        parts.append(f"提及设备: {', '.join(devices[:8])}")
    if ips:
        parts.append(f"提及IP: {', '.join(ips[:6])}")
    if racks:
        parts.append(f"提及机柜/U位: {', '.join(racks[:6])}")
    if topics:
        parts.append(f"早期排查主题({len(evicted_messages)//2}轮): " + " → ".join(topics[-4:]))

    summary = "；".join(parts)
    if not summary:
        return ""
    return summary[:max_chars].rstrip()


# ── Layer 2 & 3: Long-Term Semantic/Episodic Nodes & Synapse Edges ──

def save_memory_node(
    *,
    title: str,
    content: str,
    memory_type: str = "semantic",
    entity_key: str = "global",
    tags: Optional[List[str]] = None,
    weight: float = 1.0,
    tenant_id: str = "tenant-default",
    created_by: str = "operator",
    related_entities: Optional[List[tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """Persist a long-term semantic or episodic memory node with secret guard."""
    clean_title = " ".join(str(title or "").strip().split())[:140]
    clean_content = str(content or "").strip()[:1000]
    if not clean_title or not clean_content:
        raise ValueError("title and content are required")
    if _contains_secret_material(clean_title) or _contains_secret_material(clean_content):
        raise ValueError("memory content contains prohibited secret or credential material")

    mtype = str(memory_type or "semantic").strip().lower()
    if mtype not in {"semantic", "episodic"}:
        mtype = "semantic"
    ekey = str(entity_key or "global").strip().lower()[:120] or "global"
    now = _now_iso()
    node_id = f"mem_{uuid.uuid4().hex[:12]}"
    safe_tags = [str(t).strip()[:32] for t in (tags or []) if str(t).strip()][:10]
    bounded_weight = max(0.2, min(float(weight or 1.0), 5.0))

    with get_db_connection() as conn:
        _ensure_memory_tables(conn)
        conn.execute(
            """
            INSERT INTO ai_memory_nodes (
                id, tenant_id, memory_type, entity_key, title, content,
                tags_json, weight, hit_count, created_by, created_at, updated_at, last_activated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                node_id, tenant_id or "tenant-default", mtype, ekey, clean_title, clean_content,
                json.dumps(safe_tags, ensure_ascii=False), bounded_weight, created_by or "operator",
                now, now, now,
            ),
        )
        # Create synapse edges connecting anchor entity to related entities/memory
        for rel, target in (related_entities or [])[:6]:
            rel_clean = str(rel or "related_to").strip().lower()[:40]
            tgt_clean = str(target or "").strip().lower()[:120]
            if rel_clean and tgt_clean:
                edge_id = f"edge_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO ai_memory_edges (id, tenant_id, source_key, relation, target_key, weight, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (edge_id, tenant_id or "tenant-default", ekey, rel_clean, tgt_clean, 1.0, now),
                )
        conn.commit()

    return {
        "id": node_id,
        "tenant_id": tenant_id or "tenant-default",
        "memory_type": mtype,
        "entity_key": ekey,
        "title": clean_title,
        "content": clean_content,
        "tags": safe_tags,
        "weight": bounded_weight,
        "hit_count": 0,
        "created_at": now,
    }


def add_memory_edge(
    *,
    source_key: str,
    relation: str,
    target_key: str,
    weight: float = 1.0,
    tenant_id: str = "tenant-default",
) -> Dict[str, Any]:
    """Create a directional synapse edge between two entity/memory keys."""
    src = str(source_key or "").strip().lower()[:120]
    rel = str(relation or "related_to").strip().lower()[:40]
    tgt = str(target_key or "").strip().lower()[:120]
    if not src or not tgt:
        raise ValueError("source_key and target_key are required")
    edge_id = f"edge_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    with get_db_connection() as conn:
        _ensure_memory_tables(conn)
        conn.execute(
            """
            INSERT INTO ai_memory_edges (id, tenant_id, source_key, relation, target_key, weight, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (edge_id, tenant_id or "tenant-default", src, rel, tgt, max(0.2, min(float(weight or 1.0), 5.0)), now),
        )
        conn.commit()
    return {"id": edge_id, "source_key": src, "relation": rel, "target_key": tgt, "weight": weight}


def reinforce_memory_node(memory_id: str, *, delta: float = 0.35, tenant_id: str = "tenant-default") -> bool:
    """Hebbian reinforcement: strengthen a memory node's weight and hit counter."""
    now = _now_iso()
    with get_db_connection() as conn:
        _ensure_memory_tables(conn)
        row = conn.execute(
            "SELECT weight, hit_count FROM ai_memory_nodes WHERE id = ? AND tenant_id = ?",
            (memory_id, tenant_id or "tenant-default"),
        ).fetchone()
        if not row:
            return False
        new_weight = max(0.2, min(5.0, float(row[0] or 1.0) + float(delta)))
        new_hits = int(row[1] or 0) + 1
        conn.execute(
            "UPDATE ai_memory_nodes SET weight = ?, hit_count = ?, last_activated_at = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
            (new_weight, new_hits, now, now, memory_id, tenant_id or "tenant-default"),
        )
        conn.commit()
        return True


def delete_memory_node(memory_id: str, *, tenant_id: str = "tenant-default") -> bool:
    with get_db_connection() as conn:
        _ensure_memory_tables(conn)
        cur = conn.execute(
            "DELETE FROM ai_memory_nodes WHERE id = ? AND tenant_id = ?",
            (memory_id, tenant_id or "tenant-default"),
        )
        conn.commit()
        return bool(getattr(cur, "rowcount", 0))


def list_memory_nodes(*, tenant_id: str = "tenant-default", memory_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        _ensure_memory_tables(conn)
        if memory_type:
            rows = conn.execute(
                """
                SELECT id, memory_type, entity_key, title, content, tags_json, weight, hit_count, created_by, created_at, last_activated_at
                FROM ai_memory_nodes WHERE tenant_id = ? AND memory_type = ?
                ORDER BY weight DESC, updated_at DESC LIMIT ?
                """,
                (tenant_id or "tenant-default", memory_type, max(1, min(limit, 200))),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, memory_type, entity_key, title, content, tags_json, weight, hit_count, created_by, created_at, last_activated_at
                FROM ai_memory_nodes WHERE tenant_id = ?
                ORDER BY weight DESC, updated_at DESC LIMIT ?
                """,
                (tenant_id or "tenant-default", max(1, min(limit, 200))),
            ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            tags = json.loads(r[5] or "[]")
        except Exception:
            tags = []
        out.append({
            "id": r[0], "memory_type": r[1], "entity_key": r[2], "title": r[3],
            "content": r[4], "tags": tags, "weight": round(float(r[6] or 1.0), 3),
            "hit_count": int(r[7] or 0), "created_by": r[8], "created_at": r[9],
            "last_activated_at": r[10],
        })
    return out


def activate_memories(
    query: str,
    *,
    tenant_id: str = "tenant-default",
    extra_entities: Optional[Sequence[str]] = None,
    top_k: int = 4,
) -> Dict[str, Any]:
    """2-hop spreading-activation recall over long-term semantic & episodic memory.

    Hop 1: Match seed entity_keys + lexical resonance on `ai_memory_nodes`.
    Hop 2: Expand via `ai_memory_edges` (bidirectional) so mentioning S6850_1
           also activates its HA peer S6850-2 or linked incident memories.
    Applies exponential time decay (half-life ~90 days for episodic, ~365 days
    for semantic) and Hebbian hit reinforcement on returned top-K nodes.
    """
    seed_entities = set(_extract_entity_keys(query))
    for item in (extra_entities or []):
        s = str(item or "").strip().lower()
        if s:
            seed_entities.add(s)
    query_tokens = _tokenize_keywords(query)
    if not seed_entities and not query_tokens:
        return {"nodes": [], "edges": [], "prompt_block": ""}

    now_dt = datetime.now(timezone.utc)
    tenant = tenant_id or "tenant-default"
    neighbor_entities: set[str] = set()
    activated_edges: List[Dict[str, Any]] = []

    try:
        with get_db_connection() as conn:
            _ensure_memory_tables(conn)
            # Hop 1 -> 2: Expand synapse edges connected to seed entities
            if seed_entities:
                edge_rows = conn.execute(
                    "SELECT source_key, relation, target_key, weight FROM ai_memory_edges WHERE tenant_id = ? LIMIT 200",
                    (tenant,),
                ).fetchall()
                for src, rel, tgt, ew in edge_rows:
                    src_l, tgt_l = str(src or "").lower(), str(tgt or "").lower()
                    if src_l in seed_entities:
                        neighbor_entities.add(tgt_l)
                        activated_edges.append({"source": src_l, "relation": rel, "target": tgt_l, "weight": float(ew or 1.0)})
                    elif tgt_l in seed_entities:
                        neighbor_entities.add(src_l)
                        activated_edges.append({"source": src_l, "relation": rel, "target": tgt_l, "weight": float(ew or 1.0)})

            all_rows = conn.execute(
                """
                SELECT id, memory_type, entity_key, title, content, tags_json, weight, hit_count, last_activated_at, updated_at
                FROM ai_memory_nodes WHERE tenant_id = ?
                ORDER BY weight DESC, updated_at DESC LIMIT 200
                """,
                (tenant,),
            ).fetchall()

            scored: List[tuple[float, Dict[str, Any]]] = []
            for r in all_rows:
                node_id, mtype, ekey, title, content, tags_json, weight, hits, last_act, upd = r
                ekey_l = str(ekey or "").lower()
                base_weight = max(0.2, float(weight or 1.0))

                # Time decay: semantic decays very slowly (365d), episodic decays faster (90d)
                ref_dt = _parse_iso(last_act) or _parse_iso(upd)
                age_days = max(0.0, (now_dt - ref_dt).total_seconds() / 86400.0) if ref_dt else 0.0
                half_life = 365.0 if mtype == "semantic" else 90.0
                decay = math.exp(-math.log(2) * (age_days / half_life))

                # Activation score: direct entity match > 1-hop synapse neighbor > lexical overlap
                entity_score = 0.0
                if ekey_l in seed_entities:
                    entity_score = 3.0
                elif ekey_l in neighbor_entities:
                    entity_score = 1.8

                node_tokens = _tokenize_keywords(f"{title} {content} {tags_json}")
                overlap = len(query_tokens & node_tokens)
                lex_score = min(2.0, overlap * 0.45)

                raw_activation = entity_score + lex_score
                if raw_activation < 0.85:
                    continue
                final_score = raw_activation * base_weight * decay
                scored.append((final_score, {
                    "id": node_id,
                    "memory_type": mtype,
                    "entity_key": ekey_l,
                    "title": title,
                    "content": content,
                    "score": round(final_score, 3),
                }))

            scored.sort(key=lambda pair: pair[0], reverse=True)
            top_nodes = [item for _, item in scored[: max(1, min(top_k, 6))]]

            # Light Hebbian reinforcement on recalled nodes
            if top_nodes:
                now_str = _now_iso()
                for n in top_nodes:
                    conn.execute(
                        "UPDATE ai_memory_nodes SET hit_count = hit_count + 1, last_activated_at = ? WHERE id = ? AND tenant_id = ?",
                        (now_str, n["id"], tenant),
                    )
                conn.commit()
    except Exception as exc:
        logger.debug("Memory activation skipped: %s", type(exc).__name__)
        return {"nodes": [], "edges": [], "prompt_block": ""}

    if not top_nodes and not activated_edges:
        return {"nodes": [], "edges": [], "prompt_block": ""}

    lines: List[str] = []
    for n in top_nodes:
        tag = "历史案例" if n["memory_type"] == "episodic" else "企业常识"
        lines.append(f"- [{tag}·{n['entity_key']}] {n['title']}: {n['content'][:140]}")
    for e in activated_edges[:3]:
        lines.append(f"- [实体关联] {e['source']} --({e['relation']})--> {e['target']}")

    prompt_block = "\n".join(lines)[:550]
    return {"nodes": top_nodes, "edges": activated_edges[:5], "prompt_block": prompt_block}

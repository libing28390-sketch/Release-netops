"""Create outbound probes configuration and status tables."""

VERSION = 24
NAME = "outbound_probes"


def upgrade(cursor, _use_pg: bool) -> None:
    # 1. 创建配置表 outbound_probe_targets
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS outbound_probe_targets (
            id           TEXT PRIMARY KEY,
            target_name  TEXT NOT NULL UNIQUE,
            host         TEXT NOT NULL,
            port         INTEGER NOT NULL,
            probe_type   TEXT NOT NULL DEFAULT 'tcp',
            is_active    BOOLEAN NOT NULL DEFAULT TRUE,
            created_at   TEXT NOT NULL
        )
        """
    )

    # 2. 创建样本数据表 outbound_probe_samples
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS outbound_probe_samples (
            id             TEXT PRIMARY KEY,
            timestamp      TEXT NOT NULL,
            success_count  INTEGER NOT NULL,
            total_targets  INTEGER NOT NULL,
            success_rate   REAL NOT NULL,
            egress_ip      TEXT DEFAULT '',
            avg_latency_ms REAL NOT NULL
        )
        """
    )

    # 3. 注入默认拨测目标
    cursor.execute("SELECT COUNT(*) FROM outbound_probe_targets")
    count = cursor.fetchone()[0]
    if count == 0:
        import uuid
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        defaults = [
            (str(uuid.uuid4()), "Aliyun DNS", "223.5.5.5", 53, "TCP_CONNECT", True, now),
            (str(uuid.uuid4()), "Tencent DNS", "119.29.29.29", 53, "TCP_CONNECT", True, now),
            (str(uuid.uuid4()), "Baidu Web", "www.baidu.com", 443, "TCP_CONNECT", True, now),
            (str(uuid.uuid4()), "Aliyun Web", "www.aliyun.com", 443, "TCP_CONNECT", True, now),
        ]
        placeholder = "%s" if _use_pg else "?"
        for row in defaults:
            cursor.execute(
                f"""
                INSERT INTO outbound_probe_targets (id, target_name, host, port, probe_type, is_active, created_at)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                """,
                row
            )

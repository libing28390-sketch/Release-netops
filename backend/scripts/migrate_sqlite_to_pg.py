"""
一次性数据迁移脚本：SQLite (data/netops.db) → PostgreSQL。

用法（在 backend 目录下，且 .env 中 DATABASE_URL 已指向 PostgreSQL）：
    python scripts/migrate_sqlite_to_pg.py
    python scripts/migrate_sqlite_to_pg.py --dry-run     # 仅统计，不写入
    python scripts/migrate_sqlite_to_pg.py --sqlite /path/to/netops.db

流程：
1. 以 PostgreSQL 模式初始化目标库 schema（init_db 建表 + 迁移）。
2. 打开源 SQLite 库，按表逐一搬运两边都存在的公共列。
3. 迁移期间通过 session_replication_role='replica' 关闭外键/触发器，
   使表的搬运顺序无关紧要，并保留原始 created_at / updated_at 值。
4. 迁移完成后修正所有 SERIAL 自增序列的当前值。

幂等：每张表迁移前会 TRUNCATE ... CASCADE，可安全重复执行。
"""

import os
import sys
import argparse
import sqlite3

# 确保可以 import 到 backend 顶层包
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)

import database  # noqa: E402
from database import get_db_connection, _USE_PG, init_db, DB_PATH  # noqa: E402


def _convert(value, pg_type: str):
    """把 SQLite 取出的值转换为适配 PostgreSQL 列类型的值。"""
    if value is None:
        return None
    if pg_type == 'boolean':
        if isinstance(value, str):
            return value.strip().lower() in ('1', 't', 'true', 'yes', 'y')
        return bool(value)
    if pg_type in ('json', 'jsonb'):
        # 空串无法转成 jsonb，按 NULL 处理；其余交给 PG 的 text→jsonb 隐式转换
        if isinstance(value, str) and value.strip() == '':
            return None
        return value
    if pg_type in ('integer', 'bigint', 'smallint'):
        if isinstance(value, str):
            s = value.strip()
            if s == '':
                return None
            try:
                return int(float(s)) if '.' in s else int(s)
            except ValueError:
                return None
        if isinstance(value, bool):
            return int(value)
        return value
    if pg_type in ('numeric', 'real', 'double precision'):
        if isinstance(value, str):
            s = value.strip()
            if s == '':
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return value
    return value


def main():
    parser = argparse.ArgumentParser(description='Migrate SQLite data into PostgreSQL.')
    parser.add_argument('--sqlite', default=DB_PATH, help='Path to source SQLite DB file.')
    parser.add_argument('--dry-run', action='store_true', help='Only report row counts, do not write.')
    args = parser.parse_args()

    if not _USE_PG:
        print('[ERROR] DATABASE_URL 不是 PostgreSQL。请确认根目录 .env 中 '
              'DATABASE_URL=postgresql://... 后重试。')
        sys.exit(1)

    if not os.path.exists(args.sqlite):
        print(f'[ERROR] 找不到源 SQLite 库：{args.sqlite}')
        sys.exit(1)

    print(f'[1/4] 初始化 PostgreSQL schema（建表 + 迁移）...')
    init_db()

    print(f'[2/4] 打开源 SQLite 库：{args.sqlite}')
    sconn = sqlite3.connect(args.sqlite)
    sconn.row_factory = sqlite3.Row

    sqlite_tables = [
        r[0] for r in sconn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    # schema_migrations 由 PG 自身的 init_db / run_migrations 管理，不从 SQLite 覆盖
    _EXCLUDE = {'schema_migrations'}
    sqlite_tables = [t for t in sqlite_tables if t not in _EXCLUDE]
    print(f'      源库共发现 {len(sqlite_tables)} 张待迁移表。')

    pg = get_db_connection()

    # 预先解析每张表的 PG 列类型与公共列
    plan = []  # (table, common_cols, pg_types)
    skipped = []
    for table in sqlite_tables:
        cols_info = pg.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = %s", (table,)
        ).fetchall()
        pg_types = {c['column_name']: c['data_type'] for c in cols_info}
        if not pg_types:
            skipped.append(table)
            continue
        s_cols = [r[1] for r in sconn.execute(f'PRAGMA table_info("{table}")').fetchall()]
        common = [c for c in s_cols if c in pg_types]
        if not common:
            skipped.append(table)
            continue
        plan.append((table, common, pg_types))

    if skipped:
        print(f'      跳过（PG 中不存在或无公共列）：{", ".join(skipped)}')

    if args.dry_run:
        print('[3/4] DRY-RUN：仅统计行数，不写入。')
        total = 0
        for table, common, _ in plan:
            cnt = sconn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            total += cnt
            print(f'      {table:<40} {cnt:>8} 行  ({len(common)} 列)')
        print(f'      合计 {total} 行，共 {len(plan)} 张表可迁移。')
        sconn.close()
        return

    print(f'[3/4] 开始迁移 {len(plan)} 张表 ...')
    # 关闭外键/触发器校验，使搬运顺序无关
    pg.execute("SET session_replication_role = 'replica'")

    # 先清空所有目标表
    target_tables = [t for t, _, _ in plan]
    if target_tables:
        quoted = ', '.join(f'"{t}"' for t in target_tables)
        pg.execute(f'TRUNCATE TABLE {quoted} CASCADE')

    summary = []
    for table, common, pg_types in plan:
        rows = sconn.execute(f'SELECT * FROM "{table}"').fetchall()
        collist = ', '.join(f'"{c}"' for c in common)
        placeholders = ', '.join(['%s'] * len(common))
        sql = f'INSERT INTO "{table}" ({collist}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'

        ok = 0
        failed = 0
        for row in rows:
            vals = [_convert(row[c], pg_types[c]) for c in common]
            try:
                pg.execute(sql, vals)
                ok += 1
            except Exception as exc:
                failed += 1
                if failed <= 3:
                    print(f'      [WARN] {table}: 行插入失败 -> {exc}')
        summary.append((table, len(rows), ok, failed))
        print(f'      {table:<40} 读取 {len(rows):>7}  写入 {ok:>7}  失败 {failed:>4}')

    pg.commit()

    print('[4/4] 修正 SERIAL 自增序列 ...')
    fixed_seqs = 0
    for table, common, pg_types in plan:
        if 'id' not in pg_types:
            continue
        try:
            seq_row = pg.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,)).fetchone()
            seq = seq_row[0] if seq_row else None
            if seq:
                pg.execute(
                    f'SELECT setval(%s, COALESCE((SELECT MAX(id) FROM "{table}"), 1))',
                    (seq,)
                )
                fixed_seqs += 1
        except Exception as exc:
            print(f'      [WARN] {table}: 序列修正失败 -> {exc}')
    pg.commit()

    # 恢复正常复制角色
    try:
        pg.execute("SET session_replication_role = 'origin'")
        pg.commit()
    except Exception:
        pass

    sconn.close()
    pg.close()

    print('\n══════════ 迁移完成 ══════════')
    total_read = sum(s[1] for s in summary)
    total_ok = sum(s[2] for s in summary)
    total_failed = sum(s[3] for s in summary)
    print(f'表数: {len(summary)}  读取: {total_read}  写入: {total_ok}  失败: {total_failed}  '
          f'修正序列: {fixed_seqs}')
    if total_failed:
        print('存在失败行，请检查上面的 [WARN] 输出。')


if __name__ == '__main__':
    main()

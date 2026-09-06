"""Normalize historical site aliases to the canonical ``sites.id``."""

VERSION = 20
NAME = "site_alias_normalization"


def _resolve_site(cursor, value):
    raw = str(value or '').strip()
    if not raw:
        return None
    return cursor.execute(
        """SELECT id, site_code, site_name FROM sites
           WHERE LOWER(TRIM(id)) = LOWER(TRIM(?))
              OR LOWER(TRIM(site_code)) = LOWER(TRIM(?))
              OR LOWER(TRIM(site_name)) = LOWER(TRIM(?))
           ORDER BY CASE
               WHEN LOWER(TRIM(id)) = LOWER(TRIM(?)) THEN 0
               WHEN LOWER(TRIM(site_code)) = LOWER(TRIM(?)) THEN 1
               ELSE 2
           END, id LIMIT 1""",
        (raw, raw, raw, raw, raw),
    ).fetchone()


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    try:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    except Exception:
        return set()


def _normalize_table(cursor, table: str, columns: set[str], display_column: str | None = None) -> None:
    if 'site_id' not in columns:
        return
    rows = cursor.execute(
        f"SELECT id, site_id FROM {table} WHERE COALESCE(site_id, '') <> ''"
    ).fetchall()
    for row in rows:
        site = _resolve_site(cursor, row[1])
        if not site:
            continue
        if display_column and display_column in columns:
            cursor.execute(
                f"UPDATE {table} SET site_id = ?, {display_column} = ? WHERE id = ?",
                (site[0], site[2] or site[1] or site[0], row[0]),
            )
        else:
            cursor.execute(f"UPDATE {table} SET site_id = ? WHERE id = ?", (site[0], row[0]))


def _normalize_site_column(cursor, table: str, columns: set[str], column: str) -> None:
    if column not in columns:
        return
    rows = cursor.execute(
        f"SELECT id, {column} FROM {table} WHERE COALESCE({column}, '') <> ''"
    ).fetchall()
    for row in rows:
        site = _resolve_site(cursor, row[1])
        if site:
            cursor.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (site[0], row[0]))


def upgrade(cursor, use_pg: bool) -> None:
    table_columns = {
        table: _columns(cursor, table, use_pg)
        for table in ('devices', 'physical_assets', 'racks', 'topology_links', 'topology_observations')
    }
    _normalize_table(cursor, 'devices', table_columns['devices'], 'site')
    _normalize_table(cursor, 'physical_assets', table_columns['physical_assets'], 'datacenter')
    _normalize_table(cursor, 'racks', table_columns['racks'], 'datacenter')
    for table, columns in table_columns.items():
        _normalize_site_column(cursor, table, columns, 'source_site_id')
        _normalize_site_column(cursor, table, columns, 'target_site_id')

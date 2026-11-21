import database
from database.migrations.m0258_outbound_probe_icmp_quality import upgrade


def test_m0258_adds_quality_columns_idempotently_to_postgres(isolated_db):
    connection = database.get_db_connection()
    try:
        cursor = connection.cursor()
        upgrade(cursor, use_pg=True)
        upgrade(cursor, use_pg=True)
        connection.commit()

        columns = {
            str(row[0])
            for row in cursor.execute(
                """
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'outbound_probe_results'
                """
            ).fetchall()
        }
        assert {"packet_loss_percent", "rtt_jitter_ms"}.issubset(columns)
    finally:
        connection.close()

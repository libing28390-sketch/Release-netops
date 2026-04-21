from backend.database import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()

# Delete pytest scenarios
cursor.execute("DELETE FROM custom_scenarios WHERE id LIKE 'pytest_%'")
conn.commit()
print("Deleted pytest scenarios:", cursor.rowcount)

conn.close()

import sqlite3
conn = sqlite3.connect("data/netops.db")
conn.execute("DELETE FROM login_failures WHERE username = 'admin'")
conn.commit()
print("Login lockout cleared for admin")
conn.close()

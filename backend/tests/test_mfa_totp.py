import pytest
import hmac
import hashlib
import time
import base64
import struct
from fastapi.testclient import TestClient
from main import app
from api.users import verify_totp, generate_totp_secret
from database import get_db_connection

def generate_totp_code(secret: str, time_offset: int = 0) -> str:
    missing_padding = len(secret) % 8
    if missing_padding:
        secret += '=' * (8 - missing_padding)
    key = base64.b32decode(secret, casefold=True)
    t = int(time.time() / 30) + time_offset
    msg = struct.pack(">Q", t)
    hmac_hash = hmac.new(key, msg, hashlib.sha1).digest()
    offset = hmac_hash[-1] & 0x0f
    truncated = struct.unpack(">I", hmac_hash[offset:offset+4])[0] & 0x7fffffff
    computed_code = truncated % 1000000
    return f"{computed_code:06d}"

def test_totp_algorithm():
    # 1. Generate secret
    secret = generate_totp_secret()
    assert len(secret) == 16
    
    # 2. Verify current code is valid
    code = generate_totp_code(secret)
    assert verify_totp(secret, code) is True
    
    # 3. Verify window drift (t-1 and t+1 should be valid)
    code_prev = generate_totp_code(secret, time_offset=-1)
    code_next = generate_totp_code(secret, time_offset=1)
    assert verify_totp(secret, code_prev, window=1) is True
    assert verify_totp(secret, code_next, window=1) is True
    
    # 4. Verify outside window is invalid
    code_far = generate_totp_code(secret, time_offset=2)
    assert verify_totp(secret, code_far, window=1) is False
    
    # 5. Invalid values
    assert verify_totp(secret, "abc") is False
    assert verify_totp("invalid_secret", code) is False

@pytest.mark.asyncio
async def test_mfa_setup_enable_login_and_disable_flow(isolated_db):
    client = TestClient(app)
    
    # 1. Create a user with a known password
    from api.users import _hash_password
    conn = get_db_connection()
    hashed = await _hash_password("MySecurePass123!")
    conn.execute(
        "INSERT INTO users (id, username, password, role, status, mfa_enabled, mfa_secret) VALUES (?, ?, ?, ?, ?, 0, '')",
        ("test-mfa-user-id", "mfauser", hashed, "Operator", "active")
    )
    conn.commit()
    conn.close()
    
    # 2. Perform initial login (should succeed immediately since MFA is disabled)
    response = client.post("/api/login", json={"username": "mfauser", "password": "MySecurePass123!"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "token" in data
    token = data["token"]
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3. Request MFA setup
    response = client.post("/api/mfa/setup", headers=headers)
    assert response.status_code == 200
    setup_data = response.json()
    assert setup_data["success"] is True
    secret = setup_data["secret"]
    
    # 4. Enable MFA with incorrect code
    response = client.post("/api/mfa/enable", json={"code": "000000", "secret": secret}, headers=headers)
    assert response.status_code == 400
    
    # 5. Enable MFA with correct code
    correct_code = generate_totp_code(secret)
    response = client.post("/api/mfa/enable", json={"code": correct_code, "secret": secret}, headers=headers)
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    # Check DB state
    conn = get_db_connection()
    user_row = conn.execute("SELECT mfa_enabled, mfa_secret FROM users WHERE id = ?", ("test-mfa-user-id",)).fetchone()
    conn.close()
    assert user_row["mfa_enabled"] == 1
    assert user_row["mfa_secret"] == secret
    
    # 6. Try logging in again — should require MFA
    response = client.post("/api/login", json={"username": "mfauser", "password": "MySecurePass123!"})
    assert response.status_code == 200
    login_data = response.json()
    assert login_data["mfa_required"] is True
    temp_token = login_data["temp_token"]
    
    # 7. Verify MFA login with wrong code
    response = client.post("/api/mfa/verify", json={"temp_token": temp_token, "code": "000000"})
    assert response.status_code == 401
    
    # 8. Verify MFA login with correct code
    mfa_code = generate_totp_code(secret)
    response = client.post("/api/mfa/verify", json={"temp_token": temp_token, "code": mfa_code})
    assert response.status_code == 200
    verify_data = response.json()
    assert "token" in verify_data
    new_token = verify_data["token"]
    
    # 9. Disable MFA with wrong password
    headers_new = {"Authorization": f"Bearer {new_token}"}
    response = client.post("/api/mfa/disable", json={"password": "WrongPassword123"}, headers=headers_new)
    assert response.status_code == 400
    
    # 10. Disable MFA with correct password
    response = client.post("/api/mfa/disable", json={"password": "MySecurePass123!"}, headers=headers_new)
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    # Check DB state again
    conn = get_db_connection()
    user_row = conn.execute("SELECT mfa_enabled, mfa_secret FROM users WHERE id = ?", ("test-mfa-user-id",)).fetchone()
    conn.close()
    assert user_row["mfa_enabled"] == 0
    assert user_row["mfa_secret"] == ""
    
    # 11. Final login — should succeed directly again
    response = client.post("/api/login", json={"username": "mfauser", "password": "MySecurePass123!"})
    assert response.status_code == 200
    assert "token" in response.json()
    assert "mfa_required" not in response.json()

def test_pam_verify_mfa_smart_compatibility(isolated_db):
    from api.pam import _verify_mfa, mfa_store
    import bcrypt
    import time
    
    # 1. Create two test users: static and dynamic
    conn = get_db_connection()
    hashed_static = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode('utf-8')
    
    conn.execute(
        "INSERT INTO users (id, username, password, role, status, mfa_enabled, mfa_secret, fixed_pin) VALUES (?, ?, ?, ?, ?, 0, '', ?)",
        ("user-static-id", "staticuser", "dummy", "Operator", "active", hashed_static)
    )
    
    secret = generate_totp_secret()
    conn.execute(
        "INSERT INTO users (id, username, password, role, status, mfa_enabled, mfa_secret, fixed_pin) VALUES (?, ?, ?, ?, ?, 1, ?, '')",
        ("user-dynamic-id", "dynamicuser", "dummy", "Operator", "active", secret)
    )
    conn.commit()
    conn.close()
    
    # 2. Verify Static User
    mfa_store["staticuser"] = {"code": "888888", "expire": time.time() + 60, "nonce": None}
    success, err = _verify_mfa("staticuser", "123456", "888888")
    assert success is True
    
    mfa_store["staticuser"] = {"code": "888888", "expire": time.time() + 60, "nonce": None}
    success, err = _verify_mfa("staticuser", "111111", "888888")
    assert success is False
    assert "固定密码验证失败" in err
    
    # 3. Verify Dynamic User
    mfa_store["dynamicuser"] = {"code": "888888", "expire": time.time() + 60, "nonce": None}
    correct_totp = generate_totp_code(secret)
    success, err = _verify_mfa("dynamicuser", correct_totp, "888888")
    assert success is True
    
    mfa_store["dynamicuser"] = {"code": "888888", "expire": time.time() + 60, "nonce": None}
    success, err = _verify_mfa("dynamicuser", "000000", "888888")
    assert success is False
    assert "动态身份验证码验证失败" in err

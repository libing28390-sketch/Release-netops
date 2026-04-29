#!/usr/bin/env python3
"""
license/generator.py — License 生成工具（独立脚本）
===================================================
⚠️  此脚本包含 RSA 私钥操作，仅限在安全的内部环境中运行。
    绝对不要将私钥部署到客户服务器上。

用法:
    # 1. 首次使用：生成密钥对
    python -m license.generator --init-keys

    # 2. 生成 License
    python -m license.generator \\
        --company "Acme Corp" \\
        --expire "2027-12-31T23:59:59" \\
        --devices 500 \\
        --features automation,config_management,monitoring,alerting,rbac \\
        --type enterprise \\
        --output license.json

    # 3. 验证已有 License
    python -m license.generator --verify license.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add backend to path for imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_BACKEND_DIR))

from license.crypto import (
    generate_key_pair,
    load_private_key_from_file,
    load_public_key_from_file,
    sign_payload,
    verify_signature,
)
from license.models import LicenseFile, LicensePayload, LicenseType

# Default key paths (relative to this script's directory)
_KEYS_DIR = _SCRIPT_DIR / "keys"
_PRIVATE_KEY_PATH = _KEYS_DIR / "private.pem"
_PUBLIC_KEY_PATH = _KEYS_DIR / "public.pem"


def init_keys(force: bool = False):
    """Generate RSA key pair and save to keys/ directory."""
    if _PRIVATE_KEY_PATH.exists() and not force:
        print(f"⚠️  Keys already exist at {_KEYS_DIR}")
        print("   Use --force to overwrite")
        return

    _KEYS_DIR.mkdir(parents=True, exist_ok=True)
    private_pem, public_pem = generate_key_pair(
        private_key_path=str(_PRIVATE_KEY_PATH),
        public_key_path=str(_PUBLIC_KEY_PATH),
    )
    print(f"✅ RSA-2048 key pair generated:")
    print(f"   Private key: {_PRIVATE_KEY_PATH}")
    print(f"   Public key:  {_PUBLIC_KEY_PATH}")
    print()
    print("⚠️  SECURITY NOTICE:")
    print("   • Keep the PRIVATE KEY secret — never deploy it to customer servers")
    print("   • Only the PUBLIC KEY should be shipped with the application")
    print("   • Back up the private key in a secure vault")


def generate_license(
    company: str,
    expire_at: str,
    device_limit: int = 50,
    server_limit: int = 50,
    features: list[str] | None = None,
    license_type: str = "standard",
    machine_id: str | None = None,
    metadata: dict | None = None,
    output_path: str = "license.json",
    private_key_path: str | None = None,
):
    """Generate a signed license file."""
    # Load private key
    pk_path = Path(private_key_path or _PRIVATE_KEY_PATH)
    if not pk_path.exists():
        print(f"❌ Private key not found: {pk_path}")
        print("   Run: python -m license.generator --init-keys")
        sys.exit(1)

    private_key_pem = load_private_key_from_file(str(pk_path))

    # Build payload
    payload = LicensePayload(
        license_id=str(uuid.uuid4()),
        company=company,
        license_type=LicenseType(license_type),
        issued_at=datetime.now(timezone.utc).isoformat(),
        expire_at=expire_at,
        device_limit=device_limit,
        server_limit=server_limit,
        features=features or [],
        machine_id=machine_id,
        metadata=metadata,
    )

    # Sign
    payload_dict = payload.model_dump(mode="json")
    signature = sign_payload(payload_dict, private_key_pem)

    # Build license file
    license_file = LicenseFile(payload=payload, signature=signature)

    # Write
    output = Path(output_path)
    output.write_text(
        json.dumps(license_file.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"✅ License generated successfully!")
    print(f"   File:     {output.resolve()}")
    print(f"   ID:       {payload.license_id}")
    print(f"   Company:  {payload.company}")
    print(f"   Type:     {payload.license_type.value}")
    print(f"   Issued:   {payload.issued_at}")
    print(f"   Expires:  {payload.expire_at}")
    print(f"   Devices:  {payload.device_limit}")
    print(f"   Servers:  {payload.server_limit}")
    print(f"   Features: {', '.join(payload.features) or '(none)'}")
    if payload.machine_id:
        print(f"   Machine:  {payload.machine_id}")


def verify_license(license_path: str, public_key_path: str | None = None):
    """Verify an existing license file."""
    pk_path = Path(public_key_path or _PUBLIC_KEY_PATH)
    if not pk_path.exists():
        print(f"❌ Public key not found: {pk_path}")
        sys.exit(1)

    lf = Path(license_path)
    if not lf.exists():
        print(f"❌ License file not found: {lf}")
        sys.exit(1)

    public_key_pem = load_public_key_from_file(str(pk_path))
    data = json.loads(lf.read_text(encoding="utf-8"))

    try:
        license_file = LicenseFile(**data)
    except Exception as e:
        print(f"❌ Invalid license format: {e}")
        sys.exit(1)

    payload_dict = license_file.payload.model_dump(mode="json")
    sig_valid = verify_signature(payload_dict, license_file.signature, public_key_pem)

    payload = license_file.payload
    print(f"\n{'═' * 50}")
    print(f"  License Verification Report")
    print(f"{'═' * 50}")
    print(f"  ID:        {payload.license_id}")
    print(f"  Company:   {payload.company}")
    print(f"  Type:      {payload.license_type.value}")
    print(f"  Issued:    {payload.issued_at}")
    print(f"  Expires:   {payload.expire_at}")
    print(f"  Devices:   {payload.device_limit}")
    print(f"  Features:  {', '.join(payload.features) or '(none)'}")
    if payload.machine_id:
        print(f"  Machine:   {payload.machine_id}")
    print(f"{'─' * 50}")
    print(f"  Signature: {'✅ VALID' if sig_valid else '❌ INVALID'}")

    # Check expiry
    try:
        expire_dt = datetime.fromisoformat(payload.expire_at)
        if expire_dt.tzinfo is None:
            expire_dt = expire_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        delta = expire_dt - now_dt
        if delta.days < 0:
            print(f"  Expiry:    ❌ EXPIRED ({abs(delta.days)} days ago)")
        elif delta.days <= 7:
            print(f"  Expiry:    ⚠️  EXPIRING SOON ({delta.days} days remaining)")
        else:
            print(f"  Expiry:    ✅ OK ({delta.days} days remaining)")
    except Exception:
        print(f"  Expiry:    ⚠️  Could not parse date")

    print(f"{'═' * 50}\n")

    if not sig_valid:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Nexora License Generator & Verifier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate keys
  python -m license.generator --init-keys

  # Generate a license
  python -m license.generator \\
      --company "Acme Corp" \\
      --expire "2027-12-31T23:59:59" \\
      --devices 500 \\
      --servers 100 \\
      --features automation,monitoring,alerting,rbac \\
      --type enterprise \\
      --output data/license.json

  # Verify a license
  python -m license.generator --verify data/license.json
        """,
    )
    parser.add_argument("--init-keys", action="store_true", help="Generate RSA key pair")
    parser.add_argument("--force", action="store_true", help="Overwrite existing keys")
    parser.add_argument("--verify", type=str, metavar="FILE", help="Verify an existing license file")

    # Generation arguments
    gen = parser.add_argument_group("License Generation")
    gen.add_argument("--company", type=str, help="Company name")
    gen.add_argument("--expire", type=str, help="Expiry date (ISO-8601, e.g. 2027-12-31T23:59:59)")
    gen.add_argument("--devices", type=int, default=50, help="Network device limit (default: 50)")
    gen.add_argument("--servers", type=int, default=50, help="Server limit (default: 50)")
    gen.add_argument("--features", type=str, default="", help="Comma-separated feature list")
    gen.add_argument("--type", type=str, default="standard",
                     choices=["trial", "standard", "professional", "enterprise"],
                     help="License type (default: standard)")
    gen.add_argument("--machine-id", type=str, default=None, help="Machine fingerprint for binding")
    gen.add_argument("--output", type=str, default="license.json", help="Output file path")
    gen.add_argument("--private-key", type=str, default=None, help="Path to RSA private key")
    gen.add_argument("--public-key", type=str, default=None, help="Path to RSA public key (for verify)")

    args = parser.parse_args()

    if args.init_keys:
        init_keys(force=args.force)
    elif args.verify:
        verify_license(args.verify, public_key_path=args.public_key)
    elif args.company and args.expire:
        features = [f.strip() for f in args.features.split(",") if f.strip()] if args.features else []
        generate_license(
            company=args.company,
            expire_at=args.expire,
            device_limit=args.devices,
            server_limit=args.servers,
            features=features,
            license_type=args.type,
            machine_id=args.machine_id,
            output_path=args.output,
            private_key_path=args.private_key,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

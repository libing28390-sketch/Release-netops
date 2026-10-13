import datetime
import os
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

def generate_self_signed_cert(cert_path, key_path):
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Write private key
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        
    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Beijing"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Beijing"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NetOps Automation"),
        x509.NameAttribute(NameOID.COMMON_NAME, "netops.local"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        # 10 years validity
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.DNSName("netops.local")]),
        critical=False,
    ).sign(private_key, hashes.SHA256())
    
    # Write certificate
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    nginx_dir = os.path.join(os.path.dirname(script_dir), "nginx", "ssl")
    cert_path = os.path.join(nginx_dir, "netops.crt")
    key_path = os.path.join(nginx_dir, "netops.key")
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print(f"Generating self-signed certificate...")
        generate_self_signed_cert(cert_path, key_path)
        print(f"Certificate generated at {cert_path}")
        print(f"Private key generated at {key_path}")
    else:
        print("Certificate and key already exist, skipping generation.")

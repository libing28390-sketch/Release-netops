#!/bin/sh
set -eu

cert_file=/etc/nginx/ssl/netops.crt
key_file=/etc/nginx/ssl/netops.key

if [ -s "$cert_file" ] && [ -s "$key_file" ]; then
    echo "05-ensure-tls-certificate.sh: using existing TLS certificate"
    exit 0
fi

mkdir -p /etc/nginx/ssl
rm -f "$cert_file" "$key_file"

common_name=${TLS_COMMON_NAME:-localhost}
case "$common_name" in
    *:*) subject_alt_name="IP:$common_name" ;;
    *[!0-9.]*) subject_alt_name="DNS:$common_name" ;;
    *) subject_alt_name="IP:$common_name" ;;
esac

echo "05-ensure-tls-certificate.sh: TLS certificate missing; generating a self-signed certificate for $common_name"
umask 077
openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 3650 \
    -keyout "$key_file" \
    -out "$cert_file" \
    -subj "/CN=$common_name" \
    -addext "subjectAltName=$subject_alt_name"
chmod 600 "$key_file"
chmod 644 "$cert_file"

echo "05-ensure-tls-certificate.sh: generated $cert_file (replace it with a trusted certificate for production)"

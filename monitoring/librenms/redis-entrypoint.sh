#!/bin/sh
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 64
}

redis_password=${REDIS_PASSWORD:-}
[ "${#redis_password}" -ge 32 ] || fail 'LibreNMS Redis password must contain at least 32 characters.'

case "$redis_password" in
  *replace-with*|*placeholder*|*changeme*|*CHANGE_ME*)
    fail 'LibreNMS example placeholder values cannot be used at runtime.'
    ;;
esac

umask 077
password_hash=$(printf '%s' "$redis_password" | sha256sum | awk '{print $1}')
printf 'user default on #%s ~* &* +@all\n' "$password_hash" > /data/librenms-users.acl

exec /usr/local/bin/docker-entrypoint.sh redis-server \
  --appendonly yes \
  --appendfsync everysec \
  --aclfile /data/librenms-users.acl

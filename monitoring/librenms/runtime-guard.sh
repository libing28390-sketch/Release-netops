#!/bin/sh
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 64
}

app_key=${APP_KEY:-}
db_password=${DB_PASSWORD:-}
redis_password=${REDIS_PASSWORD:-}

case "$app_key" in
  base64:*) app_key_payload=${app_key#base64:} ;;
  *) fail 'LibreNMS APP_KEY must be generated before enabling the native profile.' ;;
esac

[ -n "$db_password" ] || fail 'LibreNMS database password is required.'
[ -n "$redis_password" ] || fail 'LibreNMS Redis password is required.'
[ "${#db_password}" -ge 32 ] || fail 'LibreNMS database password must contain at least 32 characters.'
[ "${#redis_password}" -ge 32 ] || fail 'LibreNMS Redis password must contain at least 32 characters.'
[ "$db_password" != "$redis_password" ] || fail 'LibreNMS database and Redis passwords must be different.'

case "$db_password:$redis_password" in
  *replace-with*|*placeholder*|*changeme*|*CHANGE_ME*)
    fail 'LibreNMS example placeholder values cannot be used at runtime.'
    ;;
esac

printf '%s' "$app_key_payload" | base64 -d >/dev/null 2>&1 || fail 'LibreNMS APP_KEY is not valid base64.'
decoded_key_length=$(printf '%s' "$app_key_payload" | base64 -d 2>/dev/null | wc -c | tr -d '[:space:]')
[ "$decoded_key_length" = '32' ] || fail 'LibreNMS APP_KEY must encode exactly 32 random bytes.'

exec /init "$@"

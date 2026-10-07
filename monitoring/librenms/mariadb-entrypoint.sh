#!/bin/sh
set -eu

fail() {
  printf '%s\n' "$1" >&2
  exit 64
}

root_password=${MARIADB_ROOT_PASSWORD:-}
db_password=${MARIADB_PASSWORD:-}

[ "${#root_password}" -ge 32 ] || fail 'LibreNMS MariaDB root password must contain at least 32 characters.'
[ "${#db_password}" -ge 32 ] || fail 'LibreNMS MariaDB application password must contain at least 32 characters.'
[ "$root_password" != "$db_password" ] || fail 'LibreNMS MariaDB root and application passwords must be different.'

case "$root_password:$db_password" in
  *replace-with*|*placeholder*|*changeme*|*CHANGE_ME*)
    fail 'LibreNMS example placeholder values cannot be used at runtime.'
    ;;
esac

exec /usr/local/bin/docker-entrypoint.sh "$@"

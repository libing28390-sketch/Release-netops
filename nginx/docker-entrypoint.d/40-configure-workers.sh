#!/bin/sh
set -eu

# The official image runs hooks in filename order. Configure the main file
# after 30-tune-worker-processes.sh, keeping its result explicitly controlled.
configure_nginx_workers() {
    config_path="$1"
    workers="${NGINX_WORKER_PROCESSES:-1}"
    case "$workers" in
        *[!0-9]* | '')
            echo "NGINX_WORKER_PROCESSES must be an integer from 1 to 8" >&2
            return 1
            ;;
    esac
    if [ "${#workers}" -gt 1 ] || [ "$workers" -lt 1 ] || [ "$workers" -gt 8 ]; then
        echo "NGINX_WORKER_PROCESSES must be an integer from 1 to 8" >&2
        return 1
    fi
    directive_count="$(grep -Ec '^[[:space:]]*worker_processes[[:space:]]+[^;]+;' "$config_path" || true)"
    if [ "$directive_count" != 1 ]; then
        echo "Expected one worker_processes directive in the Nginx main config" >&2
        return 1
    fi
    sed -i "s/^\([[:space:]]*worker_processes[[:space:]][[:space:]]*\)[^;]*;/\1${workers};/" "$config_path"
    grep -Eq "^[[:space:]]*worker_processes[[:space:]]+${workers};" "$config_path"
}

configure_nginx_workers /etc/nginx/nginx.conf

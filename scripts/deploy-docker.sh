#!/usr/bin/env bash
set -Eeuo pipefail

# Docker deployment helper for the sanitized public release repository.
# It never pushes to Git and never runs a host-wide Docker prune.

readonly RELEASE_REPO="${NETOPS_RELEASE_REPO:-https://github.com/libing28390-sketch/Release-netops.git}"
readonly RELEASE_BRANCH="${NETOPS_RELEASE_BRANCH:-main}"

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

log() {
    echo "[NetOps] $*"
}

usage() {
    cat <<'EOF'
Usage:
  bash scripts/deploy-docker.sh install [deployment-directory]
  bash scripts/deploy-docker.sh update [deployment-directory] [--force]
  bash scripts/deploy-docker.sh save-images [archive-path]
  bash scripts/deploy-docker.sh load-images <archive-path>
  bash scripts/deploy-docker.sh backup-release [deployment-directory]
  bash scripts/deploy-docker.sh start-offline
  bash scripts/deploy-docker.sh reset-data [deployment-directory] [--yes]

Commands:
  install    Clone/sync the public release, initialize .env, build, and start.
  update     Preserve .env, Docker volumes, and nginx/ssl; sync the public
             release history, show source changes, and rebuild only when the
             release content changed. Use --force to rebuild unconditionally.
  save-images Save the three already-built Compose images to a gzip-compressed
             archive and write a SHA-256 checksum alongside it. This command
             does not build images or access a registry.
  load-images Load a previously saved image archive and verify all required
             Compose image tags are available locally.
  backup-release Create a PostgreSQL custom dump, redacted Source Manifest,
             and private configuration/config-snapshot archives before release.
  start-offline Start the stack using only local images, without building or
                 pulling any image.
  reset-data Stop the stack and delete this Compose project's volumes, local
             build images, and generated TLS files. It does not affect other
             Docker projects. Use --yes or NETOPS_CONFIRM=YES for automation.

Environment:
  NETOPS_RELEASE_REPO    Override the public release URL.
  NETOPS_RELEASE_BRANCH  Override the release branch (default: main).
  NETOPS_DIR              Default deployment directory (default: current dir).
  RELEASE_BACKUP_DIR      Backup destination (default: ../netops-release-backups).
  NETOPS_BUILD_PULL       Set to 1 to always pull newer base images while
                          building. By default local base images are reused and
                          the registry is only contacted for missing images.
EOF
}

RELEASE_CHANGED=0

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_docker() {
    require_command docker
    docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
}

set_env_value() {
    local key="$1" value="$2"
    if grep -qE "^${key}=" .env; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

env_value() {
    local key="$1" value
    value="$(grep -E "^${key}=" .env | tail -n 1 | cut -d= -f2- || true)"
    # .env may have been edited on Windows and contain CRLF line endings.
    # Keep dotenv values as data, but do not pass the trailing CR to Docker or
    # PostgreSQL as part of the username/database name.
    value="${value%$'\r'}"
    printf '%s' "$value"
}

is_placeholder() {
    case "$1" in
        ""|postgres|localhost|127.0.0.1|replace-*|change-me*|__CHANGE_ME__*) return 0 ;;
        *) return 1 ;;
    esac
}

initialize_env() {
    if [[ ! -f .env ]]; then
        [[ -f .env.example ]] || die ".env.example is missing"
        cp .env.example .env
        log "Created .env from .env.example"
    fi

    require_command openssl
    local db_user db_name db_password server_name
    db_user="$(env_value POSTGRES_USER)"
    db_name="$(env_value POSTGRES_DB)"
    db_user="${db_user:-postgres}"
    db_name="${db_name:-netops}"

    if is_placeholder "$(env_value POSTGRES_PASSWORD)"; then
        set_env_value POSTGRES_PASSWORD "$(openssl rand -hex 16)"
    fi
    if is_placeholder "$(env_value SECRET_KEY)"; then
        set_env_value SECRET_KEY "$(openssl rand -hex 32)"
    fi
    if is_placeholder "$(env_value CREDENTIAL_ENCRYPTION_KEY)"; then
        set_env_value CREDENTIAL_ENCRYPTION_KEY "$(openssl rand -hex 32)"
    fi

    db_password="$(env_value POSTGRES_PASSWORD)"
    if [[ -z "$(env_value DATABASE_URL)" || "$(env_value DATABASE_URL)" == *127.0.0.1* || "$(env_value DATABASE_URL)" == *localhost* ]]; then
        set_env_value DATABASE_URL "postgresql://${db_user}:${db_password}@db:5432/${db_name}"
    fi

    server_name="$(env_value TLS_COMMON_NAME)"
    if is_placeholder "$server_name"; then
        server_name="$(hostname -I 2>/dev/null | awk '{print $1}')"
        server_name="${server_name:-localhost}"
        set_env_value TLS_COMMON_NAME "$server_name"
    fi
    chmod 600 .env
}

set_release_remote() {
    local current
    if git remote get-url origin >/dev/null 2>&1; then
        current="$(git remote get-url origin)"
        if [[ "$current" != "$RELEASE_REPO" ]]; then
            log "Switching origin from $current to $RELEASE_REPO"
            git remote set-url origin "$RELEASE_REPO"
        fi
    else
        git remote add origin "$RELEASE_REPO"
    fi
}

sync_release() {
    set_release_remote
    local current_commit remote_commit current_tree remote_tree
    current_commit="$(git rev-parse HEAD)"
    git fetch --prune origin "$RELEASE_BRANCH"
    remote_commit="$(git rev-parse "origin/${RELEASE_BRANCH}")"
    current_tree="$(git rev-parse "${current_commit}^{tree}")"
    remote_tree="$(git rev-parse "${remote_commit}^{tree}")"

    if [[ "$current_tree" == "$remote_tree" ]]; then
        RELEASE_CHANGED=0
        if [[ "$current_commit" != "$remote_commit" ]]; then
            log "Release commit changed but source content is unchanged"
            log "  ${current_commit:0:7} -> ${remote_commit:0:7}"
            git reset --hard "$remote_commit" >/dev/null
        else
            log "Release is already up to date at ${remote_commit:0:7}"
        fi
        return 0
    fi

    RELEASE_CHANGED=1
    log "Release source changed: ${current_commit:0:7} -> ${remote_commit:0:7}"
    git --no-pager diff --stat "$current_commit" "$remote_commit" || true
    git --no-pager diff --name-status "$current_commit" "$remote_commit" | sed -n '1,80p' || true
    git reset --hard "$remote_commit"
}

prepare_source() {
    local deployment_dir="$1"
    if [[ ! -d "$deployment_dir/.git" ]]; then
        if [[ -e "$deployment_dir" ]] && find "$deployment_dir" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
            die "$deployment_dir exists and is not an empty Git deployment directory"
        fi
        mkdir -p "$(dirname "$deployment_dir")"
        log "Cloning $RELEASE_REPO into $deployment_dir"
        git clone --branch "$RELEASE_BRANCH" "$RELEASE_REPO" "$deployment_dir"
    fi
    cd "$deployment_dir"
    [[ -f docker-compose.yml ]] || die "docker-compose.yml is missing in $deployment_dir"
    sync_release
}

backup_env() {
    if [[ -f .env ]]; then
        local backup=".env.backup.$(date +%Y%m%d%H%M%S)"
        cp -a .env "$backup"
        log "Saved environment backup to $backup"
    fi
}

backup_release_state() {
    local backup_root="${RELEASE_BACKUP_DIR:-../netops-release-backups}"
    local stamp="$(date +%Y%m%d-%H%M%S)"
    local backup_dir="${backup_root%/}/release-${stamp}"
    local dump_path="${backup_dir}/database.dump"
    local dump_partial="${dump_path}.partial"
    local manifest_path="${backup_dir}/source-manifest.json"
    local manifest_partial="${manifest_path}.partial"
    local config_path="${backup_dir}/deployment-config.tar.gz"
    local config_partial="${config_path}.partial"
    local snapshot_path="${backup_dir}/config-snapshots.tar.gz"
    local snapshot_partial="${snapshot_path}.partial"

    [[ -f .env ]] || die "Cannot create release backup: .env is missing"
    # Read only the database identifiers needed by pg_dump.  Do not source the
    # whole dotenv file: cron expressions and other values may contain spaces
    # or shell metacharacters and must remain data, not executable shell code.
    local postgres_user postgres_db
    postgres_user="$(env_value POSTGRES_USER)"
    postgres_db="$(env_value POSTGRES_DB)"
    mkdir -p "$backup_dir"
    chmod 700 "$backup_dir"

    # The database service supplies its own local credentials; the password is
    # never interpolated into the command line or written to a log.
    if docker compose exec -T db pg_dump \
        --format=custom --no-owner \
        --username="${postgres_user:-postgres}" \
        --dbname="${postgres_db:-netops}" > "$dump_partial"; then
        [[ -s "$dump_partial" ]] || die "Release backup failed: empty PostgreSQL dump"
        mv -f "$dump_partial" "$dump_path"
    else
        rm -f "$dump_partial"
        die "Release backup failed: PostgreSQL pg_dump did not complete"
    fi

    # Export the manifest through the running application so it uses the same
    # PostgreSQL connection and metadata authority as production.
    if docker compose exec -T netops sh -c \
        'set -eu; rm -f /tmp/nexora-source-manifest.json; PYTHONPATH=/app/backend python -m database.backup manifest --output /tmp/nexora-source-manifest.json >/dev/null; cat /tmp/nexora-source-manifest.json' \
        > "$manifest_partial"; then
        [[ -s "$manifest_partial" ]] || die "Release backup failed: empty Source Manifest"
        mv -f "$manifest_partial" "$manifest_path"
    else
        rm -f "$manifest_partial"
        die "Release backup failed: Source Manifest export did not complete"
    fi

    # Keep runtime configuration private. This archive may contain the
    # encrypted .env and TLS material and is therefore never committed.
    local config_entries=(.env)
    [[ -f .env.example ]] && config_entries+=(.env.example)
    [[ -d nginx/ssl ]] && config_entries+=(nginx/ssl)
    [[ -f desktop/desktop_settings.ini ]] && config_entries+=(desktop/desktop_settings.ini)
    if tar -czf "$config_partial" -C . "${config_entries[@]}"; then
        [[ -s "$config_partial" ]] || die "Release backup failed: empty deployment configuration archive"
        chmod 600 "$config_partial"
        mv -f "$config_partial" "$config_path"
    else
        rm -f "$config_partial"
        die "Release backup failed: deployment configuration archive did not complete"
    fi

    # The Docker backup volume contains device configuration snapshots. Keep a
    # separate private archive so a database restore is never mistaken for a
    # device-config restore.
    if docker compose exec -T netops tar -czf - -C /app/backup . > "$snapshot_partial"; then
        [[ -s "$snapshot_partial" ]] || die "Release backup failed: empty configuration snapshot archive"
        chmod 600 "$snapshot_partial"
        mv -f "$snapshot_partial" "$snapshot_path"
    else
        rm -f "$snapshot_partial"
        die "Release backup failed: configuration snapshot archive did not complete"
    fi

    chmod 600 "$dump_path" "$manifest_path"
    log "Release backup complete: $backup_dir"
    log "  PostgreSQL dump, Source Manifest, deployment config, and config snapshots are present"
}

validate_compose() {
    docker compose config --quiet || die "Docker Compose configuration is invalid"
}

build_and_start() {
    validate_compose
    local build_args=(db netops nginx)
    # Local images win: without --pull, BuildKit uses locally available FROM
    # images and only contacts the registry when one is missing. Hosts with
    # reliable registry access can set NETOPS_BUILD_PULL=1 to force refreshing
    # base images.
    [[ "${NETOPS_BUILD_PULL:-0}" == "1" ]] && build_args=(--pull "${build_args[@]}")
    # Build the database image first so pgvector and pg_trgm are present before
    # the application container starts its migrations.
    docker compose build "${build_args[@]}"
    docker compose up -d --force-recreate --remove-orphans
    docker compose ps
}

required_images() {
    printf '%s\n' \
        "nexora-netops:latest" \
        "nexora-nginx:latest" \
        "nexora-postgres:latest"
}

verify_required_images() {
    local image
    while IFS= read -r image; do
        docker image inspect "$image" >/dev/null 2>&1 || die "Required image is missing locally: $image"
    done < <(required_images)
}

save_images() {
    local archive_path="${1:-nexora-images-$(date +%Y%m%d-%H%M%S).tar.gz}"
    local partial_path="${archive_path}.partial"
    require_command gzip
    require_command sha256sum
    verify_required_images
    mkdir -p "$(dirname "$archive_path")"
    rm -f "$partial_path"
    log "Saving Compose images to $archive_path"
    required_images | xargs docker save | gzip -c > "$partial_path"
    mv "$partial_path" "$archive_path"
    (cd "$(dirname "$archive_path")" && sha256sum "$(basename "$archive_path")") > "${archive_path}.sha256"
    log "Image archive and checksum created"
    ls -lh "$archive_path" "${archive_path}.sha256"
}

load_images() {
    local archive_path="${1:-}"
    [[ -n "$archive_path" ]] || die "Usage: bash scripts/deploy-docker.sh load-images <archive-path>"
    [[ -f "$archive_path" ]] || die "Image archive not found: $archive_path"
    require_command gzip
    if [[ -f "${archive_path}.sha256" ]]; then
        (cd "$(dirname "$archive_path")" && sha256sum -c "$(basename "$archive_path").sha256") || die "Image archive checksum verification failed"
    fi
    if [[ "$archive_path" == *.gz ]]; then
        gzip -dc "$archive_path" | docker load
    else
        docker load --input "$archive_path"
    fi
    verify_required_images
    log "All required images are available locally"
}

start_offline() {
    validate_compose
    verify_required_images
    docker compose up -d --no-build --pull never --remove-orphans
    docker compose ps
}

reset_data() {
    local deployment_dir="$1" confirmed="${NETOPS_CONFIRM:-}"
    cd "$deployment_dir"
    [[ -f docker-compose.yml ]] || die "docker-compose.yml is missing in $deployment_dir"
    if [[ "${2:-}" != "--yes" && "$confirmed" != "YES" ]]; then
        read -r -p "Delete NetOps containers, volumes, local images, and TLS files? [y/N] " answer
        [[ "$answer" == "y" || "$answer" == "Y" ]] || { log "Cancelled"; exit 0; }
    fi
    docker compose down -v --remove-orphans --rmi local
    # Explicit image tags are not always covered by --rmi local.
    docker image rm -f nexora-netops nexora-nginx nexora-postgres >/dev/null 2>&1 || true
    rm -f nginx/ssl/netops.crt nginx/ssl/netops.key
    log "NetOps Docker data reset complete"
}

COMMAND="${1:-help}"
shift || true
DEPLOYMENT_DIR="${NETOPS_DIR:-$PWD}"
YES_FLAG=""
FORCE_UPDATE=""
ARCHIVE_PATH=""
if [[ "$COMMAND" == "save-images" || "$COMMAND" == "load-images" ]]; then
    ARCHIVE_PATH="${1:-}"
    shift || true
fi
for argument in "$@"; do
    case "$argument" in
        --yes) YES_FLAG="--yes" ;;
        --force) FORCE_UPDATE="--force" ;;
        -h|--help) usage; exit 0 ;;
        -*) die "Unknown option: $argument" ;;
        *) DEPLOYMENT_DIR="$argument" ;;
    esac
done

case "$COMMAND" in
    -h|--help|help) usage ;;
    install)
        require_docker
        require_command git
        prepare_source "$DEPLOYMENT_DIR"
        initialize_env
        mkdir -p nginx/ssl
        build_and_start
        log "Initial Docker installation complete"
        ;;
    update)
        require_docker
        require_command git
        [[ -d "$DEPLOYMENT_DIR/.git" ]] || die "Not a Git deployment: $DEPLOYMENT_DIR"
        cd "$DEPLOYMENT_DIR"
        backup_release_state
        backup_env
        sync_release
        initialize_env
        if [[ "${FORCE_UPDATE:-}" != "--force" && "$RELEASE_CHANGED" != "1" ]]; then
            docker compose ps
            log "No release content changes; skipped image pull, build, and container recreation"
            log "Docker update check complete; .env, volumes, and nginx/ssl were preserved"
        else
            [[ "${FORCE_UPDATE:-}" == "--force" ]] && log "Force update requested; rebuilding the Docker stack"
            build_and_start
            log "Docker update complete; .env, volumes, and nginx/ssl were preserved"
        fi
        ;;
    save-images)
        require_docker
        save_images "$ARCHIVE_PATH"
        ;;
    load-images)
        require_docker
        load_images "$ARCHIVE_PATH"
        ;;
    backup-release)
        require_docker
        [[ -d "$DEPLOYMENT_DIR/.git" ]] || die "Not a Git deployment: $DEPLOYMENT_DIR"
        cd "$DEPLOYMENT_DIR"
        backup_release_state
        ;;
    start-offline)
        require_docker
        start_offline
        ;;
    reset-data)
        require_docker
        reset_data "$DEPLOYMENT_DIR" "$YES_FLAG"
        ;;
    *)
        usage
        die "Unknown command: $COMMAND"
        ;;
esac

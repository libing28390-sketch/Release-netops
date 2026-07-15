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
  bash scripts/deploy-docker.sh reset-data [deployment-directory] [--yes]

Commands:
  install    Clone/sync the public release, initialize .env, build, and start.
  update     Preserve .env, Docker volumes, and nginx/ssl; sync the public
             release history, show source changes, and rebuild only when the
             release content changed. Use --force to rebuild unconditionally.
  reset-data Stop the stack and delete this Compose project's volumes, local
             build images, and generated TLS files. It does not affect other
             Docker projects. Use --yes or NETOPS_CONFIRM=YES for automation.

Environment:
  NETOPS_RELEASE_REPO    Override the public release URL.
  NETOPS_RELEASE_BRANCH  Override the release branch (default: main).
  NETOPS_DIR              Default deployment directory (default: current dir).
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
    local key="$1"
    grep -E "^${key}=" .env | tail -n 1 | cut -d= -f2- || true
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

validate_compose() {
    docker compose config --quiet || die "Docker Compose configuration is invalid"
}

build_and_start() {
    validate_compose
    docker compose pull db
    docker compose build --pull netops nginx
    docker compose up -d --force-recreate --remove-orphans
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
    docker image rm -f nexora-netops nexora-nginx >/dev/null 2>&1 || true
    rm -f nginx/ssl/netops.crt nginx/ssl/netops.key
    log "NetOps Docker data reset complete"
}

COMMAND="${1:-help}"
shift || true
DEPLOYMENT_DIR="${NETOPS_DIR:-$PWD}"
YES_FLAG=""
FORCE_UPDATE=""
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
    reset-data)
        require_docker
        reset_data "$DEPLOYMENT_DIR" "$YES_FLAG"
        ;;
    *)
        usage
        die "Unknown command: $COMMAND"
        ;;
esac

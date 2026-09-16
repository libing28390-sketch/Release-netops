#!/usr/bin/env bash
# ============================================================
#  NetOps Automation — Ubuntu 一键部署脚本
#  用法:  chmod +x deploy-ubuntu.sh && ./deploy-ubuntu.sh
#  支持:  Ubuntu 20.04 / 22.04 / 24.04 (x86_64 / arm64)
#         GitHub Codespaces / Docker 容器环境
# ============================================================

set -euo pipefail

# ── 全局错误捕获：任何命令失败时打印出错位置 ──
_on_error() {
    local exit_code=$?
    local line_no=$1
    echo ""
    echo -e "\033[0;31m[FAIL]\033[0m  脚本在第 ${line_no} 行意外退出 (exit code: ${exit_code})"
    echo -e "\033[0;31m[FAIL]\033[0m  请检查上方输出，或使用 'bash -x deploy-ubuntu.sh' 开启调试模式"
    exit $exit_code
}
trap '_on_error $LINENO' ERR

# ── 检测是否通过管道运行（curl | bash），重定向 stdin ──
if [ ! -t 0 ]; then
    # stdin 不是终端（管道模式），重定向到 /dev/tty 保证交互命令正常
    exec < /dev/tty 2>/dev/null || true
fi

# ---------- 颜色输出 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ---------- 配置 ----------
NODE_MAJOR=22
PYTHON_MIN="3.10"
# One-click deployments use the sanitized public release repository by
# default. Developers can still override this with GIT_REPO.
GIT_REPO="${GIT_REPO:-https://github.com/libing28390-sketch/Release-netops.git}"
PROJECT_NAME="nexora-automation"
SERVICE_NAME="netops"
BACKEND_PORT=8003
NGINX_PORT=80
SERVER_NAME="_"

# ---------- 检查是否以 root 运行 ----------
if [ "$EUID" -eq 0 ]; then
    warn "当前以 root 身份运行，服务将以 root 用户启动"
    warn "生产环境建议使用普通用户执行此脚本"
    RUN_USER="root"
else
    RUN_USER="$USER"
fi

echo ""
echo "========================================"
echo "  NetOps Automation 一键部署"
echo "========================================"
echo ""

# ============================================================
# 0. 修正可能的 Windows 行尾符（CRLF → LF）
# ============================================================
if file "$0" | grep -q CRLF 2>/dev/null; then
    info "检测到 CRLF 行尾，自动转换..."
    sed -i 's/\r$//' "$0"
    exec bash "$0" "$@"
fi

# ============================================================
# 0.1 检测运行环境（systemd 还是容器）
# ============================================================
HAS_SYSTEMD=0
IS_CONTAINER=0

# ── OS 兼容性检查 ──
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_VERSION="${VERSION_ID:-0}"
    OS_MAJOR=$(echo "$OS_VERSION" | cut -d. -f1)

    case "$OS_ID" in
        ubuntu|debian)
            ok "操作系统: $PRETTY_NAME"
            ;;
        rhel|rocky|almalinux|centos)
            if [ "$OS_MAJOR" -ge 8 ] 2>/dev/null; then
                ok "操作系统: $PRETTY_NAME"
                warn "注意: 此脚本针对 Ubuntu/Debian 优化，在 RHEL 系发行版上部分步骤（apt-get/Nginx 路径）可能需要手动调整。"
                warn "建议使用 Docker 部署方式以获得最佳兼容性。"
            else
                fail "不支持的操作系统: $PRETTY_NAME
  CentOS 7 / RHEL 7 的 glibc 版本 (2.17) 过低，无法加载平台核心模块。
  请迁移到 Rocky Linux 8+ 或 AlmaLinux 8+，或使用 Docker 部署。"
            fi
            ;;
        *)
            warn "未识别的操作系统: ${PRETTY_NAME:-$OS_ID}，继续尝试部署..."
            ;;
    esac
else
    warn "无法读取 /etc/os-release，跳过 OS 兼容性检查"
fi

if [ -f /run/systemd/private ] || systemctl --version > /dev/null 2>&1; then
    HAS_SYSTEMD=1
fi

if [ -f /.dockerenv ] || grep -q 'docker\|lxc\|codespaces' /proc/1/cgroup 2>/dev/null; then
    IS_CONTAINER=1
fi

# 容器内 systemd 通常不可用
if [ "$IS_CONTAINER" = "1" ]; then
    HAS_SYSTEMD=0
    warn "检测到容器环境（Docker / Codespaces），将使用 service 命令管理服务"
else
    info "检测到标准 Ubuntu 环境，将使用 systemd 管理服务"
fi

# 统一服务管理函数
svc_start()  {
    local name="$1"
    if [ "$HAS_SYSTEMD" = "1" ]; then
        sudo systemctl start "$name"
    else
        sudo service "$name" start || true
    fi
}
svc_stop() {
    local name="$1"
    if [ "$HAS_SYSTEMD" = "1" ]; then
        sudo systemctl stop "$name" 2>/dev/null || true
    else
        sudo service "$name" stop 2>/dev/null || true
    fi
}
svc_enable() {
    local name="$1"
    if [ "$HAS_SYSTEMD" = "1" ]; then
        sudo systemctl enable "$name" > /dev/null 2>&1 || true
    fi
    # 容器环境无需 enable（无开机自启概念）
}
svc_reload() {
    local name="$1"
    if [ "$HAS_SYSTEMD" = "1" ]; then
        sudo systemctl reload "$name"
    else
        sudo service "$name" reload || sudo service "$name" restart
    fi
}
svc_restart() {
    local name="$1"
    if [ "$HAS_SYSTEMD" = "1" ]; then
        sudo systemctl restart "$name"
    else
        sudo service "$name" restart || true
    fi
}
svc_is_active() {
    local name="$1"
    if [ "$HAS_SYSTEMD" = "1" ]; then
        sudo systemctl is-active --quiet "$name"
    else
        sudo service "$name" status > /dev/null 2>&1
    fi
}

# ============================================================
# 1. 系统依赖
# ============================================================

# 检查系统时间是否偏差过大（时间错误会导致 apt 源证书验证失败）
SYSTEM_EPOCH=$(date +%s)
# 用 curl 拿一个可靠的时间戳（HTTP Date 头）
REMOTE_DATE=$(curl -sI --max-time 5 https://www.baidu.com 2>/dev/null | grep -i '^date:' | head -1 | cut -d' ' -f2-)
if [ -n "$REMOTE_DATE" ]; then
    REMOTE_EPOCH=$(date -d "$REMOTE_DATE" +%s 2>/dev/null || echo 0)
    TIME_DIFF=$(( SYSTEM_EPOCH - REMOTE_EPOCH ))
    TIME_DIFF=${TIME_DIFF#-}  # 取绝对值
    if [ "$TIME_DIFF" -gt 86400 ] 2>/dev/null; then
        warn "系统时间偏差超过 24 小时（偏差 ${TIME_DIFF}s），apt 源证书验证可能失败"
        info "尝试自动同步时间..."
        sudo timedatectl set-ntp true 2>/dev/null || true
        sudo systemctl restart systemd-timesyncd 2>/dev/null || \
            sudo service systemd-timesyncd restart 2>/dev/null || true
        sleep 3
        # 如果 ntp 同步太慢，直接用 HTTP 时间强制设置
        if [ -n "$REMOTE_DATE" ] && [ "$TIME_DIFF" -gt 86400 ]; then
            sudo timedatectl set-time "$REMOTE_DATE" 2>/dev/null || \
                sudo date -s "$REMOTE_DATE" 2>/dev/null || true
            ok "系统时间已强制同步: $(date)"
        fi
    fi
fi

info "安装系统依赖..."
sudo apt-get update -qq --allow-releaseinfo-change 2>/dev/null || \
    sudo apt-get update -qq -o Acquire::Check-Valid-Until=false 2>/dev/null || \
    warn "apt update 遇到警告，尝试继续安装..."
sudo apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential libffi-dev libssl-dev \
    pkg-config libcairo2-dev libgirepository1.0-dev \
    nginx libcap2-bin \
    curl git ca-certificates > /dev/null 2>&1
ok "系统依赖安装完成（含 Nginx、Git）"

# ============================================================
# 1.1 项目目录检测 / 代码准备
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/backend/main.py" ]; then
    PROJECT_DIR="$SCRIPT_DIR"
    ok "检测到项目目录: $PROJECT_DIR"
else
    INSTALL_BASE="${INSTALL_DIR:-/opt}"
    PROJECT_DIR="$INSTALL_BASE/$PROJECT_NAME"
    if [ -d "$PROJECT_DIR/.git" ]; then
        info "项目目录已存在，拉取最新代码..."
        cd "$PROJECT_DIR"
        # 远端可能做过 force push（历史重写），--ff-only 会失败
        # 直接 reset 到远端最新状态，确保与发布版本完全一致
        git fetch origin main 2>&1 || warn "git fetch 失败，使用当前版本继续"
        git reset --hard origin/main 2>&1 && ok "代码已同步到最新版本: $PROJECT_DIR" || warn "git reset 失败，使用当前版本继续"
    else
        info "从 Git 克隆项目..."
        sudo mkdir -p "$INSTALL_BASE"
        sudo chown "$RUN_USER:$(id -gn $RUN_USER)" "$INSTALL_BASE" 2>/dev/null || true
        git clone "$GIT_REPO" "$PROJECT_DIR"
        ok "项目克隆完成: $PROJECT_DIR"
    fi
fi

info "目标目录: $PROJECT_DIR"

# The Docker build requires the local Terminal Agent source. Fail early with
# an actionable message instead of reporting a cryptic Docker COPY checksum
# error when an old/incomplete checkout is used.
if [ ! -f "$PROJECT_DIR/scripts/terminal_agent.py" ]; then
    fail "当前代码不是完整的 Nexora 主仓库（缺少 scripts/terminal_agent.py）。请执行 git fetch origin main && git reset --hard origin/main，或重新从 $GIT_REPO 克隆。"
fi

# ============================================================
# 1.2 PostgreSQL 安装与数据库初始化
# ============================================================
info "检查并安装 PostgreSQL..."
if ! command -v psql &> /dev/null; then
    sudo apt-get install -y -qq postgresql postgresql-contrib > /dev/null 2>&1
    ok "PostgreSQL 安装完成"
else
    ok "PostgreSQL 已安装"
fi

# 启动 PostgreSQL（兼容 systemd 和容器）
info "启动 PostgreSQL 服务..."
if [ "$HAS_SYSTEMD" = "1" ]; then
    sudo systemctl enable postgresql > /dev/null 2>&1 || true
    sudo systemctl start postgresql || true
else
    # 容器环境：直接初始化并启动 postgres 进程
    PG_VERSION=$(ls /etc/postgresql/ 2>/dev/null | sort -V | tail -1 || echo "")
    if [ -n "$PG_VERSION" ]; then
        # 确保数据目录已初始化
        PG_DATA="/var/lib/postgresql/$PG_VERSION/main"
        if [ ! -f "$PG_DATA/PG_VERSION" ]; then
            sudo -u postgres /usr/lib/postgresql/$PG_VERSION/bin/initdb -D "$PG_DATA" > /dev/null 2>&1 || true
        fi
        sudo service postgresql start || true
    else
        warn "无法确定 PostgreSQL 版本，尝试直接启动..."
        sudo service postgresql start || true
    fi
fi

PG_USER="netops"
PG_DB="netops"
PG_PASS=""

info "等待 PostgreSQL 服务就绪..."
for i in {1..30}; do
    if sudo -u postgres psql -c '\q' > /dev/null 2>&1; then
        ok "PostgreSQL 服务就绪"
        break
    fi
    if [ "$i" = "30" ]; then
        fail "PostgreSQL 服务未能正常响应，请手动检查: sudo service postgresql status"
    fi
    sleep 1
done

# 创建数据库用户和库
ROLE_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$PG_USER'" 2>/dev/null || echo "0")
if [ "$ROLE_EXISTS" != "1" ]; then
    PG_PASS=$(openssl rand -hex 16)
    sudo -u postgres psql -c "CREATE USER $PG_USER WITH PASSWORD '$PG_PASS';" > /dev/null || fail "创建数据库用户失败"
    sudo -u postgres psql -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" > /dev/null || fail "创建数据库失败"
    ok "PostgreSQL 数据库 ($PG_DB) 与用户 ($PG_USER) 创建完成"
else
    # 用户已存在：检查 .env 里是否已有有效密码，没有则重置
    EXISTING_DB_URL=$(grep "^DATABASE_URL=" "$PROJECT_DIR/.env" 2>/dev/null || true)
    if echo "$EXISTING_DB_URL" | grep -q "YOUR_PASSWORD\|replace-with\|@localhost:5432/$PG_DB$" || [ -z "$EXISTING_DB_URL" ]; then
        # .env 里没有有效密码，重置 PG 用户密码
        PG_PASS=$(openssl rand -hex 16)
        sudo -u postgres psql -c "ALTER USER $PG_USER WITH PASSWORD '$PG_PASS';" > /dev/null || fail "重置数据库密码失败"
        ok "PostgreSQL 用户 ($PG_USER) 已存在，密码已重置"
    else
        # .env 里已有有效密码，提取出来复用，不重置
        PG_PASS=$(echo "$EXISTING_DB_URL" | grep -oP '://[^:]+:\K[^@]+' || true)
        ok "PostgreSQL 用户 ($PG_USER) 已存在，复用现有密码"
    fi
    # 确保数据库存在
    DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" 2>/dev/null || echo "0")
    if [ "$DB_EXISTS" != "1" ]; then
        sudo -u postgres psql -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" > /dev/null || fail "创建数据库失败"
        ok "PostgreSQL 数据库 ($PG_DB) 创建完成"
    fi
fi

# ============================================================
# 2. Python 版本检查
# ============================================================
VENV_DIR="$PROJECT_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}"
NGINX_LINK="/etc/nginx/sites-enabled/${SERVICE_NAME}"

PYTHON_BIN=$(command -v python3 || true)
[ -z "$PYTHON_BIN" ] && fail "未找到 python3，请先安装 Python >= $PYTHON_MIN"

PY_VER=$($PYTHON_BIN -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$($PYTHON_BIN -c "import sys; print(1 if sys.version_info >= (3,10) else 0)")
[ "$PY_OK" != "1" ] && fail "Python 版本 $PY_VER 过低，需要 >= $PYTHON_MIN"
ok "Python $PY_VER"


# ============================================================
# 3. Node.js 安装 / 检查
# ============================================================
NEED_NODE=0
if command -v node &> /dev/null; then
    NODE_VER=$(node -v | tr -d 'v')
    NODE_MAJOR_CUR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "$NODE_MAJOR_CUR" -ge 20 ]; then
        ok "Node.js v$NODE_VER (已安装)"
    else
        warn "Node.js v$NODE_VER 版本过低，将安装 v${NODE_MAJOR}"
        NEED_NODE=1
    fi
else
    info "未检测到 Node.js，将安装 v${NODE_MAJOR}"
    NEED_NODE=1
fi

if [ "$NEED_NODE" = "1" ]; then
    info "通过 NodeSource 安装 Node.js ${NODE_MAJOR}..."
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | sudo -E bash - > /dev/null 2>&1
    sudo apt-get install -y -qq nodejs > /dev/null 2>&1
    ok "Node.js $(node -v) 安装完成"
fi

# ============================================================
# 4. Python 虚拟环境
# ============================================================
cd "$PROJECT_DIR"

if [ ! -d "$VENV_DIR" ]; then
    info "创建 Python 虚拟环境..."
    $PYTHON_BIN -m venv "$VENV_DIR"
    ok "虚拟环境创建于 $VENV_DIR"
else
    ok "虚拟环境已存在"
fi

info "安装 Python 依赖..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r backend/requirements.txt -q
ok "Python 依赖安装完成"

# ============================================================
# 5. Node.js 依赖 & 前端构建
# ============================================================
info "安装 Node.js 依赖..."
if [ -f package-lock.json ]; then
    npm ci --include=dev --prefer-offline 2>&1 | tail -5 || \
        npm ci --include=dev 2>&1 | tail -10 || \
        fail "npm ci 失败，请检查网络或 package-lock.json"
else
    npm install --include=dev --prefer-offline 2>&1 | tail -5 || \
        npm install --include=dev 2>&1 | tail -10 || \
        fail "npm install 失败，请检查网络或 package.json"
fi
ok "Node.js 依赖安装完成"

info "构建前端生产版本..."
npm run build 2>&1 | tail -5 || fail "前端构建失败，请检查 Node.js 版本或依赖"
ok "前端构建完成 (dist/)"

# ============================================================
# 6. 环境文件 (.env)
# ============================================================
if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        info "正在生成 .env 配置文件..."
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        # 强制转换 CRLF → LF，避免 Windows 换行符导致 sed 替换失败
        sed -i 's/\r$//' "$PROJECT_DIR/.env"

        NEW_SECRET=$(openssl rand -hex 32)
        NEW_CRED_KEY=$(openssl rand -hex 32)
        sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$NEW_SECRET/" "$PROJECT_DIR/.env"
        sed -i "s/^CREDENTIAL_ENCRYPTION_KEY=.*/CREDENTIAL_ENCRYPTION_KEY=$NEW_CRED_KEY/" "$PROJECT_DIR/.env"

        # 交互式询问是否需要自定义常见变量（设置 10 秒超时自动静默）
        if [ -t 0 ]; then
            echo ""
            info "============================================================"
            info "  环境配置定制 (.env)"
            info "  系统已生成高强度加密密钥与随机数据库凭证。"
            info "  是否需自定义数据库密码或端口？(10 秒无操作则自动静默继续)"
            info "============================================================"
            read -t 10 -p "是否手动配置？[y/N]: " CUSTOMIZE_ENV || CUSTOMIZE_ENV="N"
            if [[ "$CUSTOMIZE_ENV" =~ ^[Yy]$ ]]; then
                echo ""
                read -p "请输入自定义 PostgreSQL 密码 [直接回车保持自动随机]: " INPUT_PG_PASS
                if [ -n "$INPUT_PG_PASS" ]; then
                    PG_PASS="$INPUT_PG_PASS"
                    sudo -u postgres psql -c "ALTER USER $PG_USER WITH PASSWORD '$PG_PASS';" > /dev/null || true
                    ok "已将 PostgreSQL 用户 $PG_USER 密码更新为您指定的密码"
                fi
                read -p "请输入后端监听端口 [默认 $BACKEND_PORT]: " INPUT_PORT
                if [ -n "$INPUT_PORT" ] && [[ "$INPUT_PORT" =~ ^[0-9]+$ ]]; then
                    BACKEND_PORT="$INPUT_PORT"
                    ok "后端服务端口设定为 $BACKEND_PORT"
                fi
                read -p "请输入 Nginx 外部监听端口 [默认 $NGINX_PORT]: " INPUT_NGINX
                if [ -n "$INPUT_NGINX" ] && [[ "$INPUT_NGINX" =~ ^[0-9]+$ ]]; then
                    NGINX_PORT="$INPUT_NGINX"
                    ok "Nginx 代理端口设定为 $NGINX_PORT"
                fi
            else
                info "采用默认安全配置继续..."
            fi
            echo ""
        fi

        if [ -n "$PG_PASS" ]; then
            sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://$PG_USER:$PG_PASS@localhost:5432/$PG_DB|" "$PROJECT_DIR/.env"
            ok "已创建 .env（SECRET_KEY、CREDENTIAL_ENCRYPTION_KEY 已生成，PostgreSQL 凭证已更新）"
        else
            sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://$PG_USER:YOUR_PASSWORD@localhost:5432/$PG_DB|" "$PROJECT_DIR/.env"
            warn ".env 已创建，但数据库密码需要手动更新 (DATABASE_URL)"
        fi
    else
        warn "未找到 .env.example，跳过环境文件自动生成"
    fi
fi

# ── 无论 .env 是新建还是已存在，先统一转换换行符，再修正配置 ──
if [ -f "$PROJECT_DIR/.env" ]; then
    # 转换 CRLF → LF（Windows 开发机上传的文件可能带 \r）
    sed -i 's/\r$//' "$PROJECT_DIR/.env"

    # 修正 Docker 服务名 db → localhost
    if grep -q '@db:' "$PROJECT_DIR/.env" 2>/dev/null; then
        sed -i 's|@db:|@localhost:|g' "$PROJECT_DIR/.env"
        warn ".env 中 DATABASE_URL 的主机名 'db' 已自动替换为 'localhost'（非 Docker Compose 环境）"
    fi

    # 如果 DATABASE_URL 还是占位符且现在有密码，补写进去
    if [ -n "$PG_PASS" ] && grep -q 'YOUR_PASSWORD' "$PROJECT_DIR/.env" 2>/dev/null; then
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://$PG_USER:$PG_PASS@localhost:5432/$PG_DB|" "$PROJECT_DIR/.env"
        ok "DATABASE_URL 已更新（使用当前 PostgreSQL 密码）"
    fi
fi

# ============================================================
# 7. 数据目录
# ============================================================
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/backup"
ok "数据目录就绪"

# ============================================================
# 8. 设置 ping3 CAP_NET_RAW 权限
# ============================================================
VENV_PYTHON=$(readlink -f "$VENV_DIR/bin/python")
CURRENT_CAPS=$(getcap "$VENV_PYTHON" 2>/dev/null || true)
if echo "$CURRENT_CAPS" | grep -q cap_net_raw; then
    ok "Python 已具备 CAP_NET_RAW 权限"
else
    info "设置 CAP_NET_RAW 权限 (用于 ICMP ping)..."
    sudo setcap cap_net_raw+ep "$VENV_PYTHON" && ok "CAP_NET_RAW 权限设置完成" || warn "CAP_NET_RAW 设置失败（容器环境可能不支持，ping 功能受限）"
fi

# ============================================================
# 9. inotify 限制
# ============================================================
CURRENT_WATCHES=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo 0)
if [ "$CURRENT_WATCHES" -lt 524288 ]; then
    info "调整 inotify watcher 限制..."
    echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf > /dev/null
    echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf > /dev/null
    sudo sysctl -p > /dev/null 2>&1 || true
    ok "inotify 限制已调整"
else
    ok "inotify watcher 限制已足够 ($CURRENT_WATCHES)"
fi

# ============================================================
# 10. 防火墙
# ============================================================
if command -v ufw &> /dev/null; then
    UFW_STATUS=$(sudo ufw status 2>/dev/null | head -1 || echo "inactive")
    if echo "$UFW_STATUS" | grep -qi "active"; then
        sudo ufw allow 'Nginx Full' > /dev/null 2>&1
        ok "UFW 已放行 Nginx Full (80/443)"
    else
        ok "UFW 未启用，跳过防火墙配置"
    fi
else
    ok "未检测到 UFW，跳过防火墙配置"
fi

# ============================================================
# 11. 配置 Nginx 反向代理
# ============================================================
info "配置 Nginx 反向代理..."

sudo tee "$NGINX_CONF" > /dev/null <<'NGINXEOF'
upstream netops_backend {
    server 127.0.0.1:8003;
    keepalive 32;
}

server {
    listen _PLACEHOLDER_NGINX_PORT_;
    listen [::]:_PLACEHOLDER_NGINX_PORT_;
    server_name _PLACEHOLDER_SERVER_NAME_;

    add_header X-Frame-Options        "SAMEORIGIN"       always;
    add_header X-Content-Type-Options  "nosniff"          always;
    add_header X-XSS-Protection        "1; mode=block"    always;
    add_header Referrer-Policy          "strict-origin-when-cross-origin" always;
    # Content-Security-Policy: locks down which origins the page may
    # pull resources from. `'unsafe-inline'` on script-src is needed
    # because Vite injects a tiny inline bootstrap; everything else
    # must come from the same origin or trusted CDNs.
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss: http://127.0.0.1:17890 http://localhost:17890; frame-ancestors 'self';" always;

    client_max_body_size 150m;

    location /assets/ {
        alias _PLACEHOLDER_PROJECT_DIR_/dist/assets/;
        expires 365d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location ~* \.(ico|svg|png|jpg|jpeg|gif|webp|woff2?|ttf|eot|css|js|map)$ {
        root _PLACEHOLDER_PROJECT_DIR_/dist;
        expires 30d;
        add_header Cache-Control "public";
        access_log off;
        try_files $uri @backend;
    }

    location /api/ {
        proxy_pass http://netops_backend;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location /api/ws/ {
        proxy_pass http://netops_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host       $host;
        proxy_set_header X-Real-IP  $remote_addr;
        proxy_read_timeout 86400s;
    }

    location / {
        root _PLACEHOLDER_PROJECT_DIR_/dist;
        try_files $uri $uri/ /index.html;
    }

    location @backend {
        proxy_pass http://netops_backend;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_min_length 1024;
    gzip_types
        text/plain text/css text/xml text/javascript
        application/json application/javascript application/xml
        application/rss+xml image/svg+xml;
}
NGINXEOF

sudo sed -i "s|_PLACEHOLDER_SERVER_NAME_|$SERVER_NAME|g"     "$NGINX_CONF"
sudo sed -i "s|_PLACEHOLDER_PROJECT_DIR_|$PROJECT_DIR|g"     "$NGINX_CONF"
sudo sed -i "s|_PLACEHOLDER_NGINX_PORT_|$NGINX_PORT|g"       "$NGINX_CONF"

if [ -L "$NGINX_LINK" ]; then sudo rm "$NGINX_LINK"; fi
sudo ln -s "$NGINX_CONF" "$NGINX_LINK"
if [ -L /etc/nginx/sites-enabled/default ]; then sudo rm /etc/nginx/sites-enabled/default; fi

sudo nginx -t 2>&1 || fail "Nginx 配置测试失败"
svc_enable nginx
svc_reload nginx
ok "Nginx 反向代理配置完成 (监听 :${NGINX_PORT})"

# ============================================================
# 12. 服务管理（systemd 或容器后台进程）
# ============================================================
if [ "$HAS_SYSTEMD" = "1" ]; then
    # ── systemd 模式 ──
    info "配置 systemd 服务..."
    sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=NetOps Automation Platform
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/uvicorn backend.main:app --host 127.0.0.1 --port $BACKEND_PORT --workers 2
Restart=always
RestartSec=5
Environment=NODE_ENV=production
Environment=PORT=$BACKEND_PORT
Environment=PYTHONPATH=$PROJECT_DIR/backend
EnvironmentFile=-$PROJECT_DIR/.env
AmbientCapabilities=CAP_NET_RAW

ProtectSystem=strict
ReadWritePaths=$PROJECT_DIR/data $PROJECT_DIR/backup $PROJECT_DIR/backend
ProtectHome=true
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=65536
MemoryMax=1G

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    svc_enable "$SERVICE_NAME"
    svc_restart "$SERVICE_NAME"
    sleep 3

    if svc_is_active "$SERVICE_NAME"; then
        ok "$SERVICE_NAME 服务已启动 (systemd)"
    else
        warn "服务启动可能失败，查看日志: sudo journalctl -u $SERVICE_NAME -f"
    fi

else
    # ── 容器模式：后台启动 uvicorn ──
    info "容器环境，以后台进程方式启动后端..."

    # 停止旧进程
    OLD_PID=$(pgrep -f "uvicorn backend.main:app" 2>/dev/null || true)
    if [ -n "$OLD_PID" ]; then
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi

    LOG_FILE="$PROJECT_DIR/data/netops.log"
    mkdir -p "$PROJECT_DIR/data"

    # 构建启动命令（通过 env file 传递环境变量，避免 xargs 特殊字符问题）
    ENV_LOADER=""
    if [ -f "$PROJECT_DIR/.env" ]; then
        ENV_LOADER="set -a; source $PROJECT_DIR/.env; set +a;"
    fi

    nohup bash -c "
        $ENV_LOADER
        export NODE_ENV=production
        export PORT=$BACKEND_PORT
        export PYTHONPATH=$PROJECT_DIR/backend
        exec $VENV_DIR/bin/uvicorn backend.main:app \
            --host 127.0.0.1 \
            --port $BACKEND_PORT \
            --workers 1
    " > "$LOG_FILE" 2>&1 &

    BACKEND_PID=$!
    echo "$BACKEND_PID" > "$PROJECT_DIR/data/netops.pid"
    info "后端进程已启动 (PID: $BACKEND_PID)，等待就绪..."

    # 等待后端响应
    for i in {1..20}; do
        if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
            ok "后端服务已就绪 (PID: $BACKEND_PID)"
            break
        fi
        if [ "$i" = "20" ]; then
            warn "后端未能在预期时间内响应，查看日志: tail -f $LOG_FILE"
        fi
        sleep 2
    done
fi

# ============================================================
# 8. 生产环境安全提示
# ============================================================
# A deployment must not mutate the checked-out source tree.  In particular,
# do not remove tests, docs, scratch directories, or Git metadata: the target
# may be a shared clone and those paths may belong to another local workflow.
info "保留项目源码、测试、文档及 Git 元数据，不执行目录清理"
ok "已跳过源码目录删除；如需精简请使用独立、明确的打包目录"

# ============================================================
# 完成
# ============================================================
echo ""
echo "========================================"
echo -e "  ${GREEN}部署完成！${NC}"
echo "========================================"
echo ""
echo "  访问地址:  http://<服务器IP>  (Nginx :${NGINX_PORT} → 后端 :${BACKEND_PORT})"
echo "  默认账号:  admin / admin"
echo "  (首次登录后请立即修改为强密码)"
echo ""

if [ "$HAS_SYSTEMD" = "1" ]; then
echo "  常用命令 (systemd):"
echo "    查看状态:  sudo systemctl status $SERVICE_NAME"
echo "    查看日志:  sudo journalctl -u $SERVICE_NAME -f"
echo "    重启服务:  sudo systemctl restart $SERVICE_NAME"
echo "    停止服务:  sudo systemctl stop $SERVICE_NAME"
else
echo "  常用命令 (容器/Codespaces):"
echo "    查看日志:  tail -f $PROJECT_DIR/data/netops.log"
echo "    查看进程:  cat $PROJECT_DIR/data/netops.pid"
echo "    停止服务:  kill \$(cat $PROJECT_DIR/data/netops.pid)"
echo "    重启服务:  kill \$(cat $PROJECT_DIR/data/netops.pid) && bash $0"
fi
echo ""
echo "  Nginx 日志: sudo tail -f /var/log/nginx/error.log"
echo "  Nginx 重载: sudo nginx -t && sudo nginx -s reload"
echo ""

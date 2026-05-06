#!/usr/bin/env bash
# ============================================================
#  NetOps Automation — Ubuntu 一键部署脚本
#  用法:  chmod +x deploy-ubuntu.sh && ./deploy-ubuntu.sh
#  支持:  Ubuntu 20.04 / 22.04 / 24.04 (x86_64 / arm64)
# ============================================================

set -euo pipefail

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
NODE_MAJOR=22                       # Node.js LTS 大版本
PYTHON_MIN="3.10"                   # 最低 Python 版本
GIT_REPO="https://github.com/libing28390-sketch/Release-netops.git"
PROJECT_NAME="netops-automation"
SERVICE_NAME="netops"
BACKEND_PORT=8003
NGINX_PORT=80                       # Nginx 监听端口
SERVER_NAME="_"                     # 默认匹配所有域名，部署后按需改为实际域名

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
# 1. 系统依赖
# ============================================================
info "安装系统依赖..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential libffi-dev libssl-dev \
    nginx libcap2-bin \
    curl git ca-certificates > /dev/null 2>&1
ok "系统依赖安装完成（含 Nginx、Git）"

# ============================================================
# 1.1 PostgreSQL 数据库安装与配置
# ============================================================
info "检查并安装 PostgreSQL..."
if ! command -v psql &> /dev/null; then
    sudo apt-get install -y -qq postgresql postgresql-contrib > /dev/null 2>&1
    sudo systemctl enable postgresql > /dev/null 2>&1
    sudo systemctl start postgresql
    ok "PostgreSQL 安装完成"
else
    ok "PostgreSQL 已安装"
fi

PG_USER="netops"
PG_DB="netops"
PG_PASS=""

info "等待 PostgreSQL 服务就绪..."
for i in {1..30}; do
    if sudo -u postgres psql -c '\q' > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! sudo -u postgres psql -c '\q' > /dev/null 2>&1; then
    fail "PostgreSQL 服务未能正常响应，请检查服务状态: systemctl status postgresql"
fi

# 检查用户是否已存在，如果不存在则自动创建数据库和用户
ROLE_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$PG_USER'" || echo "0")
if [ "$ROLE_EXISTS" != "1" ]; then
    PG_PASS=$(openssl rand -hex 16)
    sudo -u postgres psql -c "CREATE USER $PG_USER WITH PASSWORD '$PG_PASS';" > /dev/null || fail "创建数据库用户失败"
    sudo -u postgres psql -c "CREATE DATABASE $PG_DB OWNER $PG_USER;" > /dev/null || fail "创建数据库失败"
    ok "PostgreSQL 数据库 ($PG_DB) 与用户 ($PG_USER) 创建完成"
else
    ok "PostgreSQL 用户 ($PG_USER) 已存在，跳过自动创建"
fi

# ============================================================
# 1.5 如果不在项目目录中，则从 Git 克隆
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/backend/main.py" ]; then
    # 脚本在项目目录内运行
    PROJECT_DIR="$SCRIPT_DIR"
    ok "检测到项目目录: $PROJECT_DIR"
else
    # 脚本独立运行，需要 git clone
    INSTALL_BASE="${INSTALL_DIR:-/opt}"
    PROJECT_DIR="$INSTALL_BASE/$PROJECT_NAME"
    if [ -d "$PROJECT_DIR/.git" ]; then
        info "项目目录已存在，拉取最新代码..."
        cd "$PROJECT_DIR"
        git pull --ff-only || warn "git pull 失败，使用当前版本继续"
        ok "代码更新完成: $PROJECT_DIR"
    else
        info "从 Git 克隆项目..."
        sudo mkdir -p "$INSTALL_BASE"
        sudo chown "$RUN_USER:$(id -gn $RUN_USER)" "$INSTALL_BASE" 2>/dev/null || true
        git clone "$GIT_REPO" "$PROJECT_DIR"
        ok "项目克隆完成: $PROJECT_DIR"
    fi
fi

info "目标目录: $PROJECT_DIR"

# ============================================================
# 2. Python 版本检查
# ============================================================
VENV_DIR="$PROJECT_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}"
NGINX_LINK="/etc/nginx/sites-enabled/${SERVICE_NAME}"

PYTHON_BIN=$(command -v python3 || true)
if [ -z "$PYTHON_BIN" ]; then
    fail "未找到 python3，请先安装 Python >= $PYTHON_MIN"
fi

PY_VER=$($PYTHON_BIN -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$($PYTHON_BIN -c "import sys; print(1 if sys.version_info >= (3,10) else 0)")
if [ "$PY_OK" != "1" ]; then
    fail "Python 版本 $PY_VER 过低，需要 >= $PYTHON_MIN"
fi
ok "Python $PY_VER"

# ============================================================
# 3. Node.js 安装 / 检查
# ============================================================
if command -v node &> /dev/null; then
    NODE_VER=$(node -v | tr -d 'v')
    NODE_MAJOR_CUR=$(echo "$NODE_VER" | cut -d. -f1)
    if [ "$NODE_MAJOR_CUR" -ge 18 ]; then
        ok "Node.js v$NODE_VER (已安装)"
    else
        warn "Node.js v$NODE_VER 版本过低，将安装 v${NODE_MAJOR}"
        NEED_NODE=1
    fi
else
    info "未检测到 Node.js，将安装 v${NODE_MAJOR}"
    NEED_NODE=1
fi

if [ "${NEED_NODE:-0}" = "1" ]; then
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
# 5. Node.js 依赖
# ============================================================
info "安装 Node.js 依赖..."
npm install --silent 2>&1 | tail -1
ok "Node.js 依赖安装完成"

# ============================================================
# 6. 构建前端
# ============================================================
info "构建前端生产版本..."
npm run build --silent
ok "前端构建完成 (dist/)"

# ============================================================
# 7. 环境文件 (.env)
# ============================================================
if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        info "正在生成 .env 配置文件..."
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        
        # 随机生成 SECRET_KEY
        NEW_SECRET=$(openssl rand -hex 32)
        sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$NEW_SECRET/" "$PROJECT_DIR/.env"
        
        # 写入本地 PostgreSQL 配置
        if [ -n "$PG_PASS" ]; then
            sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://$PG_USER:$PG_PASS@localhost:5432/$PG_DB|" "$PROJECT_DIR/.env"
            ok "已从 .env.example 创建 .env (并配置了生成的 PostgreSQL 访问凭证)"
        else
            sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://$PG_USER:YOUR_PASSWORD@localhost:5432/$PG_DB|" "$PROJECT_DIR/.env"
            warn "注意: .env 已创建，但数据库密码需要您手动更新 (DATABASE_URL)"
        fi
    else
        warn "未找到 .env.example，跳过环境文件自动生成"
    fi
fi

# ============================================================
# 8. 数据目录
# ============================================================
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/backup"
ok "数据目录就绪"

# ============================================================
# 9. 设置 ping3 RAW 权限
# ============================================================
VENV_PYTHON=$(readlink -f "$VENV_DIR/bin/python")
CURRENT_CAPS=$(getcap "$VENV_PYTHON" 2>/dev/null || true)
if echo "$CURRENT_CAPS" | grep -q cap_net_raw; then
    ok "Python 已具备 CAP_NET_RAW 权限"
else
    info "设置 CAP_NET_RAW 权限 (用于 ICMP ping)..."
    sudo setcap cap_net_raw+ep "$VENV_PYTHON"
    ok "CAP_NET_RAW 权限设置完成"
fi

# ============================================================
# 10. 调整 inotify 限制（避免 Vite watcher 报错）
# ============================================================
CURRENT_WATCHES=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo 0)
if [ "$CURRENT_WATCHES" -lt 524288 ]; then
    info "调整 inotify watcher 限制..."
    echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf > /dev/null
    echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf > /dev/null
    sudo sysctl -p > /dev/null 2>&1
    ok "inotify 限制已调整"
else
    ok "inotify watcher 限制已足够 ($CURRENT_WATCHES)"
fi

# ============================================================
# 11. 防火墙
# ============================================================
if command -v ufw &> /dev/null; then
    UFW_STATUS=$(sudo ufw status | head -1)
    if echo "$UFW_STATUS" | grep -qi "active"; then
        info "开放 HTTP/HTTPS 端口..."
        sudo ufw allow 'Nginx Full' > /dev/null 2>&1
        ok "UFW 已放行 Nginx Full (80/443)"
    else
        ok "UFW 未启用，跳过防火墙配置"
    fi
else
    ok "未检测到 UFW，跳过防火墙配置"
fi

# ============================================================
# 12. 配置 Nginx 反向代理
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

    # ── 安全头 ──
    add_header X-Frame-Options        "SAMEORIGIN"       always;
    add_header X-Content-Type-Options  "nosniff"          always;
    add_header X-XSS-Protection        "1; mode=block"    always;
    add_header Referrer-Policy          "strict-origin-when-cross-origin" always;

    # ── 请求体限制 ──
    client_max_body_size 20m;

    # ── 静态资源 (Vite 构建产物) ──
    location /assets/ {
        alias _PLACEHOLDER_PROJECT_DIR_/dist/assets/;
        expires 365d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # ── 其他前端静态文件 ──
    location ~* \.(ico|svg|png|jpg|jpeg|gif|webp|woff2?|ttf|eot|css|js|map)$ {
        root _PLACEHOLDER_PROJECT_DIR_/dist;
        expires 30d;
        add_header Cache-Control "public";
        access_log off;
        try_files $uri @backend;
    }

    # ── API / WebSocket 反向代理 ──
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

    # ── 前端 SPA 回退 ──
    location / {
        root _PLACEHOLDER_PROJECT_DIR_/dist;
        try_files $uri $uri/ /index.html;
    }

    # ── 内部 fallback ──
    location @backend {
        proxy_pass http://netops_backend;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ── Gzip 压缩 ──
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

# 替换占位符为实际值
sudo sed -i "s|_PLACEHOLDER_SERVER_NAME_|$SERVER_NAME|g" "$NGINX_CONF"
sudo sed -i "s|_PLACEHOLDER_PROJECT_DIR_|$PROJECT_DIR|g" "$NGINX_CONF"
sudo sed -i "s|_PLACEHOLDER_NGINX_PORT_|$NGINX_PORT|g" "$NGINX_CONF"

# 启用站点
if [ -L "$NGINX_LINK" ]; then
    sudo rm "$NGINX_LINK"
fi
sudo ln -s "$NGINX_CONF" "$NGINX_LINK"

# 删除默认站点（如果还在）
if [ -L /etc/nginx/sites-enabled/default ]; then
    sudo rm /etc/nginx/sites-enabled/default
fi

# 测试并重载 Nginx
sudo nginx -t 2>&1 || fail "Nginx 配置测试失败"
sudo systemctl enable nginx > /dev/null 2>&1
sudo systemctl reload nginx
ok "Nginx 反向代理配置完成 (监听 :80)"

# ============================================================
# 13. 创建 systemd 服务
# ============================================================
info "配置 systemd 服务..."

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=NetOps Automation Platform
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_DIR/bin/python backend/main.py
Restart=always
RestartSec=5
Environment=NODE_ENV=production
Environment=PYTHONPATH=$PROJECT_DIR/backend
EnvironmentFile=-$PROJECT_DIR/.env
AmbientCapabilities=CAP_NET_RAW

# Security hardening
ProtectSystem=strict
ReadWritePaths=$PROJECT_DIR/data $PROJECT_DIR/backup $PROJECT_DIR/backend
ProtectHome=true
NoNewPrivileges=true
PrivateTmp=true

# Resource limits
LimitNOFILE=65536
MemoryMax=1G

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" > /dev/null 2>&1
ok "systemd 服务 [$SERVICE_NAME] 已创建并设为开机启动"

# ============================================================
# 14. 启动服务
# ============================================================
info "启动 $SERVICE_NAME 服务..."
sudo systemctl restart "$SERVICE_NAME"
sleep 3

if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "$SERVICE_NAME 服务已启动"
else
    warn "服务启动可能失败，查看日志: sudo journalctl -u $SERVICE_NAME -f"
fi

# 确保 Nginx 正在运行
if sudo systemctl is-active --quiet nginx; then
    ok "Nginx 反向代理运行中"
else
    warn "Nginx 未运行，尝试启动..."
    sudo systemctl start nginx
fi

# ============================================================
# 完成
# ============================================================
echo ""
echo "========================================"
echo -e "  ${GREEN}部署完成！${NC}"
echo "========================================"
echo ""
echo "  访问地址:  http://<服务器IP>  (Nginx 反向代理 → :${BACKEND_PORT})"
echo "  默认账号:  admin / admin"
echo "  (首次登录后请立即修改为强密码)"
echo ""
echo "  常用命令:"
echo "    查看状态:  sudo systemctl status $SERVICE_NAME"
echo "    查看日志:  sudo journalctl -u $SERVICE_NAME -f"
echo "    重启服务:  sudo systemctl restart $SERVICE_NAME"
echo "    停止服务:  sudo systemctl stop $SERVICE_NAME"
echo "    Nginx 状态: sudo systemctl status nginx"
echo "    Nginx 日志: sudo tail -f /var/log/nginx/error.log"
echo "    Nginx 重载: sudo nginx -t && sudo systemctl reload nginx"
echo ""

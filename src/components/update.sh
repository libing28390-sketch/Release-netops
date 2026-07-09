cat << 'EOF' > update.sh
#!/bin/bash

# --- 配置 ---
PROJECT_DIR="/opt/netops-automation"
SERVICE_NAME="netops"

echo "🚀 开始自动更新流程..."

# 1. 进入项目目录
cd $PROJECT_DIR || exit

# 2. 从 GitHub 拉取最新代码
echo "📥 正在拉取代码 (git pull)..."
git pull

# 3. 更新 Python 虚拟环境依赖 (以防后端依赖变化)
if [ -f "requirements.txt" ]; then
    echo "🐍 正在检查/更新 Python 依赖..."
    ./.venv/bin/pip install -r requirements.txt -q
fi

# 4. 更新 Node.js 依赖并构建前端
if [ -f "package.json" ]; then
    echo "📦 正在更新前端依赖并执行构建 (npm run build)..."
    npm install -q
    npm run build
fi

# 5. 重启 Systemd 服务
echo "🔄 正在重启后端服务 ($SERVICE_NAME)..."
sudo systemctl restart $SERVICE_NAME

# 6. 清理
echo "✅ 更新完成！"
echo "建议：如果页面没变化，请在浏览器按 Ctrl+F5 强制刷新。"

exit 0
EOF

# 赋予执行权限
chmod +x update.sh

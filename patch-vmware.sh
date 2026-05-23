#!/usr/bin/env bash
# ============================================================
#  NetOps 补丁脚本 — 在 VMware 虚机上直接执行
#  修复：
#    1. PAM WebSocket 404（ws_router 拆分，绕过 Depends 拦截）
#    2. Nginx 添加 /api/pam/ws/ WebSocket 代理
#    3. system.py 支持前端客户端侧启动模式
#  用法：cd ~/netops-automation && bash patch-vmware.sh
# ============================================================
set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "[INFO] 项目目录: $PROJECT_DIR"

python3 << PYEOF
import os, re, sys

proj = "$PROJECT_DIR"

# ── 1. backend/api/pam.py ────────────────────────────────────
pam_path = os.path.join(proj, 'backend/api/pam.py')
with open(pam_path) as f:
    pam = f.read()

changed = False

# 1a. 在 router = APIRouter() 后插入 ws_router
if 'ws_router = APIRouter()' not in pam:
    pam = pam.replace(
        'router = APIRouter()',
        'router = APIRouter()\n'
        '# WebSocket 路由单独放在无依赖的 router，避免 FastAPI 在 WS 握手阶段\n'
        '# 因 Depends(require_feature) 无法注入 Request 而返回 404。\n'
        'ws_router = APIRouter()',
        1
    )
    changed = True
    print('[PATCH] pam.py: 添加 ws_router')
else:
    print('[SKIP]  pam.py: ws_router 已存在')

# 1b. 把 @router.websocket('/pam/ws/ 改为 @ws_router.websocket
if "@router.websocket('/pam/ws/" in pam:
    pam = pam.replace("@router.websocket('/pam/ws/", "@ws_router.websocket('/pam/ws/")
    changed = True
    print('[PATCH] pam.py: websocket 路由改为 ws_router')
else:
    print('[SKIP]  pam.py: websocket 路由已是 ws_router')

if changed:
    with open(pam_path, 'w') as f:
        f.write(pam)

# ── 2. backend/main.py ───────────────────────────────────────
main_path = os.path.join(proj, 'backend/main.py')
with open(main_path) as f:
    main = f.read()

changed = False

# 2a. 导入 ws_router
if 'ws_router as pam_ws_router' not in main:
    main = main.replace(
        'from api.pam import router as pam_router',
        'from api.pam import router as pam_router, ws_router as pam_ws_router',
        1
    )
    changed = True
    print('[PATCH] main.py: 导入 pam_ws_router')
else:
    print('[SKIP]  main.py: pam_ws_router 已导入')

# 2b. 注册 ws_router（在 audit_router 行后）
if 'pam_ws_router' not in main:
    main = main.replace(
        'app.include_router(audit_router,',
        'app.include_router(audit_router,',
        1
    )
    # 找到 audit_router 那行，在其后插入
    lines = main.splitlines()
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if 'app.include_router(audit_router,' in line and 'rbac' in line:
            new_lines.append('# PAM WebSocket 单独注册，不带 feature 依赖（token 本身即凭证）')
            new_lines.append('app.include_router(pam_ws_router,         prefix="/api")')
    main = '\n'.join(new_lines)
    changed = True
    print('[PATCH] main.py: 注册 pam_ws_router')
else:
    print('[SKIP]  main.py: pam_ws_router 已注册')

if changed:
    with open(main_path, 'w') as f:
        f.write(main)

# ── 3. backend/api/system.py ─────────────────────────────────
sys_path = os.path.join(proj, 'backend/api/system.py')
with open(sys_path) as f:
    sys_content = f.read()

if '__client_side_launch__' not in sys_content:
    old = (
        '    if not path or not os.path.exists(path):\n'
        '        return {"success": False, "error": f"Executable path not found: {path}"}'
    )
    new = (
        '    if not path or not os.path.exists(path):\n'
        '        # 前端客户端侧启动：path 为特殊标记，跳过文件检查，只写审计日志\n'
        '        if path in (\'__client_side_launch__\', \'__mfa_verify_only__\'):\n'
        '            return {"success": True, "session_id": session_id, "client_side": True}\n'
        '        return {"success": False, "error": f"Executable path not found: {path}"}'
    )
    if old in sys_content:
        sys_content = sys_content.replace(old, new)
        with open(sys_path, 'w') as f:
            f.write(sys_content)
        print('[PATCH] system.py: 添加 client_side_launch 支持')
    else:
        print('[WARN]  system.py: 未找到目标代码段，请手动检查')
else:
    print('[SKIP]  system.py: client_side_launch 已支持')

# ── 4. nginx/nginx.conf ──────────────────────────────────────
nginx_path = os.path.join(proj, 'nginx/nginx.conf')
with open(nginx_path) as f:
    nginx = f.read()

if '/api/pam/ws/' not in nginx:
    pam_ws_block = (
        '    # ── WebSocket (PAM 受控终端) ──\n'
        '    location ^~ /api/pam/ws/ {\n'
        '        proxy_pass http://netops_backend;\n'
        '        proxy_http_version 1.1;\n'
        '        proxy_set_header Upgrade    \$http_upgrade;\n'
        '        proxy_set_header Connection "upgrade";\n'
        '        proxy_set_header Host       \$host;\n'
        '        proxy_set_header X-Real-IP  \$remote_addr;\n'
        '        proxy_read_timeout 86400s;\n'
        '        proxy_send_timeout 86400s;\n'
        '    }\n\n'
    )
    # 在第一个 location /api/ws/ 或 # ── WebSocket 注释前插入
    nginx = re.sub(
        r'(    # ── WebSocket)',
        pam_ws_block + r'\1',
        nginx,
        count=1
    )
    with open(nginx_path, 'w') as f:
        f.write(nginx)
    print('[PATCH] nginx.conf: 添加 /api/pam/ws/ 代理块')
else:
    print('[SKIP]  nginx.conf: /api/pam/ws/ 已存在')

print('')
print('所有文件补丁完成。')
PYEOF

# ── 5. 重启服务 ──────────────────────────────────────────────
echo ""
echo "[INFO] 重启 netops 容器（加载新代码）..."
docker compose restart netops

echo "[INFO] 等待容器健康检查..."
sleep 8

echo "[INFO] 重载 nginx 配置..."
docker compose exec nginx nginx -s reload

echo ""
echo "========================================"
echo "  补丁应用完成！"
echo "========================================"
echo ""
echo "  验证："
echo "    docker compose logs netops --tail=30 | grep -i 'pam\|ws\|route\|error'"
echo ""

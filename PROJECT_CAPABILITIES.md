# Nexora Project Capabilities

## Core Skills

### 1) Network Automation
- Tools: Netmiko, Scrapli, TextFSM (`backend/core/textfsm.py`)
- Use for: multi-vendor command execution, parser-based extraction, playbook debugging

### 2) Frontend Delivery
- Tools: React 19, Tailwind v4, motion/react, Lucide
- Use for: dashboard/ops UI implementation, component refactor, interaction polishing

### 3) Runtime Troubleshooting
- Tools: `scripts/startup_logger.cjs`, backend logs, Vite build output
- Use for: startup failures, API 500 analysis, frontend build/runtime regressions

## MCP Integration

Project MCP config file: [mcp-config.json](/D:/tools/netops/mcp-config.json)

Enabled servers:
- `playwright`: UI inspection and screenshot checks
- `filesystem`: workspace file operations
- `postgres`: direct query of PostgreSQL operational data
- `git`: commit/history analysis
- `github`: PR/issue context (when token is configured)

## Skills Invocation Guide

Recommended trigger phrases:
- `排查接口容量异常` / `capacity forecast debug`: prioritize `postgres` + backend API tracing
- `验证前端页面` / `open localhost`: prioritize `playwright`
- `拆分 App.tsx` / `refactor app shell`: prioritize code refactor workflow + `git`
- `检查设备巡检逻辑` / `inspection troubleshooting`: prioritize network automation skill

Suggested execution order:
1. `filesystem` read target code and config
2. `postgres` verify table/field reality
3. patch code and run `npm run build`
4. `playwright` verify UI behavior if frontend changes

# Guacamole VNC 实机纳管验证

## 背景

RDP 已通过 LEERBON 完成实机验证，但该 Windows 10 Pro 主机原来没有 VNC Server，TCP 5900 无监听，无法确认 Nexora 的 VNC 链路。

## 处理

- 用户授权在 LEERBON 安装测试 VNC 服务。使用 TightVNC 官方站点的 2.8.90 64 位包，Authenticode 签名验证有效；用户完成本机许可、服务安装和口令设置。
- 目标 Windows 防火墙配置文件均关闭。为避免将无效的防火墙规则当作限制，按用户授权在 TightVNC 的访问控制中先允许 `192.168.204.128`，再拒绝其余 IPv4 地址。通过管理权限更新配置并重启服务后，规则值与服务状态均已核验。
- Nexora 为 LEERBON 启用 VNC 入口，端口 5900，引用已有的 `test-rdp-leerbon` 凭据。Guacamole VNC 连接仅使用凭据密码，不要求用户名；密码值不写入文档或日志。

## 验证

- 访问工作台真实连接 LEERBON；页面显示 VNC 已连接且实际出现 Windows 桌面。
- PAM 会话 `pam-vnc-5adeb00d914f4f928951263e738da7fe` 在 21 秒后关闭；历史记录显示 `VNC 图形会话` 和录像可用。
- 数据库状态为 `closed`、`recording_status=uploaded`、`storage_status=READY`，对象键存在，录像大小 1,401,015 字节，确认 `.guac` 录像已归档到现有 S3 兼容存储。

## 安全说明

本次测试使用的口令较弱，仅适合测试；TightVNC 传统 VNC 认证最多使用 8 个字符。生产前应换成唯一高熵口令。当前来源限制由 VNC 服务自身的 IPv4 访问控制实现，Windows 防火墙仍处于关闭状态。

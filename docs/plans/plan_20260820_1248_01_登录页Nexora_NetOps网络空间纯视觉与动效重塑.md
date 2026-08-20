# 实施计划 - 登录页 Nexora NetOps “网络空间 / 自动化控制中心” 纯视觉与动效重塑

## 1. 目标与设计定位
对 Nexora 登录页进行一次纯视觉与动效的高级重塑，不改动任何业务逻辑、表单字段、认证流程与接口，全面打造属于 **Nexora NetOps** 的 **“空间感 / 网络场 / 自动化控制中心（Network Field & Control Hub）”** 视觉语言：
- **设计风格关键词**：Minimal / Spatial / Network Field / Calm Motion / Premium SaaS / Depth / White Space；
- **拒绝“粒子烟花页”与杂乱杂色**：以 Nexora 品牌蓝、青蓝、深紫为主色调，仅点缀极微量琥珀金，构筑富有纵深与留白的网络拓扑微粒场。

---

## 2. 核心重构细节

### 2.1 三维纵深“Network Field”（`ThreeCyberNetwork.tsx`）
1. **三层景深体系（Depth Layers）**：
   - **远景层（Far Field）**：微小尺寸（`0.015 ~ 0.025`）、低透明度（`0.2 ~ 0.35`）、缓慢漂移；
   - **中景层（Mid Field）**：标准微粒胶囊（`0.04 ~ 0.07`）、中透明度（`0.6 ~ 0.8`）、弧形轨迹与网络流动；
   - **近景层（Near Field）**：极少量（~15 颗）、尺寸略大（`0.09 ~ 0.12`）、轻微虚化景深感、漂浮感更灵动；
2. **网络节点与微弱拓扑链路（Node & Link Telemetry）**：
   - 引入极轻量、半透明的动态微细连接线与脉冲光点（Faint Network Lines & Nodes），隐约传达全网设备拓扑与自动化数据流的空间意象，绝不做成刻板杂乱的拓扑图；
3. **克制高级的平滑运动（Calm Motion & Parallax）**：
   - 整体运动周期设为 `16 ~ 22s`，流体柔和流动，避免中心烟花发散爆炸感；
   - 鼠标微视差位移严格限制在 `3 ~ 8px` 之间；
   - 支持 `prefers-reduced-motion` 媒体查询，开启时自动锁定为静止优雅构图。

### 2.2 视觉层级与呼吸感（`LoginScreen.tsx`）
1. **黄金视觉动线**：
   `Nexora 品牌标识` → `开启下一代全网自动化运维 (主视觉核心)` → `设备自动化编排 · 巡检合规审计 · 数字孪生全景感知 (副标题)` → `登录卡片`；
2. **悬浮磨砂白卡（Spatial Glass Card）**：
   - 宽度控制在 `380 ~ 395px`，高透明度白色背景与极轻 backdrop blur；
   - 柔和极淡的悬浮阴影（`shadow-[0_20px_50px_rgba(0,0,0,0.04)]`）；
   - 输入框统一尺寸与圆角，Focus 状态呈现 Nexora 品牌蓝的微光 Focus Ring；
3. **按钮与细节微交互**：
   - 深色主登录按钮：Hover 时轻微增亮、上浮 1px、箭头右移 3px；
   - 顶部系统在线：弱化胶囊边框，绿色状态点采用缓慢呼吸动画；
   - 底部版权：进一步降低对比度（`text-gray-400/70`），提供干净通透的视觉底座。

---

## 3. 拟修改文件清单

1. `src/components/home/ThreeCyberNetwork.tsx`：重构为分层 Network Field 三维空间场（远/中/近景三层、微弱拓扑连接线、微视差与 reduced-motion 支持）；
2. `src/components/LoginScreen.tsx`：精修排版层级、空间留白、悬浮磨砂卡片、输入框与克制按钮交互；
3. `docs/plans/plan_20260820_1248_01_登录页Nexora_NetOps网络空间纯视觉与动效重塑.md`：实施计划归档。

---

## 4. 验证计划
1. **多分辨率验证**：通过 `browser_subagent` 分别在 `1920×1080`、`1680×1050`、`1440×900`、`1366×768` 下走查卡片居中度、垂直呼吸感与零滚动条保证；
2. **动效走查**：验证鼠标视差位移（3~8px）、平缓网络微粒流动、无杂乱杂色；
3. **生产构建检查**：`npm run build` 确保无 TypeScript / CSS 编译问题。

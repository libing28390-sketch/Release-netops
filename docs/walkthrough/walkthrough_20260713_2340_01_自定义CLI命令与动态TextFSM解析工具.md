# 执行结果与验证报告: 自定义 CLI 查看命令与动态 TextFSM 解析工具

本报告记录了对 **CLI 自定义命令动态解析与展示工具** 的开发实现、关键架构及测试验证结果。

## 1. 完成摘要
我们已经成功开发并集成了动态 TextFSM 模板生成器和在线解析沙箱测试工具。现在，系统支持对任意只读网络设备查询命令进行动态匹配，并允许用户自定义要显示的结构化数据列。

---

## 2. 实际修改文件
- **新增**:
  - [textfsm_builder_service.py](file:///d:/netops/netsops-main/backend/services/textfsm_builder_service.py) (通用 CLI 回显分析与 TextFSM 骨架自动生成模块)
  - [test_custom_textfsm_flow.py](file:///d:/netops/netsops-main/backend/tests/test_custom_textfsm_flow.py) (针对 TextFSM 动态解析、自动骨架生成与 API 的单元测试集)
  - [TextFSMDebugger.tsx](file:///d:/netops/netsops-main/src/pages/AutomationExecute/components/TextFSMDebugger.tsx) (前端动态 TextFSM 在线调试器与字段过滤组件)
- **修改**:
  - [textfsm_templates.py](file:///d:/netops/netsops-main/backend/api/textfsm_templates.py) (集成 `/api/textfsm/auto-generate` 智能生成接口并升级在线解析测试路由)
  - [QuickQueryResultOverlay.tsx](file:///d:/netops/netsops-main/src/pages/AutomationExecute/components/QuickQueryResultOverlay.tsx) (在未成功匹配结构化解析的 Raw 回显下加入“调试与创建自定义模板”智能引导 Banner)
  - [index.tsx](file:///d:/netops/netsops-main/src/pages/AutomationExecute/index.tsx) (在自动化执行 Tab 底层挂载 TextFSM 调试器组件，并与主查询执行流程双向联动)

---

## 3. 关键实现说明
1. **智能提取算法**：[textfsm_builder_service.py](file:///d:/netops/netsops-main/backend/services/textfsm_builder_service.py) 能够在零额外规则的情况下，识别设备表格回显的 header（如以连字符/等号为分隔线，或包含 `Port` / `Vlan` / `Interface` 等典型表头字段的行），智能切分列标题并自动重组生成满足 TextFSM 正则解析要求的状态机模版；
2. **完全的在线调试沙箱**：前端抽屉提供实时编辑模板、实时测试设备回显解析的“运行解析”按钮，用户可随意剔除或挑选需要以 Grid 网格展示的数据列，点击“保存并应用”后数据将存盘至 `data/textfsm_templates/` 目录，并在下一次查询命令时自动加载。

---

## 4. 验证命令与结果

### 单元测试验证
运行新编写的动态解析测试用例：
```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_custom_textfsm_flow.py -v
```
**结果**：
```text
backend/tests/test_custom_textfsm_flow.py::test_auto_generate_template_logic PASSED
backend/tests/test_custom_textfsm_flow.py::test_parse_with_template_content PASSED
backend/tests/test_custom_textfsm_flow.py::test_api_endpoints PASSED
========================= 3 passed in 5.49s =========================
```

### 前端 TypeScript 编译与语法检测
运行项目 TypeScript 质量门禁检查：
```powershell
npx tsc --noEmit
```
**结果**：无任何报错与警告，修改完全合规。

---

## 5. 剩余风险与后续建议
- **TextFSM 规则细化**：自动生成的 TextFSM 骨架默认将列正则识别为通配匹配符 `\S+`（非空字符段）。在遇到非常复杂的非结构化回显（如多行拼装或包含空格的字段）时，建议用户使用前端编辑器的测试功能手动修改匹配正则表达式（例如将 `\S+` 调整为 `\d+` 或 `.*`）。

# 华三SNMP模板校准与新增模板SNMPWALK探测增强执行报告

## 1. 完成摘要
针对用户关于内置 SNMP 模板问题以及华三典型型号（`S5008V6`、`S5135S-16T4S`、`S5590-28SX-EI`）OID 准确性核实与新增模板时需要 SNMPWALK 测试的需求，本次已全部完成落地：
1. **官方 OID 核实与精确预置**：依据 H3C Comware 官方 MIB（`HH3C-ENTITY-EXT-MIB` 及 `IF-MIB`）标准规范，为 `S5008V6`、`S5135S-16T4S`、`S5590-28SX-EI` 建立了精确官方预置，并增强了型号智能推断规则。
2. **新增/编辑模板实景 SNMPWALK 探测面板**：在模板编辑器中全新开发了「SNMPWALK 实时探测与抓取」交互面板，支持从在线资产直接联动 SNMP 凭据、提供 9 个常用 OID 快捷按钮、支持自定义 OID 树状 walk，并支持在返回结果中一键将任意 OID 回填至 CPU/内存/温度/风扇/电源/接口等指标项。

---

## 2. 实际修改文件清单

| 文件路径 | 修改类型 | 说明 |
| :--- | :--- | :--- |
| `backend/services/snmp_preset_service.py` | 代码修改 | 新增 `S5008V6`、`S5135S-16T4S`、`S5590-28SX-EI` 预置，并扩充 `match_profile_for_model` 匹配规则 |
| `src/components/SnmpMib/components/LiveWalkInspector.tsx` | 组件重塑 | 新增 SNMPWALK 交互面板、快捷 OID 按钮组、结果表格搜索与一键回填按钮 |
| `src/components/SnmpMib/components/MetricProfileEditor.tsx` | 组件修改 | 接入 SNMPWALK 一键回填回调函数，实现 OID 选择自动同步至表单 |
| `docs/plans/plan_20260821_1959_01_华三SNMP模板校准与Walk实时探测增强.md` | 计划归档 | 任务实施计划与设计依据 |
| `docs/walkthrough/walkthrough_20260821_1959_01_华三SNMP模板校准与Walk实时探测增强.md` | 走查归档 | 执行验证报告 |

---

## 3. 关键实现说明

### 3.1 华三（H3C）核心 OID 契约
- **CPU 利用率**: `1.3.6.1.4.1.25506.2.6.1.1.1.1.6` (`hh3cEntityExtCpuUsage`)
- **内存利用率**: `1.3.6.1.4.1.25506.2.6.1.1.1.1.8` (`hh3cEntityExtMemUsage`)
- **设备温度**: `1.3.6.1.4.1.25506.2.6.1.1.1.1.12` (`hh3cEntityExtTemperature`)
- **风扇状态**: `1.3.6.1.4.1.25506.2.6.1.1.1.1.19` (`hh3cEntityExtErrorStatus`，状态码：正常 `2`，告警 `41,31`，故障 `3,4`)
- **电源状态**: `1.3.6.1.4.1.25506.2.6.1.1.1.1.19` (`hh3cEntityExtErrorStatus`，状态码：正常 `2`，告警 `51`，故障 `3,4`)
- **接口流量与状态**:
  - `ifOperStatus`: `1.3.6.1.2.1.2.2.1.8`
  - `ifHCInOctets` (64位入流量): `1.3.6.1.2.1.31.1.1.1.6`
  - `ifHCOutOctets` (64位出流量): `1.3.6.1.2.1.31.1.1.1.10`
  - `ifHighSpeed` (端口速率): `1.3.6.1.2.1.31.1.1.1.15`

### 3.2 实景 SNMPWALK 探测与一键回填机制
1. **模式平滑切换**：编辑器上方提供「SNMPWALK 实时探测与抓取」和「硬件与接口指标综合验证」双 Tab。
2. **快捷预设**：提供一键填充 H3C 实体扩展根（`1.3.6.1.4.1.25506.2.6.1.1.1`）、CPU（`.6`）、内存（`.8`）、温度（`.12`）、状态（`.19`）等常用 OID。
3. **精准回填**：抓取到的 OID 结果表格每行提供 `[+ CPU]`、`[+ 内存]`、`[+ 温度]`、`[+ 风扇]`、`[+ 电源]` 动作按钮，点击后：
   - 若指标列表中已存在该项，直接更新其 OID；
   - 若尚未添加该指标项，自动追加该指标卡片并填入精确 OID，极大提升模板配置效率。

---

## 4. 验证命令与结果

### 4.1 Python 预置与自动匹配测试
- **测试命令**：
  ```powershell
  python -c "import sys; sys.path.insert(0, 'backend'); from services.snmp_preset_service import match_profile_for_model, list_preset_profiles; presets = list_preset_profiles(); h3c_models = [p['model'] for p in presets if p['vendor'] == 'H3C']; print('H3C Presets:', h3c_models); assert 'S5008V6' in h3c_models; assert 'S5135S-16T4S' in h3c_models; assert 'S5590-28SX-EI' in h3c_models; res1 = match_profile_for_model('H3C', 'S5008V6'); print('Match S5008V6:', res1['preset']['model']); res2 = match_profile_for_model('H3C', 'S5135S-16T4S'); print('Match S5135S:', res2['preset']['model']); res3 = match_profile_for_model('H3C', 'S5590-28SX-EI'); print('Match S5590:', res3['preset']['model']); print('ALL PYTHON CHECKS PASSED!')"
  ```
- **验证结果**：
  ```
  H3C Presets: ['S5008V6', 'S5135S-16T4S', 'S5590-28SX-EI', 'S5500', 'S6800', 'S5130', 'S5560X', 'S6520X']
  Match S5008V6: S5008V6
  Match S5135S: S5135S-16T4S
  Match S5590: S5590-28SX-EI
  ALL PYTHON CHECKS PASSED!
  ```

### 4.2 前端全量生产构建检查
- **构建命令**：
  ```powershell
  npm run build
  ```
- **构建结果**：
  - `✓ built in 17.30s`，0 error，构建顺利产出所有 bundle。

---

## 5. 剩余建议
- 在实际生产网络中，若遇到部分老旧或轻量型交换机返回的实例索引与主控实体不一致，可直接利用新增的 **SNMPWALK 实时探测** 工具抓取特定端口或单板的精确实例后缀并一键回填。

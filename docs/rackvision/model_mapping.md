# RackVision 型号到视觉资产映射

机器映射文件：

- `assets/catalog/model_mapping.json`
- `assets/catalog/model_mapping.yaml`
- `assets/catalog/asset_registry.json`
- `assets/catalog/asset_registry.yaml`

## 解析顺序

```text
model_key 明确绑定
  ↓
exact vendor + exact_model 映射
  ↓
family asset
  ↓
vendor generic form factor
  ↓
global generic form factor/type
  ↓
procedural safe fallback
```

解析结果包含 `resolution_level`、`fidelity`、`asset_available` 和 `asset_render_strategy`。解析失败不会返回空设备：没有 GLB 时使用现有程序化模型，并保持原始 CMDB 设备身份不变。

## 当前目录结果

本次 Excel 构建生成 120 条 exact SKU 映射和 88 个可复用 registry entry。当前生成时仓库中已有 GLB 数量为 0，所以所有 registry entry 为 `draft`，并由程序化模型兜底。这个状态是有意保留的，不能把目录记录当作已完成建模。

## 重新生成

```powershell
$py = 'C:\Users\NINGMEI\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py backend/scripts/build_rackvision_catalog.py `
  --source 'D:\data\downloads\Nexora_3D_Asset_Base_Catalog_v1.xlsx' `
  --output-dir assets/catalog
```

生成器会保存源文件 SHA-256，并保证不覆盖下载目录中的 Excel。


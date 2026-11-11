# 资产与 CMDB 角色类别中文统一

## 完成摘要
“资产与配置”、“CMDB”及“自动化 / 快速操作”页面中设备角色、设备类别相关显示已统一。中文界面字段名统一为“设备角色”“设备类别”，常见英文枚举使用共享映射显示中文。

## 实际修改文件
- 新增 src/domain/deviceLabels.ts，集中维护设备类别和角色名称映射。
- 更新 src/pages/AssetManagement/index.tsx、src/pages/AssetManagement/constants.ts、src/pages/AssetManagement/exportUtils.ts、src/pages/AssetManagement/components/AssetModal.tsx。
- 更新 src/pages/InventoryDevicesTab.tsx、src/pages/InventoryServersTab.tsx、src/pages/inventoryServersExport.ts。
- 更新 src/pages/CmdbAssetManagementTab.tsx、src/pages/CmdbResourceSearchTab.tsx、src/pages/CmdbManagementTab.tsx。
- 更新 src/pages/RackManagement/index.tsx、src/pages/RackManagement/Rack3D/index.tsx、src/pages/RackManagement/components/DraggableDevice.tsx。
- 更新 src/pages/AutomationExecute/index.tsx、src/pages/AutomationExecute/components/DeviceSelectionStep.tsx 中的角色筛选、设备列表和导出。
- 更新 src/components/AssetReadonlyDetail.tsx、src/components/DeviceDetailModal.tsx、src/components/DeviceFormModal.tsx、src/components/DeviceList/DeviceTable.tsx、src/components/DeviceList/deviceExport.ts。
- 调整对应的既有导出和页面断言，不新增测试。

## 关键实现说明
设备类别共用一份中英文标签表，并支持旧分类别名；设备角色通过已有拓扑角色规范化，兼容交换机、服务器及旧式英文角色名称。资产表格、筛选项、表单、详情、机柜视图、自动化设备选择器和导出复用这些标签。自动化树保留原始角色代码用于筛选，只翻译其显示；筛选与保存仍传递原有代码值，未知的自定义值原样保留。

## 验证命令与结果
- npm run lint -- --pretty false：通过（首轮资产/CMDB修改）。
- node node_modules/vite/bin/vite.js build --outDir dist-device-labels-final-20261105：通过（首轮资产/CMDB修改），4360 个模块，约 26 秒。
- git diff --check（本次修改文件）：通过，仅提示少数文件的 LF/CRLF 转换状态。
- 加入自动化快速操作页后，再次运行 npm run lint -- --pretty false：通过。
- 加入自动化快速操作页后，再次运行 Vite 隔离目录生产构建：通过，4360 个模块，约 46 秒。

## 未执行验证及原因
未运行单元测试；本次任务约束未要求运行测试。未做浏览器逐页视觉验收。

## 剩余风险与后续建议
未知的组织自定义角色或类别仍按原值显示，避免猜测其中文含义。如需翻译新的自定义枚举，可补充到共享映射中。

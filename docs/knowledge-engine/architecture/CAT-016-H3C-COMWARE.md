# CAT-016 H3C Comware 产品与版本模型

## 决策

CAT-016 增加 H3C S6520X-EI 的只读审阅样本，并建立 Comware 7 / CMW710 的产品、OS、版本与平台映射。该任务不修改 CAT-001 已冻结的 Huawei/Cisco 首批官方来源 allowlist，也不启用 H3C 外发采集。

## 冻结边界

- 产品身份：`h3c` → `s6520x` → `s6520x_ei` → 精确型号。
- OS 身份：`comware` → `comware7` → `cmw710` → 精确版本。
- 版本样本：`CMW710-R6823`（主版本）、`CMW710-R6820`（兼容版本）、`CMW710-R6817`（候选版本）。
- 网络驱动映射：目录/设备身份使用 `h3c_comware`，Netmiko 与 TextFSM 使用 `hp_comware`；该映射只提供检索/解析提示，不授予写权限。
- H3C 来源状态：`pending_CAT001_additive_extension`。来源 URL 仅作为官方证据，不得在来源注册表及 CAT-004 安全门禁完成前被采集。

未知厂商、未知型号、部分型号前缀、错误版本 scheme 与歧义结果均返回候选/UNKNOWN 并要求人工澄清，禁止根据型号猜测厂商或驱动。V1 文档元数据与设备原始版本字段保持不变，任务不执行生产 DDL。

## 交付物

详见 [CAT-016-H3C-COMWARE.yaml](../catalog/CAT-016-H3C-COMWARE.yaml)、Evidence 与 walkthrough。官方型号与版本依据 H3C S6520X 硬件/软件页面，具体 URL 已固化在契约中。

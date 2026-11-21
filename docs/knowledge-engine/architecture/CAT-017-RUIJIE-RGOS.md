# CAT-017 Ruijie RGOS 产品与 OS 模型

## 决策

CAT-017 增加 Ruijie RG-S6220 系列的只读审阅样本，并建立 RGOS 11 / RGOS 11.0(5) 的产品、OS、版本与平台映射。该任务不修改 CAT-001 已冻结的 Huawei/Cisco 首批官方来源 allowlist，也不启用 Ruijie 外发采集。

## 冻结边界

- 产品身份：`ruijie` → `rg_s6220` → `s6220` → 精确型号。
- OS 身份：`rgos` → `rgos11` → `rgos_11_0_5` → 精确版本。
- 版本样本：`RGOS 11.0(5)B9P59`（主版本）、`RGOS 11.0(5)B3P2`（兼容版本）、`RGOS 11.0(5)B9P27`（候选版本）。
- 网络驱动映射：目录、设备与 TextFSM 使用 `ruijie_rgos`，Netmiko 使用 `ruijie_os`；映射只提供检索/解析提示，不授予写权限。
- Ruijie 来源状态：`pending_CAT001_additive_extension`。来源 URL 仅作为官方证据，不得在来源注册表及 CAT-004 安全门禁完成前被采集。

未知厂商、未知型号、部分型号前缀、错误版本 scheme 与歧义结果均返回候选/UNKNOWN 并要求人工澄清，禁止根据型号猜测厂商或驱动。V1 文档元数据与设备原始版本字段保持不变，任务不执行生产 DDL。

## 交付物

详见 [CAT-017-RUIJIE-RGOS.yaml](../catalog/CAT-017-RUIJIE-RGOS.yaml)、Evidence 与 walkthrough。产品/版本证据来自锐捷官方系列文档、产品页和命令参考页，具体 URL 已固化在契约中。

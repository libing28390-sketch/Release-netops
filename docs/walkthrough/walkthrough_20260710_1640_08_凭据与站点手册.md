# 6. CMDB 基础数据产品使用手册 (CMDB Core)

CMDB 基础数据是 Nexora 网络运维平台的底层数据建模仓库，包含所有不随设备运行状态频繁变化的控制平面基准数据。

## 1. 核心功能概述

本模块包含以下子菜单：
1. **凭据中心 (Credentials)**：多厂商登录凭据（用户名、SSH/Telnet 密码、Enable 密码等）的集中管理库。
2. **站点管理 (Sites)**：物理楼宇、数据中心及边缘分支地理位置的集中配置。
3. **VRF、VLAN 与租户 (VRFs, VLANs, Tenants)**：二层广播域、虚拟三层路由实例以及资源所有者的划归模型。

---

## 2. 详细操作步骤

### 2.1 凭据中心高安全配置
* **安全机制**：所有机密字段使用对称密钥进行加密存储。在向前端展现时，明文不会被传出。
* **录入凭据**：
  ![凭据中心](file:///e:/data/netsops/docs/images/cmdb_credentials.png)
  1. 进入 **CMDB基础数据 -> 凭据中心** 标签。
  2. 点击“添加凭据”，输入凭据名称（如 `Core-SSH-Key`），选择类型（`ssh_password` 或 `ssh_key_file`）。
  3. 输入用户名及密码。如有特权提权，可在此配置“Enable 密码”。
  4. 后台会将该字段传递给 [vault_service.py](file:///e:/data/netsops/backend/services/vault_service.py) 中，如果配置了 `vault_path`，还支持从企业 HashiCorp Vault 服务动态拉取。

### 2.2 物理站点配置
* **定义区域**：
  ![站点管理](file:///e:/data/netsops/docs/images/cmdb_sites.png)
  1. 切换至 **站点管理** 标签。
  2. 点击“添加站点”，输入站点编码（如 `IDC-SH-JQ`）及名称（如 `上海金桥IDC`）。
  3. 这能给资产管理和 IPAM 规划网段前缀提供地理归属标识。

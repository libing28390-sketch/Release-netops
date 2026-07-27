# SNMP 凭据与可选 Server 地址

## 变更目的

凭据中心中的 SNMPv2c 凭据以 Community 为核心认证信息，不再展示 SSH 用户名、密码和 Enable 密码字段。针对存在独立 SNMP 代理、跳转或采集目标地址的场景，新增可选的 `SNMP Server 地址`。

## 行为约定

- `SNMP Community`：SNMPv2c 必填，凭据创建接口和凭据中心前端都会校验。
- `SNMP Server 地址`：选填；留空时使用设备的管理 IP，填写后作为 SNMP 采集目标地址。
- 该地址属于凭据中心记录，绑定该凭据的设备会复用；如果不同设备需要不同 SNMP 目标，应分别建立凭据或留空使用各自管理 IP。
- 设备资产上的 Community 仍可作为回退值；当绑定凭据没有 Community 时，采集器会读取资产上的本地 Community。

## 覆盖范围

SNMP 测试、采集诊断、后台 SNMP 指标采集、设备信息采集和接口采集统一使用 `resolve_collector_credentials` 返回的 SNMP 目标地址、Community 和端口。

数据库通过迁移 `m0039_add_snmp_server_to_credentials` 为既有 `credentials` 表增加 `snmp_server` 字段；空值不会改变既有设备行为。

## 验证

- 后端回归：14 个相关测试通过。
- `npm run lint`：通过。
- `npm run build`：通过；仅保留既有的大包体积提示。

# 华为/华三协议与链路状态 CLI 官方样例第三批

## 覆盖范围

本批次继续按厂商和平台隔离：

| 厂商 | 平台 | 命令 | 结果 |
| --- | --- | --- | --- |
| Huawei | VRP8 | `display bgp peer` | NTC 内置模板 |
| Huawei | VRP8 | `display ospf peer brief` | VRP8 专用模板 |
| Huawei | VRP8 | `display ntp status` | NTC 内置模板 |
| Huawei | VRP8 | `display eth-trunk` | VRP8 专用模板 |
| H3C | Comware7 | `display bgp peer ipv4` | NTC 内置模板 |
| H3C | Comware7 | `display ospf peer` | Comware7 专用模板 |
| H3C | Comware5 | `display ntp-service status` | Comware5 专用模板 |

## 官方来源

- Huawei BGP：<https://support.huawei.com/enterprise/en/doc/EDOC1100313446/5829dca4/bgp-peer-relationship-fails-to-be-established>
- Huawei OSPF：<https://support.huawei.com/enterprise/en/doc/EDOC1100459053/e1fd2273/example-for-configuring-ospf-multi-area-adjacency>
- Huawei NTP：<https://support.huawei.com/enterprise/en/doc/EDOC1100198418/468f431e/ntp-configuration-commands>
- Huawei Eth-Trunk：<https://support.huawei.com/enterprise/en/doc/EDOC1100368579/b7014cbe/eth-trunk-configuration-commands>
- H3C BGP：<https://www.h3c.com/en/d_202410/2284517_294551_0.htm>
- H3C OSPF：<https://www.h3c.com/en/d_200806/607561_294551_0.htm>
- H3C NTP：<https://www.h3c.com/en/d_200707/207798_294551_0.htm>

所有输出都保存在 `backend/tests/fixtures/cli/`，并配套官方来源元数据。Comware5 的样例使用 `hp_comware` 目录和模板前缀，Comware7 使用 `h3c_comware`，避免平台串用。

## 验证

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_textfsm_official_huawei_h3c_protocols.py -q
```

第三批专项测试：7 passed。整个官方样例测试集合继续保持厂商/平台分离，未修改 NTC 内置模板。

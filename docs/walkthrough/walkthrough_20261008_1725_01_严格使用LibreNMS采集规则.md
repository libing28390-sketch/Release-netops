# 严格使用 LibreNMS 采集规则完成记录

## 完成摘要

Comware 硬件发现改为以固定 LibreNMS commit `6c26b4fe4a40f7b392c19c36a44257212736e38c` 的上游规则为依据。打包了官方 Comware OS 类、温度/光功率/电压/电流发现模块、内存和数值换算辅助文件及对应许可证，并在 manifest 中记录每个文件的上游路径、大小和 SHA-256。

Nexora 不再在 LibreNMS 硬件发现路径中运行自定义 H3C DOT11 无线扩展。Comware CPU、内存、机箱温度和光模块传感器按对应上游 PHP 模块的筛选、索引、值换算和阈值规则执行；LibreNMS YAML 中的风扇状态、电源状态和功率继续由通用规则执行。

由于 Nexora 采集服务是 Python，而 Comware OS 与传感器规则由 LibreNMS PHP 代码实现，本次仍保留 Python 执行适配层。它负责发起 SNMP 请求、把上游规则结果映射到 Nexora 指标和轮询计划；规则依据与来源文件保持为固定版本的 LibreNMS 上游代码。本次没有部署 LibreNMS 服务或新增 Docker Compose 服务。

## 关键规则对应

- `LibreNMS/OS/Comware.php`：CPU 只发现非零处理器；内存池只发现 `entPhysicalClass=module` 且使用量大于零的行。`app/Models/Mempool.php` 与 `LibreNMS/Util/Number.php` 定义 `fillUsage`、`fillMissingRatio` 和百分比归一化：总量缺失时百分比单值按 100 单位推导，大于 100 的百分比按十倍缩放规则处理。
- `includes/common.php`：光功率阈值沿用上游 `uw_to_dbm` 的零值、负值和 dBm 换算行为；阈值按上游发现模块四舍五入到两位小数。
- `includes/discovery/sensors/temperature/comware.inc.php`：机箱温度只取 ENTITY-MIB 的 module/sensor 类，过滤温度哨兵值 `65535`，并按上游规则附加有效高温阈值。该文件也定义光模块温度采集。
- `includes/discovery/sensors/dbm/comware.inc.php`、`voltage/comware.inc.php`、`current/comware.inc.php`：光模块指标要求诊断列存在、接口管理状态为 Up、当前值有效，并使用各上游模块的单位与阈值除数。每项传感器的 metadata 指向其具体来源文件和固定 commit。
- Comware YAML 规则继续提供风扇、电源状态和功率发现；未新增 Nexora 自定义 H3C 硬件分类或无线指标。

新增的 `LICENSE.txt` 与上游 PHP 文件版权头一并保留。上游 Comware PHP 文件标注 GPL-3.0-or-later；后续发布包含这些文件或其衍生实现的版本时，应按项目的分发方式审查许可证义务。

## 实际修改文件

- `backend/services/snmp_hardware_probe_service.py`
- `backend/tests/snmp/test_snmp_hardware_probe_service.py`
- `backend/vendor/librenms/README.md`
- `backend/vendor/librenms/source-manifest.json`
- `backend/vendor/librenms/LibreNMS/OS/Comware.php`
- `backend/vendor/librenms/app/Models/Mempool.php`
- `backend/vendor/librenms/LibreNMS/Util/Number.php`
- `backend/vendor/librenms/includes/common.php`
- `backend/vendor/librenms/includes/discovery/sensors/dbm/comware.inc.php`
- `backend/vendor/librenms/includes/discovery/sensors/temperature/comware.inc.php`
- `backend/vendor/librenms/includes/discovery/sensors/voltage/comware.inc.php`
- `backend/vendor/librenms/includes/discovery/sensors/current/comware.inc.php`
- `backend/vendor/librenms/LICENSE.txt`
- `docs/plans/plan_20261008_1725_01_严格使用LibreNMS采集规则.md`
- `docs/walkthrough/walkthrough_20261008_1725_01_严格使用LibreNMS采集规则.md`

## 验证结果

- `.venv\Scripts\python.exe -m pytest backend/tests/snmp/test_snmp_hardware_probe_service.py backend/tests/snmp/test_librenms_rule_service.py backend/tests/monitoring/test_snmp_hardware_poller_service.py -q`：29 passed。
- 硬件探测测试逐一校验 manifest 中五个上游 PHP 文件及 `LICENSE.txt` 的文件大小和 SHA-256。
- 新增用例覆盖 vendor 源文件哈希、CPU 的零值过滤、模块内存推导/百分比归一化、ENTITY 温度类别/哨兵/阈值、光模块端口/诊断/哨兵/单位阈值，以及 WX 设备不再触发 Nexora 专有 H3C 无线硬件输出。
- `git diff --check`：通过。

## 范围和未验证项

- 这次修改限于 LibreNMS 硬件发现路径。独立的 H3C 无线监控模板没有改动；LibreNMS 上游 Comware 硬件规则本身不提供这类无线指标。
- 测试使用固定 SNMP WALK fixture，没有在 AC_11 或其他真实设备上重新采集，也没有部署/重启服务。要在 Grafana 观察新逻辑，需要部署包含本次代码和 vendor 文件的版本并触发设备发现。
- 没有数据库 schema 变更，也没有修改设备配置。

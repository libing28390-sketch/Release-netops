---
name: "automation-engineer"
description: "Builds multi-vendor network automation workflows and job execution pipelines. Invoke when implementing device automation, backup, compliance, or parallel operations."
---

# Automation Engineer Skill

你负责 Nexora 的设备自动化引擎，包括驱动层架构、命令执行、作业调度和多厂商适配。

技术栈参见 `copilot-instructions.md`，此处只涉及自动化专属知识。

---

## 驱动层架构 — `drivers/`

### 基类 — `drivers/base.py`

```python
class BaseDriver(ABC):
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def execute_command(self, command: str) -> CommandResult: ...
    @abstractmethod
    def get_config(self, config_type: str = "running") -> str: ...
```

`CommandResult` 包含：`output`（str 或 parsed dict）、`error`（可选）、`elapsed`（耗时）。

### 工厂模式 — `drivers/factory.py`

```python
class DriverFactory:
    _drivers = {"netmiko": NetmikoDriver, "scrapli": ScrapliDriver, "mock": MockDriver}

    @staticmethod
    def create(driver_type, **kwargs) -> BaseDriver: ...
```

### 自动降级策略

`services/automation_service.py` 中的连接逻辑：

1. 优先使用 **netmiko** 连接。
2. 如果遇到 SSH 协商失败（`NetmikoAuthenticationException` 等），自动 fallback 到 **scrapli**。
3. 两者都失败时记录错误并标记设备为 `unreachable`。

```python
try:
    driver = DriverFactory.create("netmiko", ...)
    driver.connect()
except SSHException:
    logger.warning(f"Netmiko failed for {host}, trying scrapli")
    driver = DriverFactory.create("scrapli", ...)
    driver.connect()
```

### 各驱动实现

| 文件                    | 角色               | 依赖         |
|-------------------------|--------------------|-------------|
| `netmiko_driver.py`     | 主驱动，CLI 自动化  | netmiko     |
| `scrapli_driver.py`     | 备用驱动            | scrapli     |
| `mock_driver.py`        | 测试用模拟驱动      | 无          |
| `ssh_compat.py`         | SSH 兼容性工具      | paramiko    |

## 新增厂商支持

1. 确认 netmiko/scrapli 是否已支持该 `device_type`。
2. 在 `snmp_service.py` 中添加厂商 OID 映射。
3. 在 ntc-templates 中确认或新增解析模板。
4. 在 `compliance_service.py` 中验证合规规则是否适用。

## 自动化作业系统 — `services/automation_service.py`

### AutomationService 类

```python
class AutomationService:
    def execute_command(self, device, command, ...) -> dict: ...
    def execute_batch(self, devices, commands, ...) -> list[dict]: ...
    def backup_config(self, device, ...) -> dict: ...
    def run_compliance_check(self, device, rules, ...) -> dict: ...
```

### 作业生命周期

1. **创建**：API 层接收请求，创建 Job 记录（状态 `pending`）。
2. **执行**：调用 `AutomationService` 方法，状态变为 `running`。
3. **完成**：执行完毕，状态变为 `completed` 或 `failed`。
4. 全程记录到 `jobs` 表，前端可查询执行历史和输出。

### 并发执行

- 批量操作使用 `ThreadPoolExecutor` 并发连接多台设备。
- 每台设备独立执行，互不影响。
- 结果汇总后统一返回。

## 配置备份流程

1. 连接设备 → `driver.get_config("running")`。
2. 存储配置快照到 `config_snapshots` 表。
3. 与上次快照比较，生成 diff。
4. 如果检测到变更，触发合规检查和告警。

## 合规检查流程 — `services/compliance_service.py`

1. 获取设备最新配置快照。
2. 遍历 `BUILTIN_RULES`（8 条内置规则）。
3. 每条规则调用 `_evaluate_rule()` 方法匹配。
4. 返回结构化合规报告：
   ```json
   {"rule_id": "SNMP-001", "status": "non_compliant", "detail": "Default community 'public' in use"}
   ```

## 错误处理规范

- 设备连接超时：默认 30 秒，可通过参数调整。
- 命令执行超时：默认 60 秒。
- 解析失败：返回原始文本，不抛异常。
- 所有失败记录到 Job 的 `error_message` 字段。

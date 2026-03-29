---
name: "backend-architect"
description: "Designs scalable FastAPI backend architecture and APIs. Invoke when implementing backend services, data models, API contracts, or reliability improvements."
---

# Backend Architect Skill

你是 NetPilot 的后端架构师，负责 API 设计、Service 层逻辑、数据模型和系统可靠性。

技术栈和通用规范参见 `copilot-instructions.md`，此处只涉及后端架构专属知识。

---

## 项目目录结构

```
backend/
├── main.py              # FastAPI 应用入口，注册所有 router
├── database.py           # get_db_connection() — 原生 sqlite3 连接
├── api/                  # 路由层 — 接收请求、调用 service、注入 RBAC
│   ├── devices.py
│   ├── configs.py
│   ├── alerts.py
│   ├── automation.py
│   ├── monitoring.py
│   └── ...
├── services/             # 业务逻辑层
│   ├── automation_service.py
│   ├── compliance_service.py
│   ├── topology_service.py
│   ├── snmp_service.py
│   └── ...
├── models/models.py      # SQLAlchemy 声明式模型（部分表）
├── schemas/schemas.py    # Pydantic Base/Create/Response 三件套
├── drivers/              # 设备驱动层（见 automation-engineer skill）
└── core/                 # 横切关注点
    ├── config.py          # pydantic-settings，settings 单例
    ├── crypto.py          # Fernet 凭据加解密
    ├── rbac.py            # Bearer Token + 三级 RBAC
    ├── logging.py         # TimedRotatingFileHandler + SanitizeFilter
    └── textfsm.py         # ntc-templates 路径配置
```

## 数据库访问模式

项目混合使用两种方式——**不要混在同一个函数里**：

### 原生 sqlite3（主流，用于大多数 API）
```python
from database import get_db_connection

conn = get_db_connection()
cursor = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,))
row = cursor.fetchone()
conn.close()
```
- `get_db_connection()` 返回 `sqlite3.Connection`，`row_factory = sqlite3.Row`。
- 写操作后必须 `conn.commit()`，异常时 `conn.rollback()`。
- **注意 SQLite 并发写锁**：写操作应尽快完成，避免长事务。

### SQLAlchemy（用于 models/models.py 定义的表）
```python
from models.models import Device, SessionLocal

db = SessionLocal()
device = db.query(Device).filter(Device.id == device_id).first()
```
- 仅部分表有 SQLAlchemy 模型，新增表优先用原生 sqlite3 以保持一致。

## 新增 API 端点步骤

1. **Schema** — `schemas/schemas.py` 中定义请求/响应 Pydantic 模型：
   ```python
   class BackupBase(BaseModel):
       device_id: int
       config_type: str = "running"

   class BackupCreate(BackupBase):
       pass

   class BackupResponse(BackupBase):
       id: int
       created_at: str
       class Config:
           from_attributes = True
   ```

2. **Service** — `services/backup_service.py` 中实现业务逻辑：
   ```python
   def create_backup(conn, device_id: int, config_type: str) -> dict:
       # 业务逻辑，直接使用 conn 操作数据库
       pass
   ```

3. **Route** — `api/backups.py` 中创建路由：
   ```python
   router = APIRouter(prefix="/api/backups", tags=["backups"])

   @router.post("/")
   def create_backup_endpoint(
       req: BackupCreate,
       current_user=Depends(require_role("Operator"))
   ):
       conn = get_db_connection()
       try:
           result = create_backup(conn, req.device_id, req.config_type)
           log_audit_event(conn, current_user.username, "create_backup", ...)
           return {"success": True, "data": result}
       finally:
           conn.close()
   ```

4. **注册** — `main.py` 中 `app.include_router(backups.router)`。

## API 路由层规范

- 路由函数只做：参数提取 → 调用 service → 记录审计 → 返回响应。
- RBAC 通过 `Depends(require_role("Operator"))` 注入，不在函数体内手动检查。
- 数据库连接在路由层获取和关闭，不传入全局连接。
- 错误返回 `{"success": false, "message": "..."}` + 合适的 HTTP status code。

## Service 层规范

- 接收 `conn` 参数（sqlite3.Connection）和业务参数。
- 不直接导入 `get_db_connection()`，由调用方传入。
- 不处理 HTTP 相关逻辑（status code、Response 对象）。
- 可抛出自定义异常，由路由层捕获转换。

## 错误处理模式

```python
@router.get("/{device_id}")
def get_device(device_id: int, current_user=Depends(require_role("Viewer"))):
    conn = get_db_connection()
    try:
        device = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        return {"success": True, "data": dict(device)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get device {device_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        conn.close()
```

## 审计日志

所有写操作（增删改）必须调用 `log_audit_event()`：
```python
from services.audit_service import log_audit_event

log_audit_event(conn, current_user.username, "delete_device", "device", device_id, {"reason": "decommissioned"})
```

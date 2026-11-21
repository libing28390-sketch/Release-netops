# Actions 发布门禁回归修复

## 目的与问题

修复 GitHub Actions 后端 release gate 中的两个失败：Docker Redis 禁用文案契约不同步，以及 SNMP MIB 自动匹配接口在直接调用时因 FastAPI 查询参数默认值导致 Huawei 模板无法匹配。

## 根因

- `scripts/deploy-docker.sh` 在 `26c7df28` 加入监控服务后，将 Redis 禁用说明更新为 `db/netops/monitoring/nginx`；对应测试仍断言旧文案。
- `ae1ccc20` 为 `auto_match_model_mibs` 增加 `platform` 与 `software_version` 查询参数。测试直接调用 Python 函数时，省略参数会得到 `Query` 对象，而不是空字符串；对象字符串化后被固件范围匹配逻辑误判，导致 Huawei 返回未匹配。

## 方案与文件

- 更新 `backend/tests/release/test_deploy_docker_redis_contract.py` 的严格文案断言，反映当前部署脚本实际覆盖的服务范围。
- 将 `auto_match_model_mibs` 的查询参数改为 `Annotated[..., Query(...)]` 搭配普通空字符串默认值，保留 HTTP 校验并使直接调用与 HTTP 调用语义一致。

## 验证

- `.venv\\Scripts\\python.exe -m pytest backend/tests/release/test_deploy_docker_redis_contract.py -q`：4 passed。
- `.venv\\Scripts\\python.exe -m pytest backend/tests/snmp/test_snmp_mib_repository.py -q`：10 passed in 141.55s。
- 合并聚焦验证：`.venv\\Scripts\\python.exe -m pytest backend/tests/release/test_deploy_docker_redis_contract.py backend/tests/snmp/test_snmp_mib_repository.py`：14 passed in 133.97s。
- 额外验证：省略 `platform`/`software_version` 的四个自动匹配案例均返回 `matched=True`；不支持的 Ruijie/Nexus 案例保持未匹配。
- PostgreSQL-only policy scanner：0 violation。完整后端套件在 Windows 本地运行至约 28% 时出现一个未保留汇总的额外错误后中止；单独复现 `catalog/test_cat003_source_registry.py` 为 5 passed。CI Linux 全量结果仍需由 Actions 确认。

## 未验证项与恢复

完整 Actions 环境尚未在本地复刻；推送后由 GitHub Actions 完成全量 release gate。若需恢复，回退本次提交即可，不涉及数据库迁移或生产数据。

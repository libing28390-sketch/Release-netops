Nexora 四厂商本地知识摘要包
================================

这个目录是一个可重复生成的、本地离线的 Knowledge Engine 候选资料包，覆盖
Huawei、Cisco、H3C、Ruijie 四个厂商。

包内容
------

* 40 篇核心摘要：10 个主题（vlan、access_port、trunk、ospf、bgp、lacp、
  acl、ssh、ntp、static_route）分别覆盖四个厂商。
* 40 篇只读核验/排障伴随摘要：每个厂商的每个核心主题各增加一篇，用于
  检索后续的状态核对、常见异常定位和验证命令补充。
* 10 篇锚点评测补充摘要：VXLAN/EVPN、端口安全、CPU/内存诊断、ARP/MAC、
  HSRP、接口状态、LLDP 等，用于补足 50-anchor 中有明确文章候选的题目。
* manifest.json：文件哈希、来源 URL、厂商/主题矩阵和构建契约。
* source_catalog.yaml：来源治理目录和每篇补充摘要的官方页面映射。
* ../docs/knowledge-engine/eval/eval-local-pack-coverage.json：50-anchor 与
  400-case 的本地候选覆盖报告。

重要边界
--------

* 本包的文章是根据公开厂商官网页面编写的本地摘要，不是官网全文镜像；每篇文章都保留官方 HTTPS 来源 URL。
* 所有来源 URL 都是官方站点；构建脚本不访问外网，构建结果不会把网页变化
  隐式带入包内。
* test_only=true、production_eligible=false、gold_replacement=false 是有意
  保留的环境边界。这个包可以用于本地检索、分块、嵌入和评测联调；它不是官网
  全文镜像，也不能绕过生产部署、来源条款和检索质量门禁。
* 当前共 90 篇摘要。50-anchor 中有 44 个 answer 题；当前 38 个有候选文章映射。其余 6 个是
  需要继续采集或必须先走安全/澄清策略的题目（BFD、AAA/PAM、接口补充以及
  两个高风险操作），空映射是有意的，不是把安全拒答伪装成知识命中。
* 400-case 是 400 条评测用例的覆盖矩阵，不等于需要制作 400 篇文章。当前
  400 数据集采用官方 URL 支撑的自动生成策略，不要求人工评审；每个 answer
  用例必须引用允许域名下的官方来源。自动生成不等同于检索质量已经通过。

校验算法说明
------------

manifest.json 中每篇文章使用 `content_sha256` 和 `content_bytes`，分别校验
ZIP 内文档的精确字节内容和大小；导入器会重新计算 SHA-256 并拒绝不匹配的
文章。不要改成 MD5：MD5 不属于当前导入契约，也不适合作为抗碰撞的完整性校验。
SHA-256 只能证明导入内容没有被意外篡改，不能替代官方 URL 来源验证或检索
质量门禁。

构建与校验
----------

在仓库根目录运行：

    .venv\Scripts\python.exe scripts\build_local_knowledge_pack.py --check-only
    .venv\Scripts\python.exe scripts\build_local_knowledge_pack.py --output %TEMP%\nexora-local-knowledge-4vendor.zip

不带 --check-only 时，脚本会重新生成本目录下的 Markdown、manifest.json 和
覆盖报告。ZIP 使用固定时间戳和排序，便于比较构建结果；它只应作为本地测试
输入，不能把本地摘要包本身当作官网全文或生产发布证据。

当前包没有执行数据库导入，也没有执行 Git push。若要导入本地 PostgreSQL，
应在单独的、明确授权的测试步骤中确认数据库、vector 扩展、嵌入模型和租户
范围后再进行。

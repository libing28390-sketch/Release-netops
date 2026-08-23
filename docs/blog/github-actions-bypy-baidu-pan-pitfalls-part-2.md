# GitHub Actions 上传百度网盘为什么不稳定？我踩过的几个坑

上一篇介绍了 Nexora 如何通过 GitHub Actions 自动完成构建、创建 GitHub Release，并将发布文件同步到百度网盘。

真正开始使用以后，我发现最麻烦的并不是写一个 YAML 文件，而是这一段链路：

~~~
海外 GitHub Actions
        ↓
上传
        ↓
百度网盘
~~~

中间涉及授权文件、Base64 编码、网络超时、分片大小、失败重试和上传状态判断。

这篇就专门记录 bypy 上传过程中比较容易踩坑的几个地方。

## 一、bypy 授权文件到底是什么

首先安装 bypy：

~~~bash
pip install bypy
~~~

第一次执行：

~~~bash
bypy info
~~~

按照提示完成百度账号授权。

授权成功后，本机会生成：

~~~
Windows:
C:\Users\<用户名>\.bypy\bypy.json

Linux / macOS:
~/.bypy/bypy.json
~~~

这个文件不是普通配置文件，里面包含百度网盘授权信息。

因此不能直接提交到 GitHub，也不建议写入 `release.yml`。

还需要注意 bypy 的远程目录规则。代码中写的：

~~~
Nexora_Release/latest/
~~~

通常对应百度网盘 bypy 应用目录下的路径，而不是普通网盘根目录。

## 二、为什么我选择保存 Base64

GitHub Secrets 可以保存敏感内容。

但 `bypy.json` 是一个多行 JSON 文件，直接复制时容易出现格式问题，所以我将它编码成一行 Base64 字符串，再保存到 Secret：

~~~
本地 bypy.json
      ↓
Base64 编码
      ↓
GitHub Secret
      ↓
Actions 运行时解码
      ↓
临时恢复 bypy.json
~~~

Windows PowerShell：

~~~powershell
[Convert]::ToBase64String(
  [IO.File]::ReadAllBytes(
    "$env:USERPROFILE\.bypy\bypy.json"
  )
) | Set-Clipboard
~~~

Linux：

~~~bash
base64 -w 0 ~/.bypy/bypy.json
~~~

macOS：

~~~bash
base64 < ~/.bypy/bypy.json | pbcopy
~~~

这里需要特别说明：

> Base64 只是编码，不是加密。

所以即使保存成 Base64，也必须把它当作敏感凭据处理。

不要在 Actions 日志中输出解码结果，也不要把它写入构建产物。

## 三、运行时恢复凭据

Actions 中通过环境变量读取 Secret：

~~~yaml
env:
  BYPY_CONFIG_B64: ${{ secrets.BYPY_CONFIG_B64 }}
~~~

Python 脚本中可以先尝试解析 JSON，如果失败，再尝试 Base64：

~~~python
import base64
import binascii
import json


def parse_config(raw_input: str) -> dict:
    raw = raw_input.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None

    if not isinstance(data, dict):
        try:
            encoded = "".join(raw.split())
            decoded = base64.b64decode(
                encoded,
                validate=True,
            )
            data = json.loads(
                decoded.decode("utf-8")
            )
        except (
            binascii.Error,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                "BYPY_CONFIG_B64 格式无效"
            ) from exc

    if "access_token" not in data:
        raise ValueError(
            "bypy 配置中缺少 access_token"
        )

    return data
~~~

恢复文件时，建议使用临时目录：

~~~python
import json
import tempfile
from pathlib import Path
from bypy import ByPy


with tempfile.TemporaryDirectory() as temp_dir:
    config_dir = Path(temp_dir) / ".bypy"
    config_dir.mkdir(parents=True)

    token_file = config_dir / "bypy.json"
    token_file.write_text(
        json.dumps(token_data),
        encoding="utf-8",
    )

    client = ByPy(
        configdir=str(config_dir),
        slice_size=500 * 1024 * 1024,
        timeout=600,
        retry=3,
    )
~~~

这样凭据不会长期留在 Runner 的用户目录中。

## 四、分片大小不是越大越好

上传大文件时，bypy 会进行分片处理。

我当前使用过类似这样的参数：

~~~python
slice_size=500 * 1024 * 1024
timeout=600
retry=3
~~~

但这并不是适合所有环境的固定答案。

分片太小，会带来更多请求和校验操作。

分片太大，单个分片失败时，重新上传的成本也更高。

比较合理的做法是根据自己的环境测试：

| 参数 | 作用 |
| --- | --- |
| `slice_size` | 控制单个上传分片的大小 |
| `timeout` | 控制单次网络请求超时时间 |
| `retry` | 控制失败后的重试次数 |

测试时至少记录：

- 文件大小
- 分片大小
- 总上传时间
- 失败次数
- 最终是否成功
- Actions Runner 所在区域

不要直接把“500 MB 分片上传更稳定”写成普遍结论。

更准确的表达应该是：

> 在我的 GitHub Actions 环境中，经过测试后选择了 500 MB 分片；其他环境需要自行调整。

## 五、日志不输出，看起来就像卡死

上传大文件时，如果 Python 输出被缓冲，Actions 日志可能长时间没有新内容。

这时任务可能还在运行，但页面看起来像是卡住了。

可以在工作流中设置：

~~~yaml
env:
  PYTHONUNBUFFERED: '1'
~~~

Python 输出日志时使用：

~~~python
print(
    "[BaiduPan] 开始上传...",
    flush=True,
)
~~~

建议每个文件至少输出：

- 文件名
- 文件大小
- 目标目录
- 开始上传时间
- 上传完成状态
- 返回码

这样排查问题时，不需要猜任务到底停在哪一步。

## 六、上传失败后，Actions 不能继续显示成功

这是我认为最容易忽略的问题。

很多脚本只是打印上传结果：

~~~python
result = client.upload(
    str(local_file),
    remote_dir,
)

print(f"上传状态: {result}")
~~~

但如果不判断返回值，即使百度网盘上传失败，GitHub Actions 仍然可能显示成功。

建议封装一个检查函数：

~~~python
def upload_checked(
    client,
    local_file: Path,
    remote_dir: str,
) -> None:
    result = client.upload(
        str(local_file),
        remote_dir,
    )

    if result != 0:
        raise RuntimeError(
            f"上传失败: {local_file}"
        )
~~~

上传 `latest` 和 `archive` 时都使用这个函数：

~~~python
upload_checked(
    client,
    latest_file,
    "Nexora_Release/latest/",
)

upload_checked(
    client,
    versioned_file,
    f"Nexora_Release/archive/{tag_name}/",
)
~~~

只要其中一个文件失败，整个工作流就应该失败。

否则你可能看到一个绿色的 Actions 状态，但用户下载到的却是旧版本。

## 七、latest 覆盖和重复执行

自动化发布必须考虑重复执行。

例如同一个 Tag 因为网络问题重新运行时，脚本应该能够处理：

- `latest` 文件是否覆盖
- `archive` 文件是否重复
- 同名文件是否跳过
- 失败后是否可以继续上传

不要只依赖默认行为。应该根据当前使用的 bypy 版本，明确设置或验证同名文件的处理方式。

实际发布时，还可以把文件名设计成幂等形式：

~~~
Nexora-Windows-Latest.zip
Nexora-Windows_v1.0.6.zip
~~~

这样同一个版本重复执行时，不会不断产生难以识别的新文件。

## 八、workflow_dispatch 也要谨慎使用

如果工作流只通过 Tag 触发，版本号可以直接读取：

~~~python
tag_name = os.environ.get(
    "GITHUB_REF_NAME",
    "latest",
)
~~~

但如果加入：

~~~yaml
workflow_dispatch:
~~~

手动运行时，`GITHUB_REF_NAME` 可能是当前分支名称，而不是版本号。

这样就可能生成：

~~~
archive/main/
~~~

或者：

~~~
archive/develop/
~~~

如果确实需要手动运行，建议增加输入参数：

~~~yaml
workflow_dispatch:
  inputs:
    release_tag:
      description: Release tag
      required: true
      type: string
~~~

然后让脚本优先读取这个输入值。

如果暂时没有手动发布需求，直接只保留 Tag 触发会更简单。

## 九、依赖版本也要固定

工作流中直接执行：

~~~bash
pip install bypy
~~~

每次安装的可能不是完全相同的版本。

如果后续 bypy 依赖或行为发生变化，之前正常的上传流程可能受到影响。

实际项目中建议在测试通过后固定版本：

~~~bash
python -m pip install bypy==<已验证版本>
~~~

GitHub Actions 使用的 Action 版本也要按照项目的安全策略进行固定和定期升级。

## 十、这套方案的边界

这套方案适合个人项目、小型开源项目和内部工具分发。

但它并不能解决所有下载问题。

百度网盘更适合当作一个国内备用入口，不应该被描述成专业 CDN。

如果项目下载量较大，或者需要稳定的商业分发能力，后续可以考虑：

- 国内对象存储
- CDN 加速
- 自建下载服务
- 多地域镜像
- 文件完整性校验
- 下载统计和失败监控

另外，bypy 属于第三方客户端，百度接口或授权机制发生变化时，上传流程也可能需要调整。

## 十一、最后整理一份检查清单

每次排查上传问题时，我会按下面的顺序检查：

~~~
□ Secret 是否配置正确
□ Base64 是否完整
□ bypy.json 是否能正常解析
□ Runner 是否能连接百度服务
□ 远程目录是否正确
□ 分片和超时时间是否合适
□ 每个上传结果是否检查
□ latest 是否覆盖成功
□ archive 是否生成正确版本目录
□ Actions 最终状态是否真实反映上传结果
~~~

自动化发布不是把命令放进 YAML 就结束了。

真正可靠的流水线，还要能够识别失败、输出日志、保留历史，并且让最终状态可信。

这也是我在 Nexora 发布流程中逐步补上的部分。

## 发布配套

### 摘要

GitHub Actions 上传百度网盘时，真正麻烦的不是安装 bypy，而是授权文件、Base64、分片大小、网络超时和失败状态判断。本文整理了这套流程中最容易踩坑的几个地方。

### 配图建议

1. bypy 授权过程
2. `bypy.json` 文件位置
3. Secret 环境变量配置
4. 上传日志
5. 分片参数代码
6. 上传失败后的错误日志
7. 最终排查清单

### 参考资料

- https://github.com/houtianze/bypy/blob/master/README.md
- https://docs.github.com/en/actions/concepts/security/secrets
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax


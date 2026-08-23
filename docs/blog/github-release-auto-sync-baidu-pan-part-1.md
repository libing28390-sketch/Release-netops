# GitHub Release 下载太慢？我用 GitHub Actions 自动同步到百度网盘

最近给 Nexora 发布版本时，我发现最耗时间的不是构建，而是构建完成后把安装包从 GitHub Actions 下载下来，再手动上传到百度网盘。

版本少的时候还能接受，版本一多，这一步就变成了发布流程中最重复、也最容易出错的环节。

后来我把这部分接入了 GitHub Actions：只要推送一个版本 Tag，流水线就会自动完成构建、打包、创建 GitHub Release，并将同一批产物同步到百度网盘。

百度网盘再按 `latest` 和 `archive` 两个目录管理，官网始终使用固定下载入口，历史版本也可以保留。

本文分享这套方案的整体思路、目录设计和 GitHub Actions 配置。具体的 bypy 授权、分片上传和失败重试问题，放到下一篇详细说明。

> 配图 1：GitHub Release 与百度网盘目录的最终效果

## 一、以前发布一个版本有多麻烦

以前的流程大概是：

~~~
本地修改代码
    ↓
Push 到 GitHub
    ↓
GitHub Actions 构建
    ↓
手动下载构建产物
    ↓
上传百度网盘
    ↓
整理下载地址
    ↓
通知用户
~~~

真正麻烦的不是某一步很难，而是每次发布都要重复做一遍。

而且手动操作还容易出现几个问题：

- 下载错构建产物
- 上传错版本目录
- 文件名不统一
- 忘记更新下载地址
- GitHub Release 和百度网盘文件不一致

所以我后来把目标改成：

> GitHub Release 是正式发布入口，百度网盘作为国内用户的备用下载入口，两边使用同一批构建产物。

## 二、最终实现的发布链路

现在的流程变成：

~~~
git tag v1.0.6
    ↓
git push origin v1.0.6
    ↓
GitHub Actions
    ├── 构建程序
    ├── 生成发布文件
    ├── 创建 GitHub Release
    └── 上传百度网盘
~~~

百度网盘目录采用两个层级：

~~~
Nexora_Release/
├── latest/
│   ├── Nexora-Windows-Latest.zip
│   └── Nexora-Linux-Latest.zip
│
└── archive/
    └── v1.0.6/
        ├── Nexora-Windows_v1.0.6.zip
        └── Nexora-Linux_v1.0.6.zip
~~~

`latest` 用于当前版本下载。

官网、README 或公众号文章可以长期使用固定入口，不需要每次更新版本都修改地址。

`archive` 用于保存历史版本。

如果用户需要旧版本，可以直接进入对应的版本目录。

这里建议保留 GitHub Release，不要把百度网盘作为唯一来源。GitHub Release 仍然是版本和文件的正式记录，百度网盘只是额外增加的国内下载入口。

## 三、GitHub Actions 配置

下面是一个简化版工作流：

~~~yaml
name: Build and Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout source
        uses: actions/checkout@v4

      - name: Build release artifacts
        shell: bash
        run: |
          mkdir -p dist

          # 替换为项目实际的构建命令
          ./scripts/build-release.sh

          # 最终需要在 dist/ 目录生成待发布文件
          ls -lh dist

      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" \
            dist/*.zip \
            --title "$GITHUB_REF_NAME" \
            --generate-notes

      - name: Install bypy
        run: |
          python -m pip install bypy

      - name: Upload to Baidu Netdisk
        env:
          BYPY_CONFIG_B64: ${{ secrets.BYPY_CONFIG_B64 }}
          PYTHONUNBUFFERED: '1'
        run: |
          python .github/scripts/upload_to_baidupan.py
~~~

这里有三个重点。

第一，工作流只监听版本 Tag：

~~~yaml
tags:
  - 'v*'
~~~

普通代码 Push 不会触发发布流程，避免每次提交都上传文件。

第二，`permissions` 需要允许工作流创建 Release：

~~~yaml
permissions:
  contents: write
~~~

第三，构建步骤要替换成项目自己的真实命令。

例如 Nexora 实际发布 Windows 安装包、Linux 压缩包或 Docker 镜像时，就应该在这里完成，而不是简单把源码打成 ZIP。

## 四、为什么还要维护 latest 和 archive

如果每次发布都生成新的版本目录，官网的下载地址会不断变化。

使用 `latest` 后，下载入口可以固定：

~~~
Nexora_Release/latest/Nexora-Windows-Latest.zip
~~~

每次上传新版本时，只需要覆盖 `latest` 目录中的文件。

历史版本则放到：

~~~
Nexora_Release/archive/v1.0.6/
~~~

这样当前版本和历史版本互不影响。

正式发布时，建议同时生成校验文件：

~~~bash
sha256sum dist/*.zip > dist/SHA256SUMS.txt
~~~

然后把校验文件同时上传到 GitHub Release 和百度网盘，方便用户确认下载文件是否完整。

## 五、百度网盘凭据怎么保存

bypy 需要先在本地完成一次百度账号授权：

~~~bash
pip install bypy
bypy info
~~~

授权完成后，本机会生成 `bypy.json` 文件。

然后将这个文件编码后保存到 GitHub Secrets 中。

我建议 Secret 名称使用：

~~~
BYPY_CONFIG_B64
~~~

因为它保存的不是单独的 Token，而是完整的 bypy 配置内容。

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

然后进入：

~~~
GitHub
→ Settings
→ Secrets and variables
→ Actions
→ New repository secret
~~~

把内容保存为：

~~~
BYPY_CONFIG_B64
~~~

不要把 `bypy.json`、Access Token 或 Base64 内容提交到代码仓库。

## 六、发布之后如何确认成功

每次发布完成后，我会检查四个地方：

1. GitHub Actions 是否执行成功
2. GitHub Release 是否包含所有发布文件
3. 百度网盘 `latest` 目录是否更新
4. 百度网盘 `archive/版本号` 是否生成

如果条件允许，还应该实际下载一次文件，并校验 SHA256。

因为“上传步骤执行完成”不等于“用户一定可以正常下载”。

## 七、这套方案适合什么场景

这套方式比较适合：

- 开源项目发布
- 个人开发工具分发
- 网络运维工具更新
- 需要同时维护海外和国内下载入口的项目
- 不想每次手动搬运构建产物的团队

如果下载量很大，或者项目需要稳定的商业分发能力，后续可以考虑国内对象存储、CDN 或自建下载服务。

百度网盘更适合作为一个方便的备用入口，而不是完整的商业分发基础设施。

## 最后

自动化发布真正节省的，不只是上传文件的几分钟。

更重要的是，把原来依赖个人记忆的发布流程，变成一套可以重复执行、可以检查、可以继续扩展的流水线。

后续我会继续介绍这套方案中最麻烦的一部分：

> GitHub Actions 在海外环境上传百度网盘时，为什么容易遇到失败、重试和凭据问题。

完整的工作流和脚本可以放在 Nexora 项目仓库中：

https://github.com/libing28390-sketch/Release-netops

## 发布配套

### 摘要

GitHub Release 对国内用户下载不太友好怎么办？我把百度网盘同步接入 GitHub Actions，只需推送一个 Tag，就能自动完成构建、Release 和国内镜像分发。

### 配图建议

1. GitHub Release 与百度网盘最终目录，作为首图
2. Tag 到 Release、百度网盘的流程图
3. GitHub Actions 工作流配置
4. `latest/archive` 目录结构
5. GitHub Secret 配置，敏感内容打码
6. 发布成功后的 Actions 日志

### 下一篇预告

下一篇专门讲 bypy 授权、Base64、分片大小、网络超时和上传失败状态判断。

### 参考资料

- https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- https://docs.github.com/en/actions/concepts/security/secrets
- https://github.com/houtianze/bypy/blob/master/README.md


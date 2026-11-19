<p align="center">
  <img src="https://stellio-app.com/assets/logo-nom-stellio.png" alt="Stellio 徽标" width="360">
</p>

<h3 align="center">Stellio 官方插件目录</h3>

<p align="center">
  <a href="https://github.com/stellio-app/stellio-plugins/actions"><img src="https://img.shields.io/github/actions/workflow/status/stellio-app/stellio-plugins/validate.yml?label=catalog" alt="Catalog check"></a>
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://github.com/stellio-app/stellio"><img src="https://img.shields.io/badge/for-Stellio-blueviolet.svg" alt="For Stellio"></a>
  <a href="https://github.com/stellio-app/stellio-plugins/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

<p align="center">
  <a href="../../README.md">🇬🇧 English</a> |
  <a href="README_fr.md">🇫🇷 Français</a> |
  <a href="README_de.md">🇩🇪 Deutsch</a> |
  <a href="README_es.md">🇪🇸 Español</a> |
  <a href="README_it.md">🇮🇹 Italiano</a> |
  <a href="README_pt.md">🇵🇹 Português</a> |
  <a href="README_zh.md">🇨🇳 中文</a> |
  <a href="README_ja.md">🇯🇵 日本語</a>
</p>

<p align="center">插件用于扩展 <a href="https://github.com/stellio-app/stellio">Stellio</a>——面向创客和 3D 打印机用户的 3D 文件管理器。本仓库保存在 <b>工具 › 插件</b> 中显示的公共列表。</p>

<p align="center">
  <a href="https://stellio-app.com/docs/"><b>📖 Documentation</b></a> &nbsp;·&nbsp; <a href="https://demo.stellio-app.com"><b>▶ Demo</b></a>
</p>

<p align="center"><a href="#-简介">📦 简介</a> &nbsp;·&nbsp; <a href="#-安装插件">🚀 安装插件</a> &nbsp;·&nbsp; <a href="#-提交您的插件">🧩 提交您的插件</a> &nbsp;·&nbsp; <a href="#-审核规则">✅ 审核规则</a> &nbsp;·&nbsp; <a href="#-安全">🔒 安全</a> &nbsp;·&nbsp; <a href="#-资源">🔗 资源</a> &nbsp;·&nbsp; <a href="#-许可证">📜 许可证</a></p>

---

## 📦 简介

**插件**是一个小型 Python 程序，用于响应 Stellio 的事件（打印完成、打印失败、订单逾期、打印机过载）：发送通知、写入电子表格、打开灯、导出指标……

插件由**作者托管在 GitHub 上**。本仓库只包含 [`catalog.json`](../../catalog.json)：每个插件的名称、描述、徽标，以及指向发布压缩包的链接和其 SHA-256 校验和。Stellio 读取此文件，并在 **工具 › 插件** 中以卡片（徽标 + 描述）形式显示。

## 🚀 安装插件

1. 在 Stellio 中打开 **工具 › 插件**（仅限所有者账户）。
2. 浏览目录并点击 **安装**：Stellio 会下载压缩包并校验其 SHA-256 校验和。
3. 阅读所请求的**权限**并予以接受。插件安装后处于**停用**状态。
4. 启用后点击 **测试**，用测试事件运行它。运行日志会显示输出。

## 🧩 提交您的插件

1. 创建并发布您的插件（参见 [Stellio 文档](https://stellio-app.com/docs/)中的**插件**页面）：带有 `.zip` 压缩包的 GitHub release。
2. Fork 本仓库，并在 [`catalog.json`](../../catalog.json) 中添加一个条目：

```json
{
  "id": "my-plugin",
  "name": "My plugin",
  "version": "1.0.0",
  "description": {"fr": "…", "en": "…"},
  "author": "Your name",
  "url": "https://github.com/you/my-plugin/releases/download/v1.0.0/my-plugin-1.0.0.zip",
  "sha256": "<sha256sum of the archive>",
  "permissions": ["events"],
  "logo": "https://raw.githubusercontent.com/you/my-plugin/main/logo.png",
  "homepage": "https://github.com/you/my-plugin"
}
```

3. 在本地检查：`python validate_catalog.py catalog.json`。
4. 提交 **Pull Request**。GitHub Action 会重新执行检查（链接、SHA-256、与 `plugin.json` 的一致性、徽标），随后 Stellio 团队审阅插件。

| 字段 | 规则 |
|---|---|
| `description` | 简短（约 140 个字符）；纯文本，或每种语言一段文本（`fr`、`en`、`de`、`es`、`pt`、`it`、`zh`、`ja`） |
| `url` | 指向 `.zip` 压缩包的 `https` 直链（最大 2 MB） |
| `sha256` | 压缩包的校验和；必须完全一致 |
| `logo` | `https`，PNG、JPEG 或 WebP，最大 200 KB，建议 128 × 128（不接受 SVG） |
| `homepage` | 指向插件页面的 `https` 链接（可选） |
| `permissions` | 必须与插件 `plugin.json` 中的权限一致 |

**更新**：发布新的 release，然后提交修改 `version`、`url` 和 `sha256` 的 Pull Request。[`template/`](../../template) 文件夹提供了一个最小插件作为起点。

## ✅ 审核规则

- 代码可读、不混淆；公开仓库，包含许可证和 README。
- 仅申请严格必要的权限，并在插件的 README 中说明。
- 不得隐蔽收集数据，不得在运行时下载代码。
- 名称、描述和徽标不得误导用户，也不得仿冒其他项目或品牌。

## 🔒 安全

插件**不在沙箱中运行**：它以 Stellio 在本机上的权限执行。审核可以降低风险，但不能消除风险：启用插件前请阅读代码和权限。插件安装后处于停用状态，下载只通过 `https`，且必须提供 SHA-256 校验和。

如需反馈已收录插件的问题，请在本仓库中提交 issue。

## 🔗 资源

- 📖 [Stellio 文档](https://stellio-app.com/docs/) – **插件**页面说明如何创建和发布插件
- 🧩 [Stellio](https://github.com/stellio-app/stellio) – 应用程序
- 🧪 [`template/`](../../template) – 可复制的最小插件

## 📜 许可证

本仓库的工具以 **MIT 许可证**发布 – 见 [LICENSE](../../LICENSE)。每个插件保持其作者选择的许可证。

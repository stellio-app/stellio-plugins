<p align="center">
  <img src="https://stellio-app.com/assets/logo-nom-stellio.png" alt="Stellio Logo" width="360">
</p>

<h3 align="center">The official plugin catalog for Stellio</h3>

<p align="center">
  <a href="https://github.com/stellio-app/stellio-plugins/actions"><img src="https://img.shields.io/github/actions/workflow/status/stellio-app/stellio-plugins/validate.yml?label=catalog" alt="Catalog check"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL%20v3-blue.svg" alt="License: AGPL v3"></a>
  <a href="https://github.com/stellio-app/stellio"><img src="https://img.shields.io/badge/for-Stellio-blueviolet.svg" alt="For Stellio"></a>
  <a href="https://github.com/stellio-app/stellio-plugins/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
</p>

<p align="center">
  <a href="README.md">🇬🇧 English</a> |
  <a href="docs/readme/README_fr.md">🇫🇷 Français</a> |
  <a href="docs/readme/README_de.md">🇩🇪 Deutsch</a> |
  <a href="docs/readme/README_es.md">🇪🇸 Español</a> |
  <a href="docs/readme/README_it.md">🇮🇹 Italiano</a> |
  <a href="docs/readme/README_pt.md">🇵🇹 Português</a> |
  <a href="docs/readme/README_zh.md">🇨🇳 中文</a> |
  <a href="docs/readme/README_ja.md">🇯🇵 日本語</a>
</p>

<p align="center">Plugins extend <a href="https://github.com/stellio-app/stellio">Stellio</a>, the 3D file manager for makers and 3D printer owners. This repository holds the public list shown in <b>Plugins › Catalog</b>.</p>

<p align="center">
  <a href="https://stellio-app.com/docs/"><b>📖 Documentation</b></a> &nbsp;·&nbsp; <a href="https://demo.stellio-app.com"><b>▶ Demo</b></a>
</p>

<p align="center"><a href="#-about">📦 About</a> &nbsp;·&nbsp; <a href="#-install-a-plugin">🚀 Install a plugin</a> &nbsp;·&nbsp; <a href="#-submit-your-plugin">🧩 Submit your plugin</a> &nbsp;·&nbsp; <a href="#-review-rules">✅ Review rules</a> &nbsp;·&nbsp; <a href="#-security">🔒 Security</a> &nbsp;·&nbsp; <a href="#-resources">🔗 Resources</a> &nbsp;·&nbsp; <a href="#-license">📜 License</a></p>

---

## 📦 About

A **plugin** is a small Python program that reacts to a Stellio event (print finished, print failed, order late, printer overload): send a notification, write to a spreadsheet, switch on a lamp, export metrics…

Plugins are **hosted by their authors on GitHub**. This repository only contains [`catalog.json`](catalog.json): for each plugin, a name, a description, a logo and a link to a release archive with its SHA-256 checksum. Stellio reads this file and shows it as cards (logo + description) in **Plugins › Catalog**.

## 🚀 Install a plugin

1. In Stellio, open **Plugins › Catalog** (owner account only).
2. Browse the catalog and click **Install**: Stellio downloads the archive and checks its SHA-256 checksum.
3. Read the **permissions** requested and accept them. The plugin is installed **disabled**.
4. Enable it, then click **Test** to run it with a test event. The run log shows the output.

## 🧩 Submit your plugin

1. Create and publish your plugin (see the **Plugins** page of the [Stellio documentation](https://stellio-app.com/docs/)): a GitHub release with a `.zip` archive.
2. Fork this repository and add an entry to [`catalog.json`](catalog.json):

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

3. Check it locally: `python validate_catalog.py catalog.json`.
4. Open a **Pull Request**. A GitHub Action replays the checks (links, SHA-256, consistency with `plugin.json`, logo), then the Stellio team reviews the plugin.

| Field | Rule |
|---|---|
| `description` | Short (about 140 characters); plain text or one text per language (`fr`, `en`, `de`, `es`, `pt`, `it`, `zh`, `ja`) |
| `url` | Direct `https` link to the `.zip` archive (2 MB maximum) |
| `sha256` | Checksum of the archive; must match exactly |
| `logo` | `https`, PNG, JPEG or WebP, 200 KB maximum, ideally 128 × 128 (SVG is refused) |
| `homepage` | `https` link to the plugin page (optional) |
| `permissions` | Must match those of the plugin's `plugin.json` |

**Updating**: publish a new release, then open a Pull Request that changes `version`, `url` and `sha256`. A `template/` folder provides a minimal plugin to start from.

## ✅ Review rules

- Readable code, no obfuscation; public repository with a license and a README.
- Only the permissions that are strictly necessary, explained in the plugin's README.
- No hidden data collection, no code downloaded at run time.
- Name, description and logo must not mislead or imitate another project or brand.

## 🔒 Security

A plugin is **not sandboxed**: it runs with Stellio's rights on the machine. Review reduces the risk, it does not remove it: read the code and the permissions before enabling a plugin. Plugins are installed disabled, downloads only go over `https`, and the SHA-256 checksum is mandatory.

To report a problem with a listed plugin, open an issue in this repository.

## 🔗 Resources

- 📖 [Stellio documentation](https://stellio-app.com/docs/) – the **Plugins** page explains how to create and publish a plugin
- 🧩 [Stellio](https://github.com/stellio-app/stellio) – the application
- 🧪 [`template/`](template) – minimal plugin to copy

## 📜 License

The code of this repository – tooling and the plugins it contains (such as the G-code viewer) – is released under the **GNU AGPL v3** – see [LICENSE](LICENSE). Plugins submitted by third parties listed in the catalog remain under the license chosen by their author.

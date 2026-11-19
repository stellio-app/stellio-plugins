<p align="center">
  <img src="https://stellio-app.com/assets/logo-nom-stellio.png" alt="Stellio ロゴ" width="360">
</p>

<h3 align="center">Stellio 公式プラグインカタログ</h3>

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

<p align="center">プラグインは、メーカーや 3D プリンター所有者向けの 3D ファイル管理ツール <a href="https://github.com/stellio-app/stellio">Stellio</a> を拡張します。このリポジトリには、<b>ツール › プラグイン</b> に表示される公開リストがあります。</p>

<p align="center">
  <a href="https://stellio-app.com/docs/"><b>📖 Documentation</b></a> &nbsp;·&nbsp; <a href="https://demo.stellio-app.com"><b>▶ Demo</b></a>
</p>

<p align="center"><a href="#-概要">📦 概要</a> &nbsp;·&nbsp; <a href="#-プラグインのインストール">🚀 プラグインのインストール</a> &nbsp;·&nbsp; <a href="#-プラグインの提出">🧩 プラグインの提出</a> &nbsp;·&nbsp; <a href="#-レビュー規則">✅ レビュー規則</a> &nbsp;·&nbsp; <a href="#-セキュリティ">🔒 セキュリティ</a> &nbsp;·&nbsp; <a href="#-リソース">🔗 リソース</a> &nbsp;·&nbsp; <a href="#-ライセンス">📜 ライセンス</a></p>

---

## 📦 概要

**プラグイン**は、Stellio のイベント（印刷完了、印刷失敗、注文の遅延、プリンターの過負荷）に反応する小さな Python プログラムです。通知の送信、スプレッドシートへの書き込み、ランプの点灯、メトリクスのエクスポートなどに使えます。

プラグインは**作者が GitHub でホスト**します。このリポジトリには [`catalog.json`](../../catalog.json) だけがあり、各プラグインの名前、説明、ロゴ、リリースアーカイブへのリンクとその SHA-256 チェックサムを記載します。Stellio はこのファイルを読み込み、**ツール › プラグイン** にカード（ロゴ + 説明）として表示します。

## 🚀 プラグインのインストール

1. Stellio で **ツール › プラグイン** を開きます（オーナーアカウントのみ）。
2. カタログを見て **インストール** をクリックします。Stellio がアーカイブをダウンロードし、SHA-256 チェックサムを検証します。
3. 要求された**権限**を読み、承認します。プラグインは**無効**の状態でインストールされます。
4. 有効にして **テスト** をクリックすると、テストイベントで実行されます。実行ログに出力が表示されます。

## 🧩 プラグインの提出

1. プラグインを作成して公開します（[Stellio ドキュメント](https://stellio-app.com/docs/)の**プラグイン**ページを参照）。`.zip` アーカイブ付きの GitHub release を用意します。
2. このリポジトリをフォークし、[`catalog.json`](../../catalog.json) にエントリを追加します。

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

3. ローカルで確認します：`python validate_catalog.py catalog.json`。
4. **Pull Request** を開きます。GitHub Action がチェック（リンク、SHA-256、`plugin.json` との整合性、ロゴ）を再実行し、その後 Stellio チームがプラグインをレビューします。

| フィールド | ルール |
|---|---|
| `description` | 短く（約 140 文字）。単一のテキスト、または言語ごとのテキスト（`fr`、`en`、`de`、`es`、`pt`、`it`、`zh`、`ja`） |
| `url` | `.zip` アーカイブへの `https` 直接リンク（最大 2 MB） |
| `sha256` | アーカイブのチェックサム。完全に一致する必要があります |
| `logo` | `https`、PNG・JPEG・WebP、最大 200 KB、理想は 128 × 128（SVG は不可） |
| `homepage` | プラグインのページへの `https` リンク（任意） |
| `permissions` | プラグインの `plugin.json` の権限と一致させる |

**更新**：新しい release を公開し、`version`、`url`、`sha256` を変更する Pull Request を開きます。[`template/`](../../template) フォルダーに、出発点となる最小のプラグインがあります。

## ✅ レビュー規則

- 読みやすく難読化されていないコード。ライセンスと README を備えた公開リポジトリ。
- 本当に必要な権限だけを要求し、プラグインの README で説明すること。
- 隠れたデータ収集や、実行時のコードのダウンロードをしないこと。
- 名前、説明、ロゴは、誤解を招いたり他のプロジェクトやブランドを模倣したりしないこと。

## 🔒 セキュリティ

プラグインは**サンドボックスで隔離されません**。マシン上で Stellio の権限で実行されます。レビューはリスクを減らしますが、なくすものではありません。プラグインを有効にする前に、コードと権限を確認してください。プラグインは無効の状態でインストールされ、ダウンロードは `https` のみ、SHA-256 チェックサムは必須です。

掲載済みプラグインの問題を報告するには、このリポジトリで issue を作成してください。

## 🔗 リソース

- 📖 [Stellio ドキュメント](https://stellio-app.com/docs/) – **プラグイン**ページで作成と公開の方法を説明しています
- 🧩 [Stellio](https://github.com/stellio-app/stellio) – アプリケーション本体
- 🧪 [`template/`](../../template) – コピーして使える最小のプラグイン

## 📜 ライセンス

このリポジトリのツールは **MIT ライセンス**で公開されています – [LICENSE](../../LICENSE) を参照してください。各プラグインは作者が選んだライセンスのままです。

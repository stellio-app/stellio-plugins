<p align="center">
  <img src="https://stellio-app.com/assets/logo-nom-stellio.png" alt="Stellio-Logo" width="360">
</p>

<h3 align="center">Der offizielle Plugin-Katalog für Stellio</h3>

<p align="center">
  <a href="https://github.com/stellio-app/stellio-plugins/actions"><img src="https://img.shields.io/github/actions/workflow/status/stellio-app/stellio-plugins/validate.yml?label=catalog" alt="Catalog check"></a>
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/License-AGPL%20v3-blue.svg" alt="License: AGPL v3"></a>
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

<p align="center">Plugins erweitern <a href="https://github.com/stellio-app/stellio">Stellio</a>, den 3D-Dateimanager für Maker und 3D-Drucker-Besitzer. Dieses Repository enthält die öffentliche Liste, die unter <b>Plugins › Katalog</b> angezeigt wird.</p>

<p align="center">
  <a href="https://stellio-app.com/docs/"><b>📖 Documentation</b></a> &nbsp;·&nbsp; <a href="https://demo.stellio-app.com"><b>▶ Demo</b></a>
</p>

<p align="center"><a href="#-überblick">📦 Überblick</a> &nbsp;·&nbsp; <a href="#-plugin-installieren">🚀 Plugin installieren</a> &nbsp;·&nbsp; <a href="#-plugin-einreichen">🧩 Plugin einreichen</a> &nbsp;·&nbsp; <a href="#-prüfregeln">✅ Prüfregeln</a> &nbsp;·&nbsp; <a href="#-sicherheit">🔒 Sicherheit</a> &nbsp;·&nbsp; <a href="#-ressourcen">🔗 Ressourcen</a> &nbsp;·&nbsp; <a href="#-lizenz">📜 Lizenz</a></p>

---

## 📦 Überblick

Ein **Plugin** ist ein kleines Python-Programm, das auf ein Stellio-Ereignis reagiert (Druck beendet, Druck fehlgeschlagen, Auftrag verspätet, Drucker überlastet): eine Benachrichtigung senden, in eine Tabelle schreiben, eine Lampe einschalten, Metriken exportieren …

Plugins werden **von ihren Autoren auf GitHub gehostet**. Dieses Repository enthält nur [`catalog.json`](../../catalog.json): zu jedem Plugin einen Namen, eine Beschreibung, ein Logo und einen Link zu einem Release-Archiv samt SHA-256-Prüfsumme. Stellio liest diese Datei und zeigt sie als Karten (Logo + Beschreibung) unter **Plugins › Katalog** an.

## 🚀 Plugin installieren

1. Öffnen Sie in Stellio **Plugins › Katalog** (nur Besitzerkonto).
2. Durchsuchen Sie den Katalog und klicken Sie auf **Installieren**: Stellio lädt das Archiv herunter und prüft seine SHA-256-Prüfsumme.
3. Lesen Sie die angeforderten **Berechtigungen** und akzeptieren Sie sie. Das Plugin wird **deaktiviert** installiert.
4. Aktivieren Sie es und klicken Sie auf **Test**, um es mit einem Testereignis auszuführen. Das Ausführungsprotokoll zeigt die Ausgabe.

## 🧩 Plugin einreichen

1. Erstellen und veröffentlichen Sie Ihr Plugin (siehe die Seite **Plugins** der [Stellio-Dokumentation](https://stellio-app.com/docs/)): ein GitHub-Release mit einem `.zip`-Archiv.
2. Forken Sie dieses Repository und fügen Sie einen Eintrag in [`catalog.json`](../../catalog.json) hinzu:

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

3. Prüfen Sie lokal: `python validate_catalog.py catalog.json`.
4. Öffnen Sie einen **Pull Request**. Eine GitHub Action wiederholt die Prüfungen (Links, SHA-256, Übereinstimmung mit `plugin.json`, Logo), danach prüft das Stellio-Team das Plugin.

| Feld | Regel |
|---|---|
| `description` | Kurz (etwa 140 Zeichen); einfacher Text oder ein Text pro Sprache (`fr`, `en`, `de`, `es`, `pt`, `it`, `zh`, `ja`) |
| `url` | Direkter `https`-Link zum `.zip`-Archiv (höchstens 2 MB) |
| `sha256` | Prüfsumme des Archivs; muss exakt übereinstimmen |
| `logo` | `https`, PNG, JPEG oder WebP, höchstens 200 KB, idealerweise 128 × 128 (SVG wird abgelehnt) |
| `homepage` | `https`-Link zur Plugin-Seite (optional) |
| `permissions` | Müssen mit der `plugin.json` des Plugins übereinstimmen |

**Aktualisieren**: Veröffentlichen Sie ein neues Release und öffnen Sie dann einen Pull Request, der `version`, `url` und `sha256` ändert. Der Ordner [`template/`](../../template) enthält ein minimales Plugin als Ausgangspunkt.

## ✅ Prüfregeln

- Lesbarer Code ohne Verschleierung; öffentliches Repository mit Lizenz und README.
- Nur die unbedingt nötigen Berechtigungen, im README des Plugins erklärt.
- Keine versteckte Datenerfassung, kein zur Laufzeit nachgeladener Code.
- Name, Beschreibung und Logo dürfen nicht täuschen oder ein anderes Projekt bzw. eine andere Marke nachahmen.

## 🔒 Sicherheit

Ein Plugin läuft **nicht in einer Sandbox**: Es wird mit den Rechten von Stellio auf dem Rechner ausgeführt. Die Prüfung verringert das Risiko, beseitigt es aber nicht: Lesen Sie Code und Berechtigungen, bevor Sie ein Plugin aktivieren. Plugins werden deaktiviert installiert, Downloads erfolgen nur über `https`, und die SHA-256-Prüfsumme ist Pflicht.

Um ein Problem mit einem gelisteten Plugin zu melden, öffnen Sie ein Issue in diesem Repository.

## 🔗 Ressourcen

- 📖 [Stellio-Dokumentation](https://stellio-app.com/docs/) – die Seite **Plugins** erklärt, wie man ein Plugin erstellt und veröffentlicht
- 🧩 [Stellio](https://github.com/stellio-app/stellio) – die Anwendung
- 🧪 [`template/`](../../template) – minimales Plugin zum Kopieren

## 📜 Lizenz

Der Code dieses Repositorys – Werkzeuge und enthaltene Plugins (z. B. der G-Code-Viewer) – steht unter der **GNU AGPL v3** – siehe [LICENSE](../../LICENSE). Im Katalog gelistete Plugins Dritter bleiben unter der vom Autor gewählten Lizenz.

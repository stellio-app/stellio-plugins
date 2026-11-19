<p align="center">
  <img src="https://stellio-app.com/assets/logo-nom-stellio.png" alt="Logo di Stellio" width="360">
</p>

<h3 align="center">Il catalogo ufficiale dei plugin di Stellio</h3>

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

<p align="center">I plugin estendono <a href="https://github.com/stellio-app/stellio">Stellio</a>, il gestore di file 3D per maker e proprietari di stampanti 3D. Questo repository contiene l'elenco pubblico mostrato in <b>Strumenti › Plugin</b>.</p>

<p align="center">
  <a href="https://stellio-app.com/docs/"><b>📖 Documentation</b></a> &nbsp;·&nbsp; <a href="https://demo.stellio-app.com"><b>▶ Demo</b></a>
</p>

<p align="center"><a href="#-presentazione">📦 Presentazione</a> &nbsp;·&nbsp; <a href="#-installare-un-plugin">🚀 Installare un plugin</a> &nbsp;·&nbsp; <a href="#-proporre-il-vostro-plugin">🧩 Proporre il vostro plugin</a> &nbsp;·&nbsp; <a href="#-regole-di-revisione">✅ Regole di revisione</a> &nbsp;·&nbsp; <a href="#-sicurezza">🔒 Sicurezza</a> &nbsp;·&nbsp; <a href="#-risorse">🔗 Risorse</a> &nbsp;·&nbsp; <a href="#-licenza">📜 Licenza</a></p>

---

## 📦 Presentazione

Un **plugin** è un piccolo programma Python che reagisce a un evento di Stellio (stampa terminata, stampa fallita, ordine in ritardo, stampante in sovraccarico): inviare una notifica, scrivere in un foglio di calcolo, accendere una luce, esportare metriche…

I plugin sono **ospitati dai loro autori su GitHub**. Questo repository contiene solo [`catalog.json`](../../catalog.json): per ogni plugin, un nome, una descrizione, un logo e un link a un archivio di release con la sua somma SHA-256. Stellio legge questo file e lo mostra come schede (logo + descrizione) in **Strumenti › Plugin**.

## 🚀 Installare un plugin

1. In Stellio, aprite **Strumenti › Plugin** (solo account proprietario).
2. Sfogliate il catalogo e fate clic su **Installa**: Stellio scarica l'archivio e verifica la somma SHA-256.
3. Leggete i **permessi** richiesti e accettateli. Il plugin viene installato **disattivato**.
4. Attivatelo e fate clic su **Prova** per avviarlo con un evento di test. Il registro delle esecuzioni mostra l'output.

## 🧩 Proporre il vostro plugin

1. Create e pubblicate il vostro plugin (vedi la pagina **Plugin** della [documentazione di Stellio](https://stellio-app.com/docs/)): una release GitHub con un archivio `.zip`.
2. Fate il fork di questo repository e aggiungete una voce in [`catalog.json`](../../catalog.json):

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

3. Verificate in locale: `python validate_catalog.py catalog.json`.
4. Aprite una **Pull Request**. Una GitHub Action ripete i controlli (link, SHA-256, coerenza con `plugin.json`, logo), poi il team di Stellio rivede il plugin.

| Campo | Regola |
|---|---|
| `description` | Breve (circa 140 caratteri); testo semplice o un testo per lingua (`fr`, `en`, `de`, `es`, `pt`, `it`, `zh`, `ja`) |
| `url` | Link `https` diretto all'archivio `.zip` (massimo 2 MB) |
| `sha256` | Somma dell'archivio; deve coincidere esattamente |
| `logo` | `https`, PNG, JPEG o WebP, massimo 200 KB, idealmente 128 × 128 (l'SVG è rifiutato) |
| `homepage` | Link `https` alla pagina del plugin (facoltativo) |
| `permissions` | Devono corrispondere a quelli del `plugin.json` del plugin |

**Aggiornare**: pubblicate una nuova release, poi aprite una Pull Request che modifichi `version`, `url` e `sha256`. La cartella [`template/`](../../template) offre un plugin minimo da cui partire.

## ✅ Regole di revisione

- Codice leggibile, senza offuscamento; repository pubblico con licenza e README.
- Solo i permessi strettamente necessari, spiegati nel README del plugin.
- Nessuna raccolta di dati nascosta, nessun codice scaricato durante l'esecuzione.
- Nome, descrizione e logo non devono trarre in inganno né imitare un altro progetto o marchio.

## 🔒 Sicurezza

Un plugin **non è isolato** in una sandbox: viene eseguito con i diritti di Stellio sul computer. La revisione riduce il rischio, non lo elimina: leggete il codice e i permessi prima di attivare un plugin. I plugin sono installati disattivati, i download avvengono solo tramite `https` e la somma SHA-256 è obbligatoria.

Per segnalare un problema con un plugin elencato, aprite una issue in questo repository.

## 🔗 Risorse

- 📖 [Documentazione di Stellio](https://stellio-app.com/docs/) – la pagina **Plugin** spiega come creare e pubblicare un plugin
- 🧩 [Stellio](https://github.com/stellio-app/stellio) – l'applicazione
- 🧪 [`template/`](../../template) – plugin minimo da copiare

## 📜 Licenza

Gli strumenti di questo repository sono rilasciati con **licenza MIT** – vedi [LICENSE](../../LICENSE). Ogni plugin resta sotto la licenza scelta dal suo autore.

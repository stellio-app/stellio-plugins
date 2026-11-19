<p align="center">
  <img src="https://stellio-app.com/assets/logo-nom-stellio.png" alt="Logo Stellio" width="360">
</p>

<h3 align="center">Le catalogue officiel des plugins Stellio</h3>

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

<p align="center">Les plugins étendent <a href="https://github.com/stellio-app/stellio">Stellio</a>, le gestionnaire de fichiers 3D pour les makers et propriétaires d'imprimantes 3D. Ce dépôt contient la liste publique affichée dans <b>Plugins › Catalogue</b>.</p>

<p align="center">
  <a href="https://stellio-app.com/docs/"><b>📖 Documentation</b></a> &nbsp;·&nbsp; <a href="https://demo.stellio-app.com"><b>▶ Demo</b></a>
</p>

<p align="center"><a href="#-présentation">📦 Présentation</a> &nbsp;·&nbsp; <a href="#-installer-un-plugin">🚀 Installer un plugin</a> &nbsp;·&nbsp; <a href="#-proposer-votre-plugin">🧩 Proposer votre plugin</a> &nbsp;·&nbsp; <a href="#-règles-de-relecture">✅ Règles de relecture</a> &nbsp;·&nbsp; <a href="#-sécurité">🔒 Sécurité</a> &nbsp;·&nbsp; <a href="#-ressources">🔗 Ressources</a> &nbsp;·&nbsp; <a href="#-licence">📜 Licence</a></p>

---

## 📦 Présentation

Un **plugin** est un petit programme Python qui réagit à un évènement de Stellio (impression terminée, impression échouée, commande en retard, imprimante en surcharge) : envoyer une notification, écrire dans un tableur, allumer une lampe, exporter des métriques…

Les plugins sont **hébergés par leurs auteurs sur GitHub**. Ce dépôt contient seulement [`catalog.json`](../../catalog.json) : pour chaque plugin, un nom, une description, un logo et un lien vers une archive de release avec sa somme SHA-256. Stellio lit ce fichier et l'affiche sous forme de cartes (logo + description) dans **Plugins › Catalogue**.

## 🚀 Installer un plugin

1. Dans Stellio, ouvrez **Plugins › Catalogue** (compte propriétaire uniquement).
2. Parcourez le catalogue et cliquez sur **Installer** : Stellio télécharge l'archive et vérifie sa somme SHA-256.
3. Lisez les **permissions** demandées et acceptez-les. Le plugin est installé **désactivé**.
4. Activez-le, puis cliquez sur **Essai** pour le lancer avec un évènement de test. Le journal des exécutions affiche la sortie.

## 🧩 Proposer votre plugin

1. Créez et publiez votre plugin (voir la page **Plugins** de la [documentation Stellio](https://stellio-app.com/docs/)) : une release GitHub avec une archive `.zip`.
2. Forkez ce dépôt et ajoutez une entrée dans [`catalog.json`](../../catalog.json) :

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

3. Vérifiez en local : `python validate_catalog.py catalog.json`.
4. Ouvrez une **Pull Request**. Une action GitHub rejoue les contrôles (liens, SHA-256, cohérence avec `plugin.json`, logo), puis l'équipe Stellio relit le plugin.

| Champ | Règle |
|---|---|
| `description` | Courte (environ 140 caractères) ; texte simple ou un texte par langue (`fr`, `en`, `de`, `es`, `pt`, `it`, `zh`, `ja`) |
| `url` | Lien `https` direct vers l'archive `.zip` (2 Mo maximum) |
| `sha256` | Somme de l'archive ; doit correspondre exactement |
| `logo` | `https`, PNG, JPEG ou WebP, 200 Ko maximum, idéalement 128 × 128 (SVG refusé) |
| `homepage` | Lien `https` vers la page du plugin (facultatif) |
| `permissions` | Doivent correspondre à celles du `plugin.json` du plugin |

**Mise à jour** : publiez une nouvelle release, puis ouvrez une Pull Request qui change `version`, `url` et `sha256`. Le dossier [`template/`](../../template) fournit un plugin minimal pour démarrer.

## ✅ Règles de relecture

- Code lisible, sans obfuscation ; dépôt public avec licence et README.
- Uniquement les permissions strictement nécessaires, expliquées dans le README du plugin.
- Aucune collecte de données cachée, aucun code téléchargé à l'exécution.
- Le nom, la description et le logo ne doivent pas induire en erreur ni imiter un autre projet ou une autre marque.

## 🔒 Sécurité

Un plugin n'est **pas isolé** dans un bac à sable : il s'exécute avec les droits de Stellio sur la machine. La relecture réduit le risque, elle ne le supprime pas : lisez le code et les permissions avant d'activer un plugin. Les plugins sont installés désactivés, les téléchargements ne passent que par `https` et la somme SHA-256 est obligatoire.

Pour signaler un problème sur un plugin listé, ouvrez une issue dans ce dépôt.

## 🔗 Ressources

- 📖 [Documentation Stellio](https://stellio-app.com/docs/) – la page **Plugins** explique comment créer et publier un plugin
- 🧩 [Stellio](https://github.com/stellio-app/stellio) – l'application
- 🧪 [`template/`](../../template) – plugin minimal à copier

## 📜 Licence

Le code de ce dépôt – outils et plugins qu'il contient (comme la visionneuse G-code) – est sous **licence GNU AGPL v3** – voir [LICENSE](../../LICENSE). Les plugins de tiers listés dans le catalogue restent sous la licence choisie par leur auteur.

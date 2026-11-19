<p align="center">
  <img src="https://stellio-app.com/assets/logo-nom-stellio.png" alt="Logotipo de Stellio" width="360">
</p>

<h3 align="center">El catálogo oficial de plugins de Stellio</h3>

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

<p align="center">Los plugins amplían <a href="https://github.com/stellio-app/stellio">Stellio</a>, el gestor de archivos 3D para makers y propietarios de impresoras 3D. Este repositorio contiene la lista pública que se muestra en <b>Plugins › Catálogo</b>.</p>

<p align="center">
  <a href="https://stellio-app.com/docs/"><b>📖 Documentation</b></a> &nbsp;·&nbsp; <a href="https://demo.stellio-app.com"><b>▶ Demo</b></a>
</p>

<p align="center"><a href="#-presentación">📦 Presentación</a> &nbsp;·&nbsp; <a href="#-instalar-un-plugin">🚀 Instalar un plugin</a> &nbsp;·&nbsp; <a href="#-proponer-su-plugin">🧩 Proponer su plugin</a> &nbsp;·&nbsp; <a href="#-reglas-de-revisión">✅ Reglas de revisión</a> &nbsp;·&nbsp; <a href="#-seguridad">🔒 Seguridad</a> &nbsp;·&nbsp; <a href="#-recursos">🔗 Recursos</a> &nbsp;·&nbsp; <a href="#-licencia">📜 Licencia</a></p>

---

## 📦 Presentación

Un **plugin** es un pequeño programa Python que reacciona a un evento de Stellio (impresión terminada, impresión fallida, pedido atrasado, impresora sobrecargada): enviar una notificación, escribir en una hoja de cálculo, encender una luz, exportar métricas…

Los plugins los **alojan sus autores en GitHub**. Este repositorio solo contiene [`catalog.json`](../../catalog.json): para cada plugin, un nombre, una descripción, un logotipo y un enlace a un archivo de release con su suma SHA-256. Stellio lee este archivo y lo muestra como tarjetas (logotipo + descripción) en **Plugins › Catálogo**.

## 🚀 Instalar un plugin

1. En Stellio, abra **Plugins › Catálogo** (solo la cuenta propietaria).
2. Explore el catálogo y haga clic en **Instalar**: Stellio descarga el archivo y comprueba su suma SHA-256.
3. Lea los **permisos** solicitados y acéptelos. El plugin se instala **desactivado**.
4. Actívelo y pulse **Prueba** para lanzarlo con un evento de prueba. El registro de ejecuciones muestra la salida.

## 🧩 Proponer su plugin

1. Cree y publique su plugin (vea la página **Plugins** de la [documentación de Stellio](https://stellio-app.com/docs/)): una release de GitHub con un archivo `.zip`.
2. Haga un fork de este repositorio y añada una entrada en [`catalog.json`](../../catalog.json):

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

3. Compruébelo en local: `python validate_catalog.py catalog.json`.
4. Abra una **Pull Request**. Una acción de GitHub repite las comprobaciones (enlaces, SHA-256, coherencia con `plugin.json`, logotipo) y después el equipo de Stellio revisa el plugin.

| Campo | Regla |
|---|---|
| `description` | Corta (unos 140 caracteres); texto simple o un texto por idioma (`fr`, `en`, `de`, `es`, `pt`, `it`, `zh`, `ja`) |
| `url` | Enlace `https` directo al archivo `.zip` (2 MB como máximo) |
| `sha256` | Suma del archivo; debe coincidir exactamente |
| `logo` | `https`, PNG, JPEG o WebP, 200 KB como máximo, idealmente 128 × 128 (se rechaza el SVG) |
| `homepage` | Enlace `https` a la página del plugin (opcional) |
| `permissions` | Deben coincidir con las del `plugin.json` del plugin |

**Actualizar**: publique una nueva release y abra una Pull Request que cambie `version`, `url` y `sha256`. La carpeta [`template/`](../../template) ofrece un plugin mínimo para empezar.

## ✅ Reglas de revisión

- Código legible, sin ofuscar; repositorio público con licencia y README.
- Solo los permisos estrictamente necesarios, explicados en el README del plugin.
- Sin recopilación oculta de datos ni código descargado en tiempo de ejecución.
- El nombre, la descripción y el logotipo no deben engañar ni imitar otro proyecto u otra marca.

## 🔒 Seguridad

Un plugin **no está aislado** en un entorno protegido: se ejecuta con los derechos de Stellio en el equipo. La revisión reduce el riesgo, no lo elimina: lea el código y los permisos antes de activar un plugin. Los plugins se instalan desactivados, las descargas solo van por `https` y la suma SHA-256 es obligatoria.

Para informar de un problema con un plugin listado, abra una issue en este repositorio.

## 🔗 Recursos

- 📖 [Documentación de Stellio](https://stellio-app.com/docs/) – la página **Plugins** explica cómo crear y publicar un plugin
- 🧩 [Stellio](https://github.com/stellio-app/stellio) – la aplicación
- 🧪 [`template/`](../../template) – plugin mínimo para copiar

## 📜 Licencia

El código de este repositorio – herramientas y plugins incluidos (como el visor de G-code) – se publica bajo la **GNU AGPL v3** – véase [LICENSE](../../LICENSE). Los plugins de terceros listados en el catálogo conservan la licencia elegida por su autor.

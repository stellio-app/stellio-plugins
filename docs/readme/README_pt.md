<p align="center">
  <img src="https://stellio-app.com/assets/logo-nom-stellio.png" alt="Logótipo do Stellio" width="360">
</p>

<h3 align="center">O catálogo oficial de plugins do Stellio</h3>

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

<p align="center">Os plugins alargam o <a href="https://github.com/stellio-app/stellio">Stellio</a>, o gestor de ficheiros 3D para makers e proprietários de impressoras 3D. Este repositório contém a lista pública apresentada em <b>Plugins › Catálogo</b>.</p>

<p align="center">
  <a href="https://stellio-app.com/docs/"><b>📖 Documentation</b></a> &nbsp;·&nbsp; <a href="https://demo.stellio-app.com"><b>▶ Demo</b></a>
</p>

<p align="center"><a href="#-apresentação">📦 Apresentação</a> &nbsp;·&nbsp; <a href="#-instalar-um-plugin">🚀 Instalar um plugin</a> &nbsp;·&nbsp; <a href="#-propor-o-seu-plugin">🧩 Propor o seu plugin</a> &nbsp;·&nbsp; <a href="#-regras-de-revisão">✅ Regras de revisão</a> &nbsp;·&nbsp; <a href="#-segurança">🔒 Segurança</a> &nbsp;·&nbsp; <a href="#-recursos">🔗 Recursos</a> &nbsp;·&nbsp; <a href="#-licença">📜 Licença</a></p>

---

## 📦 Apresentação

Um **plugin** é um pequeno programa Python que reage a um evento do Stellio (impressão concluída, impressão falhada, encomenda atrasada, impressora sobrecarregada): enviar uma notificação, escrever numa folha de cálculo, acender uma luz, exportar métricas…

Os plugins são **alojados pelos seus autores no GitHub**. Este repositório contém apenas [`catalog.json`](../../catalog.json): para cada plugin, um nome, uma descrição, um logótipo e uma ligação para um arquivo de release com a sua soma SHA-256. O Stellio lê este ficheiro e apresenta-o em cartões (logótipo + descrição) em **Plugins › Catálogo**.

## 🚀 Instalar um plugin

1. No Stellio, abra **Plugins › Catálogo** (apenas a conta proprietária).
2. Explore o catálogo e clique em **Instalar**: o Stellio descarrega o arquivo e verifica a sua soma SHA-256.
3. Leia as **permissões** pedidas e aceite-as. O plugin é instalado **desativado**.
4. Ative-o e clique em **Teste** para o executar com um evento de teste. O registo de execuções mostra a saída.

## 🧩 Propor o seu plugin

1. Crie e publique o seu plugin (veja a página **Plugins** da [documentação do Stellio](https://stellio-app.com/docs/)): uma release do GitHub com um arquivo `.zip`.
2. Faça um fork deste repositório e adicione uma entrada em [`catalog.json`](../../catalog.json):

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

3. Verifique localmente: `python validate_catalog.py catalog.json`.
4. Abra uma **Pull Request**. Uma ação do GitHub repete as verificações (ligações, SHA-256, coerência com `plugin.json`, logótipo) e depois a equipa do Stellio revê o plugin.

| Campo | Regra |
|---|---|
| `description` | Curta (cerca de 140 caracteres); texto simples ou um texto por idioma (`fr`, `en`, `de`, `es`, `pt`, `it`, `zh`, `ja`) |
| `url` | Ligação `https` direta ao arquivo `.zip` (2 MB no máximo) |
| `sha256` | Soma do arquivo; tem de coincidir exatamente |
| `logo` | `https`, PNG, JPEG ou WebP, 200 KB no máximo, idealmente 128 × 128 (o SVG é recusado) |
| `homepage` | Ligação `https` para a página do plugin (opcional) |
| `permissions` | Têm de corresponder às do `plugin.json` do plugin |

**Atualizar**: publique uma nova release e abra uma Pull Request que altere `version`, `url` e `sha256`. A pasta [`template/`](../../template) oferece um plugin mínimo para começar.

## ✅ Regras de revisão

- Código legível, sem ofuscação; repositório público com licença e README.
- Apenas as permissões estritamente necessárias, explicadas no README do plugin.
- Sem recolha de dados oculta nem código descarregado durante a execução.
- O nome, a descrição e o logótipo não devem induzir em erro nem imitar outro projeto ou marca.

## 🔒 Segurança

Um plugin **não corre isolado** numa área protegida: é executado com os direitos do Stellio na máquina. A revisão reduz o risco, não o elimina: leia o código e as permissões antes de ativar um plugin. Os plugins são instalados desativados, as transferências só são feitas por `https` e a soma SHA-256 é obrigatória.

Para comunicar um problema com um plugin listado, abra uma issue neste repositório.

## 🔗 Recursos

- 📖 [Documentação do Stellio](https://stellio-app.com/docs/) – a página **Plugins** explica como criar e publicar um plugin
- 🧩 [Stellio](https://github.com/stellio-app/stellio) – a aplicação
- 🧪 [`template/`](../../template) – plugin mínimo para copiar

## 📜 Licença

As ferramentas deste repositório são disponibilizadas sob a **licença MIT** – ver [LICENSE](../../LICENSE). Cada plugin mantém a licença escolhida pelo seu autor.

# Plugin template

Minimal Stellio plugin: reads the event on standard input and prints one line to the run log.

1. Copy this folder and edit `plugin.json` (`id`, `name`, `version`, `description`, `author`, `events`, `permissions`).
2. Zip the **contents** of the folder (2 MB maximum) and install the archive from **Tools › Plugins** in Stellio.
3. Publish a GitHub release with the archive, then follow the root [README](../README.md) to get listed.

Note: Stellio runs `python -I main.py <event>`, so the plugin folder is not on Python's path; add it yourself to import your own files.

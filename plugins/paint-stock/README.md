# Filament painter

<p align="center"><img src="logo.png" width="96" alt=""></p>

<details open>
<summary><b>English</b></summary>

3D print tool for Stellio (opens from the **Plugins** menu). Paints an STL / 3MF model with the colors of the spools in your filament stock and creates a painted 3MF (one color = one filament) for Bambu Studio / OrcaSlicer.

- Brush, paint bucket, fill all, eraser, undo/redo; colors come from your stock (manual, Spoolman, TigerTag)
- Per-face painting: painting the top does not color the sides; large faces are subdivided so part of a face can be painted
- Share of each filament shown while you paint; the original file is never modified
- Needs the `ui`, `api:read` and `api:write` permissions (writes only the new 3MF), no network

Signed plugin with built-in code: it installs only if its signature is valid and Stellio trusts the key (Stellio 1.2.0 or later).

Install: Plugins › Catalogue › Filament painter › Install, then enable it.
</details>

<details>
<summary><b>Français</b></summary>

Outil d'impression 3D pour Stellio (menu **Plugins**). Peint un modèle STL / 3MF avec les couleurs des bobines de votre stock et crée un 3MF peint (une couleur = un filament) pour Bambu Studio / OrcaSlicer.

- Pinceau, pot de peinture, tout remplir, gomme, annuler/rétablir ; couleurs issues de votre stock (manuel, Spoolman, TigerTag)
- Peinture par face : peindre le dessus ne colore pas les côtés ; les grandes faces sont subdivisées pour en peindre une partie
- Part de chaque filament affichée pendant la peinture ; le fichier d'origine n'est jamais modifié
- Permissions `ui`, `api:read`, `api:write` (n'écrit que le nouveau 3MF), aucun réseau

Plugin signé à code intégré : il ne s'installe que si sa signature est valide et que Stellio fait confiance à la clé (Stellio 1.2.0 ou plus).

Installation : Plugins › Catalogue › Peinture filaments › Installer, puis l'activer.
</details>

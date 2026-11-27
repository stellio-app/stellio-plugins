# 3D cutter

<p align="center"><img src="logo.png" width="96" alt=""></p>

<details open>
<summary><b>English</b></summary>

3D print tool for Stellio (opens from the **Plugins** menu). Cuts an STL / 3MF model with one or more planes so that it fits your print bed.

- Preview (WebGL) with a different color on each side of every cut plane; automatic cuts for the bed size
- Connectors between the pieces: pegs, dowels, magnet pockets or none; round, square or cross shapes; adjustable clearance
- Pieces laid flat on their cut face and packed on plates; assembly guide as a PDF
- The original file is never modified. Needs the `ui`, `api:read` and `api:write` permissions (writes only the new file), no network

Signed plugin with built-in code: it installs only if its signature is valid and Stellio trusts the key (Stellio 1.2.0 or later). Heavy cuts run in the background when Stellio 1.2.2 or later provides it.

Install: Plugins › Catalogue › 3D cutter › Install, then enable it.
</details>

<details>
<summary><b>Français</b></summary>

Outil d'impression 3D pour Stellio (menu **Plugins**). Découpe un modèle STL / 3MF avec un ou plusieurs plans pour qu'il tienne sur votre plateau.

- Aperçu WebGL avec une couleur de chaque côté du plan de coupe ; coupes automatiques selon la taille du plateau
- Connecteurs entre les pièces : tenons, goujons, logements d'aimants ou aucun ; formes ronde, carrée ou croix ; jeu réglable
- Pièces posées à plat sur leur face de coupe et rangées sur des plateaux ; guide d'assemblage en PDF
- Le fichier d'origine n'est jamais modifié. Permissions `ui`, `api:read`, `api:write` (n'écrit que le nouveau fichier), aucun réseau

Plugin signé à code intégré : il ne s'installe que si sa signature est valide et que Stellio fait confiance à la clé (Stellio 1.2.0 ou plus). Les découpes lourdes passent en tâche de fond avec Stellio 1.2.2 ou plus.

Installation : Plugins › Catalogue › Découpe 3D › Installer, puis l'activer.
</details>

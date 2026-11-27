# Hollow & drain

<p align="center"><img src="logo.png" width="96" alt=""></p>

<details open>
<summary><b>English</b></summary>

3D print tool for Stellio (opens from the **Plugins** menu). Hollows out an STL / 3MF model with a constant wall thickness to save resin or filament, then drills drain and vent holes so the inside can be emptied.

- Wall thickness you choose (never thinner than requested); small pockets can be ignored; three quality levels
- Every separate pocket gets its own drain hole (lowest point) and an optional vent (highest point), placed where the tunnel through the wall is shortest; drain on the bottom or on the top for models printed upside down
- Cutaway preview (WebGL) with a movable section plane, volume and material saved
- Optional printable plugs (with adjustable clearance) to close the holes afterwards
- Writes a new 3MF (hollowed model + plugs) or STL; the original file is never modified. Needs the `ui`, `api:read` and `api:write` permissions (writes only the new file), no network

Signed plugin with built-in code: it installs only if its signature is valid and Stellio trusts the key. Heavy models run in the background when Stellio provides it. Uses numpy, scipy, scikit-image and manifold3d, which ship with Stellio.

Install: Plugins › Catalogue › Hollow & drain › Install, then enable it.
</details>

<details>
<summary><b>Français</b></summary>

Outil d'impression 3D pour Stellio (menu **Plugins**). Évide un modèle STL / 3MF à épaisseur de paroi constante pour économiser la résine ou le filament, puis perce des trous de drainage et d'évent pour pouvoir vider l'intérieur.

- Épaisseur de paroi au choix (jamais plus fine que demandé) ; petites poches ignorables ; trois niveaux de qualité
- Chaque poche séparée reçoit son trou de vidange (point le plus bas) et un évent optionnel (point le plus haut), placés là où le tunnel dans la paroi est le plus court ; vidange en bas ou en haut pour un modèle imprimé à l'envers
- Aperçu en coupe (WebGL) avec plan de section réglable, volume et matière économisée
- Bouchons imprimables en option (jeu réglable) pour refermer les trous ensuite
- Écrit un nouveau 3MF (modèle creux + bouchons) ou STL ; le fichier d'origine n'est jamais modifié. Permissions `ui`, `api:read`, `api:write` (n'écrit que le nouveau fichier), aucun réseau

Plugin signé à code intégré : il ne s'installe que si sa signature est valide et que Stellio fait confiance à la clé. Les gros modèles passent en tâche de fond quand Stellio le permet. Utilise numpy, scipy, scikit-image et manifold3d, livrés avec Stellio.

Installation : Plugins › Catalogue › Hollow & drain › Installer, puis l'activer.
</details>

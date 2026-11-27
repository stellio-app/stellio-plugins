"""Stellio — plugin signé « Séparer par couleur » (catalogue stellio-plugins, 1.1.0)

Un 3MF multicolore (Bambu / Orca / PrusaSlicer, matières 3MF, peinture par triangle) → un NOUVEAU 3MF avec un plateau par couleur.
La pièce garde sa position sur chaque plateau et chaque objet porte sa couleur. Le fichier d'origine n'est jamais modifié.
Plugin du catalogue qui déclare `host` : il s'exécute DANS Stellio, donc n'est installé que signé par une clé de confiance (voir docs/plugins.md).
Routes dans l'espace réservé aux plugins : /api/x/split-color/… ; page : split.html (cadre isolé, écriture via le pont `stellio.api(..., 'json', {method:'POST'})`).
"""
import base64
import io
import math
import os
import re
import threading
import zipfile
from collections import OrderedDict
from xml.sax.saxutils import quoteattr

_REQUIRED = (
    'DATA_DIR',
    '_is_path_within_sources',
    '_smb_kwargs_for_path',
    '_resolve_3mf_plate_mesh',
    '_thumb_base_rgb',
    'app',
    'app_logger',
    'get_db',
    'invalidate_cache',
    'jsonify',
    'login_required',
    'np',
    'request',
    'session',
    'smbclient',
)
_OPTIONAL = ('CACHE_FILE', '_read_cache_json_safe', '_wv_dialog', 'run_view_async')
_OVERRIDABLE = ("os", )

_MAIN = {}
DATA_DIR = None
_is_path_within_sources = None
_smb_kwargs_for_path = None
_resolve_3mf_plate_mesh = None
_thumb_base_rgb = None
app = None
app_logger = None
get_db = None
invalidate_cache = None
jsonify = None
login_required = None
run_view_async = None
np = None
request = None
session = None
smbclient = None
CACHE_FILE = None
_read_cache_json_safe = None
_wv_dialog = None

PLATE_GAP = 0.2   # écart logique entre plateaux dans l'espace Bambu (20 % de la taille du plateau)
MAX_COLORS = 24


_JC = None


def _jc():
    """Point d'annulation : lève l'annulation demandée par la page (bouton Annuler) ; sans effet hors tâche ou sur un Stellio sans job_check."""
    global _JC
    if _JC is None:
        try:
            from modules import job_manager as _jm
            _JC = getattr(_jm, 'job_check', None) or (lambda: None)
        except Exception:
            _JC = lambda: None
    _JC()


_LIB = {'key': None, 'files': []}


def _library_files():
    """Liste des fichiers du cache de la bibliothèque, relue seulement quand ce cache change (il peut peser plusieurs Mo : la relire à chaque ouverture de page ralentissait l'affichage)."""
    try:
        if not (CACHE_FILE and _read_cache_json_safe and os.path.exists(CACHE_FILE)):
            return []
        st = os.stat(CACHE_FILE)
        key = (CACHE_FILE, st.st_mtime_ns, st.st_size)
        if _LIB['key'] != key:
            data = _read_cache_json_safe()
            _LIB['files'] = (data or {}).get('files') or []
            _LIB['key'] = key
        return _LIB['files']
    except Exception:
        return []

def _plate_columns(count):
    """Nombre de colonnes de la grille de plateaux (même règle que Bambu Studio)."""
    value = math.sqrt(count)
    rounded = round(value)
    return rounded + 1 if value > rounded else max(1, rounded)


def _plate_origin(index, count, bed_w, bed_d):
    cols = _plate_columns(count)
    row, col = divmod(index, cols)
    return col * bed_w * (1 + PLATE_GAP), -row * bed_d * (1 + PLATE_GAP)


def _safe_name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r'[\x00-\x1f<>]', '', base).strip() or 'piece'


def _repair_core(vertices, faces, max_loops=4000):
    """Répare un maillage avant livraison : soude les sommets, retire les faces dégénérées ou en double, referme les trous
    (chaque bord ouvert est comblé par un éventail depuis son centre, dans le bon sens), oriente le volume vers l'extérieur.
    Renvoie (sommets, faces, {'filled': trous refermés, 'open': arêtes encore ouvertes, 'nonmanifold': arêtes partagées par > 2 faces})."""
    v = np.asarray(vertices, dtype=float)
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if len(f) == 0:
        return v, f, {'filled': 0, 'open': 0, 'nonmanifold': 0}
    uniq, inv = np.unique(np.round(v, 4), axis=0, return_inverse=True)
    f = np.asarray(inv).reshape(-1)[f]
    v = uniq
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    if len(f):
        _, first = np.unique(np.sort(f, axis=1), axis=0, return_index=True)
        f = f[np.sort(first)]
        area = np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)
        f = f[area > 1e-12]
    de = {}
    for a, b, c in f.tolist():
        for e in ((a, b), (b, c), (c, a)):
            de[e] = de.get(e, 0) + 1
    nxt = {}
    for (a, b), n in de.items():
        if (b, a) not in de:
            nxt.setdefault(b, []).append(a)       # bord ouvert a→b : le comblement le parcourt dans le sens b→a
    new_v, new_f, filled = [], [], 0
    base = len(v)
    while nxt and filled < max_loops:
        start = next(iter(nxt))
        loop, cur = [start], start
        while True:
            outs = nxt.get(cur)
            if not outs:
                loop = None
                break
            nx = outs.pop()
            if not outs:
                del nxt[cur]
            if nx == start:
                break
            loop.append(nx)
            cur = nx
            if len(loop) > 200000:
                loop = None
                break
        if loop is None or len(loop) < 3:
            nxt.pop(start, None)
            continue
        if len(loop) == 3:
            new_f.append(loop)
        else:
            c = v[loop].mean(axis=0)
            ci = base + len(new_v)
            new_v.append(c)
            for i in range(len(loop)):
                new_f.append([ci, loop[i], loop[(i + 1) % len(loop)]])
        filled += 1
    if new_v:
        v = np.vstack([v, np.asarray(new_v)])
    if new_f:
        f = np.vstack([f, np.asarray(new_f, dtype=np.int64)])
    if len(f):
        tri = v[f]
        vol = float(np.einsum('ij,ij->', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6.0)
        if vol < 0:
            f = f[:, ::-1].copy()
    cnt = {}
    for a, b, c in f.tolist():
        for e in ((a, b), (b, c), (c, a)):
            k = e if e[0] < e[1] else (e[1], e[0])
            cnt[k] = cnt.get(k, 0) + 1
    return v, f, {'filled': filled, 'open': sum(1 for n in cnt.values() if n == 1), 'nonmanifold': sum(1 for n in cnt.values() if n > 2)}


def _edge_stats(v, f):
    cnt = {}
    for a, b, c in np.asarray(f).tolist():
        for e in ((a, b), (b, c), (c, a)):
            k = e if e[0] < e[1] else (e[1], e[0])
            cnt[k] = cnt.get(k, 0) + 1
    return {'open': sum(1 for n in cnt.values() if n == 1), 'nonmanifold': sum(1 for n in cnt.values() if n > 2)}


def _repair_mesh(vertices, faces, max_loops=4000):
    """Répare un maillage (voir _repair_core) puis, s'il reste des arêtes ouvertes ou partagées par plus de 2 faces (contours pincés
    de surfaces peintes), termine avec pymeshfix (livré avec Stellio) : le résultat est un volume fermé, orienté vers l'extérieur."""
    v, f, st = _repair_core(vertices, faces, max_loops)
    if (st['open'] or st['nonmanifold']) and len(f) >= 4:
        try:
            import pymeshfix
            mf = pymeshfix.MeshFix(np.ascontiguousarray(v, dtype=float), np.ascontiguousarray(f, dtype=np.int32))
            mf.repair(joincomp=False, remove_smallest_components=False)
            v2, f2 = np.asarray(mf.points, dtype=float), np.asarray(mf.faces, dtype=np.int64).reshape(-1, 3)
            if len(f2) >= 4:
                tri = v2[f2]
                if float(np.einsum('ij,ij->', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6.0) < 0:
                    f2 = f2[:, ::-1].copy()
                es = _edge_stats(v2, f2)
                if es['open'] + es['nonmanifold'] < st['open'] + st['nonmanifold']:
                    v, f = v2, f2
                    st = {'filled': st['filled'], 'open': es['open'], 'nonmanifold': es['nonmanifold']}
        except Exception as e:
            try:
                app_logger.info(f"[Séparation couleur] pymeshfix indisponible : {e}")
            except Exception:
                pass
    return v, f, st


def _components(faces):
    """Composantes connexes d'un maillage (faces reliées par un sommet commun) : liste de tableaux d'indices de faces."""
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    n = int(f.max()) + 1 if len(f) else 0
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, c in f.tolist():
        ra, rb, rc = find(a), find(b), find(c)
        if ra != rb:
            parent[rb] = ra
        if find(rc) != find(ra):
            parent[find(rc)] = find(ra)
    roots = np.array([find(int(x)) for x in f[:, 0]], dtype=np.int64) if len(f) else np.zeros(0, dtype=np.int64)
    out = []
    for r in np.unique(roots):
        out.append(np.nonzero(roots == r)[0])
    return out


def _pack(sizes, bed_w, gap=6.0):
    """Range des rectangles (largeur, profondeur) en rangées, sans chevauchement. Renvoie ([(x, y) coin bas-gauche], largeur, profondeur) ;
    l'ensemble est ensuite centré sur le plateau par l'appelant."""
    order = sorted(range(len(sizes)), key=lambda i: -sizes[i][1])
    limit = max(bed_w * 0.9, max((s[0] for s in sizes), default=0))
    pos = [None] * len(sizes)
    x = y = row_h = total_w = 0.0
    for i in order:
        w, d = sizes[i]
        if x > 0 and x + w > limit:
            x, y, row_h = 0.0, y + row_h + gap, 0.0
        pos[i] = (x, y)
        x += w + gap
        row_h = max(row_h, d)
        total_w = max(total_w, x - gap)
    return pos, total_w, y + row_h


def _rot_to_down(d):
    """Rotation envoyant le vecteur unitaire d vers -z."""
    d = np.asarray(d, dtype=float)
    d = d / (np.linalg.norm(d) or 1.0)
    t = np.array([0.0, 0.0, -1.0])
    c = float(np.dot(d, t))
    if c > 0.999999:
        return np.eye(3)
    if c < -0.999999:
        return np.diag([1.0, -1.0, -1.0])
    ax = np.cross(d, t)
    k = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + k + k @ k / (1.0 + c)


def _overhang_area(v, f, R):
    """Aire (mm²) des faces en surplomb (> 45°) une fois la pièce tournée par R et posée à z = 0 ; la face posée sur le plateau n'en fait pas partie."""
    w = v @ R.T
    z0 = w[:, 2].min()
    tri = w[f]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ar = np.linalg.norm(nrm, axis=1) / 2.0
    nz = nrm[:, 2] / (2.0 * ar + 1e-12)
    low = tri[:, :, 2].max(axis=1) - z0 < 0.2
    return float(ar[(nz < -0.7071) & ~low].sum())


def _orient_for_print(v, f):
    """Pose la pièce sur sa meilleure face (plus grande face plane de l'enveloppe convexe) si cela réduit nettement les surplombs
    (donc les supports) ; sinon elle garde son orientation d'origine. Renvoie les sommets tournés."""
    _jc()
    try:
        from scipy.spatial import ConvexHull
        pts = v[np.unique(f)]
        hull = ConvexHull(pts[::max(1, len(pts) // 60000)])
        eq = hull.equations
        simp = hull.simplices
        tri = pts[::max(1, len(pts) // 60000)][simp]
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2.0
        cand, seen = [], []
        for i in np.argsort(-area):
            _jc()
            n = eq[i, :3]
            if any(np.dot(n, q) > 0.985 for q in seen):
                continue
            seen.append(n)
            cand.append(n)
            if len(cand) >= 8:
                break
        base = _overhang_area(v, f, np.eye(3))
        best, best_s = np.eye(3), base
        for n in cand:
            _jc()
            R = _rot_to_down(-n)
            sc = _overhang_area(v, f, R)
            if sc < best_s:
                best, best_s = R, sc
        if best_s < 0.7 * base:
            return v @ best.T
    except Exception:
        pass
    return v


def _arrange(shells, bed_w, bed_d):
    """shells = [(sommets, faces)] d'une couleur → objets prêts pour son plateau : chaque morceau est posé sur le plateau (z = 0) et rangé
    près du centre, sans chevauchement. Renvoie (objets, tient_sur_le_plateau)."""
    _jc()
    items = []
    for v, f in shells:
        _jc()
        v = _orient_for_print(v, f)
        lo, hi = v.min(axis=0), v.max(axis=0)
        items.append((v - np.array([(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, lo[2]]), f, float(hi[0] - lo[0]), float(hi[1] - lo[1])))
    pos, tw, td = _pack([(w, d) for _v, _f, w, d in items], bed_w)
    objs = []
    for (v, f, w, d), (px, py) in zip(items, pos):
        _jc()
        objs.append({'vertices': v, 'faces': f, 'cx': bed_w / 2.0 + px + w / 2.0 - tw / 2.0, 'cy': bed_d / 2.0 + py + d / 2.0 - td / 2.0})
    return objs, tw <= bed_w and td <= bed_d


# ── Connecteurs d'emboîtement : un tenon sur la plus petite pièce, le trou correspondant (avec du jeu) dans celle qui la reçoit ──

def _solid(v, f):
    """Manifold (manifold3d, livré avec Stellio) d'un maillage fermé ; None s'il n'est pas utilisable."""
    from manifold3d import Manifold, Mesh
    m = Manifold(Mesh(vert_properties=np.ascontiguousarray(v, dtype=np.float32), tri_verts=np.ascontiguousarray(f, dtype=np.uint32)))
    return None if (m.is_empty() or not str(m.status()).endswith('NoError')) else m


def _unsolid(m):
    mesh = m.to_mesh()
    return np.array(mesh.vert_properties[:, :3], dtype=float), np.array(mesh.tri_verts, dtype=np.int64)


def _regions(mesh, labels, min_faces=4):
    """Régions = morceaux d'une même couleur, d'un seul tenant. Renvoie (région par face, couleur de chaque région, sommets soudés par face, coordonnées soudées)."""
    verts = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    uniq, inv = np.unique(np.round(verts, 4), axis=0, return_inverse=True)
    f_ids = np.asarray(inv).reshape(-1)[faces]
    region = np.full(len(faces), -1, dtype=np.int64)
    colors = []
    for k in range(int(labels.max()) + 1 if len(labels) else 0):
        idx = np.nonzero(labels == k)[0]
        if not len(idx):
            continue
        for comp in _components(f_ids[idx]):
            if len(comp) < min_faces:
                continue
            region[idx[comp]] = len(colors)
            colors.append(k)
    return region, colors, f_ids, uniq


def _frame(e1, e2, n):
    """Repère droit (colonnes e1', e2', n) dont l'axe z est n et dont x suit au mieux e1 : le tenon carré s'aligne sur le contact."""
    n = n / (np.linalg.norm(n) or 1.0)
    x = e1 - n * float(np.dot(e1, n))
    if np.linalg.norm(x) < 1e-9:
        x = e2 - n * float(np.dot(e2, n))
    x = x / (np.linalg.norm(x) or 1.0)
    y = np.cross(n, x)
    return np.column_stack([x, y, n])


def _place(m, r, c):
    mat = np.zeros((3, 4))
    mat[:, :3] = r
    mat[:, 3] = c
    return m.transform(mat)


def _square_peg(side, length, embed, bevel):
    """Tenon carré le long de +z : enfoncé de `embed` dans la pièce porteuse, dépasse de `length`, extrémité biseautée."""
    from manifold3d import Manifold, CrossSection
    sq = CrossSection.square([side, side], True)
    body = Manifold.extrude(sq, embed + length - bevel + 0.05).translate([0, 0, -embed])     # léger recouvrement avec l'embout : une seule pièce
    tip = Manifold.extrude(sq, bevel, 0, 0.0, ((side - 2 * bevel) / side, (side - 2 * bevel) / side)).translate([0, 0, length - bevel])
    return body + tip


def _square_hole(side, depth, back):
    from manifold3d import Manifold, CrossSection
    return Manifold.extrude(CrossSection.square([side, side], True), depth + back).translate([0, 0, -back])


def _bbox_overlap(a, b, tol=0.5):
    return bool(np.all(np.asarray(a[:3]) <= np.asarray(b[3:]) + tol) and np.all(np.asarray(b[:3]) <= np.asarray(a[3:]) + tol))


def _group_shells(shells, gap):
    """Regroupe les morceaux d'une même couleur qui se touchent presque (distance < gap mm) : ils restent ensemble, dans leurs positions
    d'origine, comme UNE pièce. gap = 0 : chaque morceau séparé reste une pièce à part. Renvoie une liste de (sommets, faces)."""
    _jc()
    n = len(shells)
    if n <= 1 or gap <= 0:
        return list(shells)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            _jc()
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    boxes = [(v.min(axis=0), v.max(axis=0)) for v, _f in shells]
    trees = {}
    try:
        from scipy.spatial import cKDTree
    except Exception:
        cKDTree = None
    for i in range(n):
        _jc()
        for j in range(i + 1, n):
            _jc()
            if find(i) == find(j):
                continue
            lo = np.maximum(boxes[i][0], boxes[j][0]); hi = np.minimum(boxes[i][1], boxes[j][1])
            d = np.maximum(lo - hi, 0.0)
            if float(np.linalg.norm(d)) >= gap:
                continue                                          # boîtes englobantes trop éloignées
            if cKDTree is not None and n <= 600:
                for q in (i, j):
                    _jc()
                    if q not in trees:
                        trees[q] = cKDTree(shells[q][0])
                small, big = (i, j) if len(shells[i][0]) <= len(shells[j][0]) else (j, i)
                dist = float(trees[big].query(shells[small][0], k=1)[0].min())
                if dist >= gap:
                    continue
            parent[find(j)] = find(i)
    groups = {}
    for i in range(n):
        _jc()
        groups.setdefault(find(i), []).append(i)
    out = []
    for idxs in groups.values():
        _jc()
        vs, fs, off = [], [], 0
        for i in idxs:
            _jc()
            v, f = shells[i]
            vs.append(v)
            fs.append(f + off)
            off += len(v)
        out.append((np.vstack(vs), np.vstack(fs)))
    return out


def _bodies(f_ids):
    """Corps d'un seul tenon (faces reliées par un sommet soudé) : liste de tableaux d'indices de faces (scipy, rapide)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    n = int(f_ids.max()) + 1
    a = np.concatenate([f_ids[:, 0], f_ids[:, 1]]); b = np.concatenate([f_ids[:, 1], f_ids[:, 2]])
    _k, lab = connected_components(coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n, n)), directed=False)
    fl = lab[f_ids[:, 0]]
    order = np.argsort(fl, kind='stable')
    cuts = np.nonzero(np.diff(fl[order]))[0] + 1
    return np.split(order, cuts)


def _absorb_strays(labels, f_ids, frac=0.006, min_faces=80, verts=None, faces=None, tiny_volume=40.0):
    """Un corps déjà fermé et (presque) monocolore reste ENTIER, avec sa couleur dominante : quelques faces d'une autre couleur
    (franges de peinture) ne le découpent pas. Renvoie (étiquettes corrigées, corps réellement multicolores)."""
    labels = labels.copy()
    mixed = []
    for comp in _bodies(f_ids):
        cnt = np.bincount(labels[comp])
        nz = np.nonzero(cnt)[0]
        if len(nz) <= 1:
            continue
        main = int(cnt.argmax())
        for k in nz:
            if k != main and cnt[k] < max(min_faces, frac * len(comp)):
                labels[comp[labels[comp] == k]] = main
        for k in np.unique(labels[comp]):                  # îlots minuscules d'une couleur dans un même corps : absorbés aussi
            if k == main:
                continue
            idx = comp[labels[comp] == k]
            for part in _components(f_ids[idx]):
                if len(part) < min_faces:
                    labels[idx[part]] = main
        if len(np.unique(labels[comp])) > 1 and verts is not None:
            t = verts[faces[comp]]                          # volume (mm³) du corps : trop petit pour être coupé en deux pièces imprimables
            vol = abs(float(np.einsum('ij,ij->', t[:, 0], np.cross(t[:, 1], t[:, 2])) / 6.0))
            if vol < tiny_volume:
                u = np.unique(labels[comp])
                cnt2 = np.bincount(labels[comp], minlength=int(u.max()) + 1)
                labels[comp] = int(cnt2.argmax())           # petit corps (griffe…) : une seule pièce, couleur dominante
        if len(np.unique(labels[comp])) > 1:
            mixed.append(comp)
    return labels, mixed


def _down_for(v, f):
    """Direction (dans le repère de la pièce) à tourner vers le plateau : la plus grande face d'appui de l'enveloppe convexe sur laquelle la pièce tient
    (centre de gravité au-dessus de la face)."""
    try:
        from scipy.spatial import ConvexHull
        P = np.asarray(v, dtype=float)
        h = ConvexHull(P[::max(1, len(P) // 4000)])
        pts, simp = h.points, h.simplices
        com = P.mean(axis=0)
        n = np.cross(pts[simp[:, 1]] - pts[simp[:, 0]], pts[simp[:, 2]] - pts[simp[:, 0]])
        ar = np.linalg.norm(n, axis=1) / 2.0
        n = n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
        out = (pts[simp[:, 0]] - h.interior_points.mean(axis=0)) if hasattr(h, 'interior_points') else (pts[simp[:, 0]] - pts.mean(axis=0))
        n = np.where(((n * out).sum(axis=1) < 0)[:, None], -n, n)                      # normales vers l'extérieur
        key = np.round(n, 2)
        _k, grp = np.unique(key, axis=0, return_inverse=True)
        grp = np.asarray(grp).reshape(-1)
        order = np.argsort(-np.bincount(grp, weights=ar))
        for g in order[:12]:
            m = grp == g
            nn = n[m].mean(axis=0); nn /= np.linalg.norm(nn)
            fp = pts[simp[m]].reshape(-1, 3)
            u = np.cross(nn, [1.0, 0.0, 0.0] if abs(nn[0]) < 0.9 else [0.0, 1.0, 0.0]); u /= np.linalg.norm(u); w = np.cross(nn, u)
            q = np.stack([fp @ u, fp @ w], axis=1)
            c2 = np.array([com @ u, com @ w])
            try:
                h2 = ConvexHull(q)
            except Exception:
                continue
            if np.all(h2.equations[:, :2] @ c2 + h2.equations[:, 2] <= 1e-6):
                return -nn                                                              # face d'appui vers le plateau
        return None
    except Exception:
        return None


def _split_solid_voxels(S, verts, faces, comp, labels, pending, max_vox=1200000, smooth_mm=1.2):
    """Repli du mode régions quand aucune coupe plane ne convient (modèles organiques) : chaque point du volume reçoit la région de la surface la plus proche,
    la frontière est lissée (filtre gaussien sur les zones) puis servira de surface de coupe. Les pièces sont obtenues par booléens avec le solide
    d'origine (surface extérieure intacte, pièces fermées, sans trou ni recouvrement). {zone: (sommets, faces)} ou None."""
    _jc()
    from scipy.ndimage import gaussian_filter
    from scipy.spatial import cKDTree
    from skimage.measure import marching_cubes
    mesh = S.to_mesh()
    P = np.array(mesh.vert_properties[:, :3], dtype=float)
    lo, hi = P.min(axis=0) - 3.0, P.max(axis=0) + 3.0
    pitch = max(0.4, float(np.prod(hi - lo) / max_vox) ** (1 / 3))
    shape = np.ceil((hi - lo) / pitch).astype(int) + 1
    idx = comp[np.isin(labels[comp], pending)]
    if not len(idx):
        return None
    if len(idx) > 250000:
        idx = np.random.default_rng(1).choice(idx, 250000, replace=False)
    cen = verts[faces[idx]].mean(axis=1)
    lab = labels[idx]
    axes = [lo[i] + pitch * np.arange(shape[i]) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing='ij'), axis=-1).reshape(-1, 3)
    _d, nn = cKDTree(cen).query(grid, workers=-1)
    L = lab[nn].reshape(shape)
    sig = max(0.5, smooth_mm / pitch)
    pend = [int(k) for k in pending]
    field = np.stack([gaussian_filter((L == k).astype(np.float32), sig) for k in pend])
    L = np.array(pend)[field.argmax(axis=0)]
    vols = {k: int((L == k).sum()) for k in pend}
    order = sorted(pend, key=lambda k: vols[k])             # la plus petite d'abord ; la plus grosse reste
    remaining, out = S, {}
    for k in order[:-1]:
        _jc()
        ind = np.pad((L == k).astype(np.float32), 1)
        if ind.max() < 0.5:
            continue
        sm = gaussian_filter(ind, 0.6)
        v, f, _n, _vals = marching_cubes(sm, min(0.5, 0.9 * float(sm.max())), spacing=(pitch, pitch, pitch))
        v = v + lo - pitch
        if float(np.einsum('ij,ij->', v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])) / 6.0) < 0:
            f = f[:, ::-1]
        v, f, _st = _repair_mesh(v, f)
        H = _solid(v, f)
        if H is None:
            continue
        piece = remaining ^ H
        if piece.is_empty() or piece.volume() < 1.0:
            continue
        out[k] = piece
        remaining = remaining - H
    if remaining.is_empty():
        return None
    out[order[-1]] = remaining
    return {k: _unsolid(m) for k, m in out.items()}


def _split_body_by_planes(verts, faces, f_ids, coords, labels, comp, greedy=False, spec=None, stats=None):
    """Corps peint de plusieurs couleurs : on coupe le VOLUME plein par un plan passant par la frontière de chaque zone (coupe plane, pièces pleines
    et non des coques creuses). {couleur: (sommets, faces)} ; None si la frontière n'est pas assez plane (on retombe alors sur les coques).
    `greedy` (mode régions) : à chaque tour on détache la plus petite zone dont la frontière avec celles qui restent est plane, quel que soit l'ordre ;
    avec `spec`, un tenon carré est planté dans la face de coupe de la pièce qui reste et un trou y répond dans la pièce détachée (stats['pegs'] les compte)."""
    _jc()
    used, inv = np.unique(faces[comp], return_inverse=True)
    v, f, _st = _repair_mesh(verts[used], inv.reshape(-1, 3))
    S = _solid(v, f)
    if S is None:
        return None
    labs = labels[comp]
    ks = [int(k) for k in np.unique(labs)]
    ks.sort(key=lambda k: -int((labs == k).sum()))

    def plane_for(k, others):
        fk, fo = comp[labs == k], comp[np.isin(labs, others)]
        bd = np.array(sorted(set(f_ids[fk].ravel().tolist()) & set(f_ids[fo].ravel().tolist())))
        if len(bd) < 3:
            return None
        P = coords[bd]
        c = P.mean(axis=0)
        _u, sv, vt = np.linalg.svd(P - c, full_matrices=False)
        n = vt[2] / (np.linalg.norm(vt[2]) or 1.0)
        if sv[2] > 0.15 * sv[0]:
            return None
        side = float(np.dot(verts[faces[fk]].reshape(-1, 3).mean(axis=0) - c, n))
        return (n if side >= 0 else -n), c

    def best_plane(k, others, min_acc=0.95):
        """Plan qui sépare au mieux les faces de `k` (au-dessus) de celles de `others` (en dessous) : normale = axes de la zone, seuil = meilleur taux de faces bien classées."""
        ik, io = comp[labs == k], comp[np.isin(labs, others)]
        if not len(ik) or not len(io):
            return None
        tri = verts[faces]
        cen = tri.mean(axis=1)
        ar = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2.0
        ia = np.concatenate([ik, io])
        isk = np.concatenate([np.ones(len(ik), bool), np.zeros(len(io), bool)])
        P, A = cen[ia], ar[ia]
        mk = (P[isk] * A[isk, None]).sum(axis=0) / (A[isk].sum() or 1.0)
        mo = (P[~isk] * A[~isk, None]).sum(axis=0) / (A[~isk].sum() or 1.0)
        cands = [mk - mo]
        _u, _s, vt = np.linalg.svd(P - P.mean(axis=0), full_matrices=False)
        cands += [vt[0], vt[1], vt[2]]
        best, tot = None, float(A.sum()) or 1.0
        for n in cands:
            _jc()
            ln = float(np.linalg.norm(n))
            if ln < 1e-9:
                continue
            n = n / ln
            for sg in (1.0, -1.0):
                _jc()
                nn = n * sg
                sc = P @ nn
                o = np.argsort(sc)
                ak, ao = A[o] * isk[o], A[o] * (~isk[o])
                # seuil entre o[i] et o[i+1] : bien classé = zone k au-dessus + autres en dessous
                good = (ao.cumsum() + (ak.sum() - ak.cumsum()))
                i = int(np.argmax(good[:-1])) if len(good) > 1 else 0
                acc = float(good[i]) / tot
                if best is None or acc > best[2]:
                    t = 0.5 * (sc[o[i]] + sc[o[min(i + 1, len(o) - 1)]])
                    best = (nn, P.mean(axis=0) + nn * (t - float(P.mean(axis=0) @ nn)), acc)
        return best if best is not None and best[2] >= min_acc else None

    def peel(remaining, n, c):
        level = float(np.dot(n, c))
        above, below = remaining.split_by_plane(n.tolist(), level)
        if above.is_empty() or below.is_empty():
            return None
        if above.volume() < 8.0:                           # reflet minuscule : on creuse un peu plus pour avoir au moins 0,5 mm d'épaisseur (imprimable)
            pa = np.array(above.to_mesh().vert_properties[:, :3], dtype=float)
            depth = float((pa @ n).max() - level)
            if depth < 0.5:
                a2, b2 = remaining.split_by_plane(n.tolist(), level - (0.5 - depth))
                if not a2.is_empty() and not b2.is_empty():
                    above, below, level = a2, b2, level - (0.5 - depth)
        return above, below, level

    remaining, out, down = S, {}, {}
    if greedy:
        pending = list(reversed(ks))                       # la plus petite d'abord
        while len(pending) > 1:
            _jc()
            done = False
            for k in pending:
                _jc()
                pl = plane_for(k, [x for x in pending if x != k])
                if pl is None:
                    continue
                res = peel(remaining, *pl)
                if res is None:
                    continue
                above, below, level = res
                if spec is not None:
                    try:
                        below, above, made = _seat_pegs(below, above, pl[0], level, **spec)
                        if stats is not None:
                            stats['pegs'] = stats.get('pegs', 0) + made
                    except Exception:
                        pass
                out[k], remaining = above, below
                down[k] = -pl[0]
                pending.remove(k)
                done = True
                break
            if not done:                                   # aucune frontière plane : meilleur plan de séparation (plus fidèle aux zones), s'il est assez juste
                best = None
                for k in pending:
                    _jc()
                    cand = best_plane(k, [x for x in pending if x != k])
                    if cand is not None and (best is None or cand[2] > best[1][2]):
                        best = (k, cand)
                res = None
                if best is not None:
                    k, (n, c, _acc) = best
                    res = peel(remaining, n, c)
                if res is None:                            # modèle organique : partition du volume par zones (frontières lissées)
                    vox = _split_solid_voxels(remaining, verts, faces, comp, labels, pending)
                    if vox is None:
                        return None
                    if stats is not None:
                        stats['voxel'] = stats.get('voxel', 0) + len(vox)
                    pieces = {k2: _unsolid(m) if not isinstance(m, tuple) else m for k2, m in out.items()}
                    for k2, (vv, ff) in vox.items():
                        _jc()
                        pieces[k2] = (vv, ff)
                        d = _down_for(vv, ff)
                        if d is not None:
                            down[k2] = d
                    return pieces, down
                above, below, level = res
                if spec is not None:
                    try:
                        below, above, made = _seat_pegs(below, above, n, level, **spec)
                        if stats is not None:
                            stats['pegs'] = stats.get('pegs', 0) + made
                    except Exception:
                        pass
                out[k], remaining = above, below
                down[k] = -n
                pending.remove(k)
        out[pending[0]] = remaining
        return {k: _unsolid(m) for k, m in out.items()}, down
    for k in ks[1:]:
        _jc()
        pl = plane_for(k, [x for x in ks if x != k])
        if pl is None:
            return None
        res = peel(remaining, *pl)
        if res is None:
            return None
        out[k], remaining = res[0], res[1]
        down[k] = -pl[0]                                   # sa face de coupe (plane) vers le plateau
    out[ks[0]] = remaining
    return {k: _unsolid(m) for k, m in out.items()}, down


def _rot_down(d):
    """Matrice de rotation qui amène le vecteur d sur -Z (la face de coupe vers le plateau)."""
    a = np.asarray(d, dtype=float); a = a / (np.linalg.norm(a) or 1.0)
    b = np.array([0.0, 0.0, -1.0])
    c = float(a @ b)
    if c > 1 - 1e-9:
        return np.eye(3)
    if c < -1 + 1e-9:
        return np.diag([1.0, -1.0, -1.0])
    v = np.cross(a, b)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


def _trim_rim(v, f, max_frac=0.02, max_faces=250000):
    """Bord vif plan (orbite d'un œil, ouverture d'un creux) : son pourtour est déchiqueté dans le modèle d'origine. On le coupe par un plan
    juste en dessous du bruit : face droite et lisse. Renvoie ((sommets, faces), direction de la face coupée) ou None."""
    if len(f) > max_faces:
        return None
    import trimesh
    m = trimesh.Trimesh(v, f, process=False)
    sel = m.face_adjacency_angles > np.radians(40)
    vs = np.unique(m.face_adjacency_edges[sel])
    if len(vs) < 40:
        return None
    P = v[vs]
    c = P.mean(axis=0)
    _u, sv, vt = np.linalg.svd(P - c, full_matrices=False)
    if sv[2] > 0.08 * sv[0] or float(np.ptp((P - c) @ vt[0])) < 6.0:
        return None
    n = vt[2] / (np.linalg.norm(vt[2]) or 1.0)
    if float(np.dot(v.mean(axis=0) - c, n)) < 0:
        n = -n                                             # n pointe vers le corps
    S = _solid(v, f)
    if S is None:
        return None
    off = float(np.dot(n, c)) + float(((P - c) @ n).max())
    above, _below = S.split_by_plane(n.tolist(), off)
    if above.is_empty() or S.volume() - above.volume() > max_frac * S.volume():
        return None
    return _unsolid(above), -n


def _bbox_inside(a, b, tol=0.5):
    """Vrai si la boîte `a` est (presque) entièrement contenue dans la boîte `b` : pièce imbriquée dans une autre (pupille dans l'œil)."""
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    return bool(np.all(a[:3] >= b[:3] - tol) and np.all(a[3:] <= b[3:] + tol))


def carve_seats(solids, region_color, clearance=0.15, min_volume=2.0, depth_pct=25.0, spec=None):
    """Deux pièces de couleurs différentes qui s'interpénètrent (œuf dans l'orbite, corne dans la tête…), taillées COMME AU CUTTER :
    la petite pièce est tranchée par un plan plat à sa base (la partie enfouie, cachée, est supprimée) ; la grande est creusée de la forme de ce
    qui reste (agrandie du jeu), avec un fond plan. Au contact : un plan et les parois lisses de la petite pièce, jamais la texture de l'autre.
    Renvoie ({région creusée ou tranchée}, {région tranchée : direction de sa face plane}) ; solids est mis à jour."""
    _jc()
    orig = dict(solids)
    ids = sorted(r for r in orig if orig[r].volume() >= 0.5)     # éclats sans volume : ignorés (écartés plus loin), ce qui évite des centaines d'intersections inutiles
    boxes = {r: orig[r].bounding_box() for r in ids}
    touched, down, pegs, pegged = [], {}, 0, set()
    pairs = []
    for i, a in enumerate(ids):
        _jc()
        for b in ids[i + 1:]:
            _jc()
            if region_color[a] == region_color[b] or not _bbox_overlap(boxes[a], boxes[b]):
                continue
            inter = orig[a] ^ orig[b]
            sv = min(orig[a].volume(), orig[b].volume())
            if inter.volume() >= min_volume or (inter.volume() >= 0.5 and sv >= 3.0):   # petites pièces (griffes…) : contact plus faible accepté
                pairs.append((inter.volume(), a, b, inter))
            elif sv >= 3.0 and sv < 60.0:                    # pièce qui ne fait que TOUCHER l'autre (griffe posée sur l'orteil) : contact mesuré en la gonflant de 0,5 mm
                sa, ba = (a, b) if orig[a].volume() <= orig[b].volume() else (b, a)
                bb = np.asarray(boxes[sa], dtype=float); ctr = (bb[:3] + bb[3:]) / 2.0
                grown = orig[sa].translate((-ctr).tolist()).scale([1.0 + 0.5 / max(float((bb[3:] - bb[:3]).min()) / 2.0, 0.5)] * 3).translate(ctr.tolist())
                inter = grown ^ orig[ba]
                if inter.volume() >= 0.3:
                    pairs.append((inter.volume(), a, b, inter))
    for _vol, a, b, inter in sorted(pairs, key=lambda x: -x[0]):          # le plus gros contact d'abord : c'est lui qui reçoit le tenon
        _jc()
        if True:
            small, big = (a, b) if orig[a].volume() <= orig[b].volume() else (b, a)
            pts = np.array(inter.to_mesh().vert_properties[:, :3], dtype=float)
            c = pts.mean(axis=0)
            sm = np.array(solids[small].to_mesh().vert_properties[:, :3], dtype=float)
            n = sm.mean(axis=0) - c                          # sens dans lequel la petite pièce sort de la grande
            if np.linalg.norm(n) < 1e-3:
                continue
            n = n / np.linalg.norm(n)
            pr = (pts - c) @ n
            level = float(np.dot(n, c)) + float(pr.min() + depth_pct / 100.0 * (pr.max() - pr.min()))     # plan à 25 % de l'épaisseur enfouie
            top, _bottom = solids[small].split_by_plane(n.tolist(), level)
            if top.is_empty() or top.volume() < 0.3 * solids[small].volume():
                top = solids[small]                          # trop peu de matière au-dessus du plan : on garde la pièce entière
            else:
                solids[small] = top
                down[small] = -n                             # face plane de la petite pièce = dessous (vers le plateau)
                if small not in touched:
                    touched.append(small)
            bb = np.asarray(top.bounding_box(), dtype=float)
            ctr = (bb[:3] + bb[3:]) / 2.0
            half = float(((bb[3:] - bb[:3]) / 2.0).min())
            f = 1.0 + clearance / max(half, 0.5)
            cutter = top.translate((-ctr).tolist()).scale((f, f, f)).translate(ctr.tolist())
            res = solids[big] - cutter
            if res.is_empty() or res.volume() < 0.2 * solids[big].volume():
                continue
            nested = any(o != small and orig[o].volume() > orig[small].volume() and region_color[o] != region_color[small] and region_color[o] != region_color[big]
                         and _bbox_inside(boxes[small], boxes[o]) for o in ids)
            if spec and small in down and small not in pegged and not nested:   # UN seul tenon par pièce rapportée (corne, œil…), sur son plus gros contact
                pegged.add(small)
                # tenons de positionnement : sur le fond du logement (grande pièce), trou dans la base plane de la petite
                try:
                    res, top, k = _seat_pegs(res, top, n, level, **spec)
                    if k:
                        solids[small] = top
                        pegs += k
                except Exception:
                    pass
            solids[big] = res
            if big not in touched:
                touched.append(big)
    return touched, down, pegs


def _seat_pegs(big, small, n, level, size=0.0, length=0.0, clearance=0.2):
    """Un ou deux tenons carrés plantés dans le fond plan du logement de `big`, et les trous correspondants (avec jeu) dans la base plane de `small`.
    Renvoie (big, small, nombre de tenons)."""
    _jc()
    pts = np.array(small.to_mesh().vert_properties[:, :3], dtype=float)
    base = pts[(pts @ n) - level < (0.4 if np.ptp(pts @ n) > 3.0 else 0.25)]
    if len(base) < 3:
        return big, small, 0
    c0 = base.mean(axis=0)
    c0 = c0 + n * (level - float(c0 @ n))
    _u, _s, vt = np.linalg.svd(base - base.mean(axis=0), full_matrices=False)
    e1 = vt[0] - n * float(vt[0] @ n)
    e1 = e1 / (np.linalg.norm(e1) or 1.0)
    ext1 = float(np.ptp((base - c0) @ e1)); ext2 = float(np.ptp((base - c0) @ (np.cross(n, e1))))
    side = float(size) if size and size > 0 else min(max(0.4 * min(ext1, ext2), 1.0), 4.0)
    if min(ext1, ext2) < side + 0.9:
        return big, small, 0
    ln = float(length) if length and length > 0 else min(max(side * 1.1, 1.6), 5.0)
    embed, bevel = 1.5, min(0.5, side / 4.0)
    frame = _frame(e1, np.cross(n, e1), n)
    offs = [0.0]                                             # un seul tenon, centré
    made = 0
    for off in offs:
        _jc()
        spot = c0 + e1 * off
        peg = _place(_square_peg(side, ln, embed, bevel), frame, spot)
        hole = _place(_square_hole(side + 2 * clearance, ln + 0.5, 0.3), frame, spot)
        p_in = _place(_square_hole(side * 0.9, embed, 0.0).translate([0, 0, -embed]), frame, spot)
        p_out = _place(_square_hole(side * 0.9, ln * 0.8, 0.0), frame, spot)
        if (big ^ p_in).volume() < 0.7 * p_in.volume() or (small ^ p_out).volume() < 0.7 * p_out.volume():
            continue
        big, small = big + peg, small - hole
        made += 1
    return big, small, made


# ── Mode « régions » : découpe de la géométrie en parties (moteur partagé avec le plugin « Split by region ») ──

MAX_WORK = 150000         # faces du maillage de travail du mode « régions » (au-delà : version allégée)
MAX_PARTS = 12            # parties maximum du mode « régions »
_CREASE = {'low': 0.15, 'medium': 0.5, 'high': 1.5}    # coût d'un creux, en fraction de la taille du modèle par tour complet de 180°


def _face_pairs(f):
    """Paires de faces voisines (partageant une arête) : deux tableaux (a, b)."""
    nv = int(f.max()) + 1
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    fid = np.tile(np.arange(len(f)), 3)
    key = e[:, 0].astype(np.int64) * nv + e[:, 1]
    order = np.argsort(key, kind='stable')
    ks, fs = key[order], fid[order]
    same = ks[:-1] == ks[1:]
    return fs[:-1][same], fs[1:][same]


def _geometry(v, f):
    tri = v[f]
    cen = tri.mean(axis=1)
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(cr, axis=1)
    area = ln / 2.0
    nrm = cr / np.maximum(ln, 1e-12)[:, None]
    return cen, nrm, area


def _make_graph(v, f, strength):
    """Graphe pondéré des faces : coût = distance entre centres + force × taille du modèle × angle de l'arête / 180° (un creux compte 4 fois plus qu'un bord convexe).
    Le total le long d'un chemin est le virage cumulé de la surface : il ne dépend pas de la finesse du maillage, et un creux franc coûte cher d'un coup.
    Renvoie dict(graph, cen, area, comp, ncomp, pairs)."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    cen, nrm, area = _geometry(v, f)
    a, b = _face_pairs(f)
    d = np.linalg.norm(cen[a] - cen[b], axis=1)
    theta = np.arccos(np.clip((nrm[a] * nrm[b]).sum(axis=1), -1.0, 1.0))
    concave = ((cen[b] - cen[a]) * nrm[a]).sum(axis=1) > 1e-9
    term = theta / math.pi * np.where(concave, 1.0, 0.25)
    w = np.maximum(d + strength * math.sqrt(float(area.sum())) * term, 1e-9)
    n = len(f)
    g = csr_matrix((w, (a, b)), shape=(n, n))
    ncomp, comp = connected_components(g, directed=False)
    return {'graph': g, 'cen': cen, 'area': area, 'comp': comp, 'ncomp': int(ncomp), 'pairs': (a, b), 'theta': theta, 'concave': concave}


def _dijkstra(graph, seeds):
    from scipy.sparse.csgraph import dijkstra
    dist, _pred, src = dijkstra(graph, directed=False, indices=np.asarray(seeds, dtype=np.int64), min_only=True, return_predecessors=True)
    return dist, src


def _labels_from_seeds(G, seeds):
    n = len(G['area'])
    dist, src = _dijkstra(G['graph'], seeds)
    lookup = np.full(n, -1, dtype=np.int64)
    lookup[np.asarray(seeds)] = np.arange(len(seeds))
    reach = np.isfinite(dist) & (src >= 0)
    lab = np.full(n, -1, dtype=np.int64)
    lab[reach] = lookup[src[reach]]
    if not reach.all():                                # pièces sans graine : prennent la partie la plus proche dans l'espace
        from scipy.spatial import cKDTree
        _d, k = cKDTree(G['cen'][reach]).query(G['cen'][~reach])
        lab[~reach] = lab[np.where(reach)[0][k]]
    return lab


_TCONC = {'low': 55.0, 'medium': 35.0, 'high': 20.0}   # angle (°) à partir duquel un creux sépare deux régions
_TCONV = 70.0                                              # angle (°) d'un bord convexe franc (arête de cube) qui sépare deux régions


def _charts(G, crease):
    """Plaques lisses : composantes connexes des faces une fois coupées aux creux francs et aux arêtes vives."""
    _jc()
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    a, b = G['pairs']
    deg = np.degrees(G['theta'])
    barrier = np.where(G['concave'], deg >= _TCONC.get(crease, _TCONC['medium']), deg >= _TCONV)
    keep = ~barrier
    n = len(G['area'])
    _c, lab = connected_components(coo_matrix((np.ones(int(keep.sum()), dtype=np.int8), (a[keep], b[keep])), shape=(n, n)), directed=False)
    return lab.astype(np.int64)


def _merge_charts(G, lab, target, min_share=0.004):
    """Fusionne les plaques : la plus petite d'abord, dans le voisin avec lequel elle partage la frontière la plus longue et la moins vive,
    jusqu'à `target` plaques (et sans plaque minuscule). Une pièce isolée rejoint la plaque la plus proche."""
    _jc()
    area, cen = G['area'], G['cen']
    a, b = G['pairs']
    k = int(lab.max()) + 1
    A = np.bincount(lab, weights=area, minlength=k).astype(float)
    total = float(A.sum()) or 1.0
    w = (1.0 - G['theta'] / math.pi)
    nb = [dict() for _ in range(k)]
    la, lb = lab[a], lab[b]
    for x, y, ww in zip(la.tolist(), lb.tolist(), w.tolist()):
        _jc()
        if x != y:
            nb[x][y] = nb[x].get(y, 0.0) + ww
            nb[y][x] = nb[y].get(x, 0.0) + ww
    alive = np.ones(k, dtype=bool)
    ctr = np.zeros((k, 3))
    np.add.at(ctr, lab, cen * area[:, None])
    parent = np.arange(k)
    count = k
    while count > 1:
        _jc()
        cand = np.where(alive, A, np.inf)
        i = int(np.argmin(cand))
        if count <= target and A[i] >= min_share * total:
            break
        if nb[i]:
            j = max(nb[i], key=nb[i].get)
        else:
            c = ctr / np.maximum(A, 1e-12)[:, None]
            d = np.linalg.norm(c - c[i], axis=1)
            d[~alive] = np.inf
            d[i] = np.inf
            j = int(np.argmin(d))
        for y, ww in nb[i].items():
            _jc()
            if y != j:
                nb[y].pop(i, None)
                nb[y][j] = nb[y].get(j, 0.0) + ww
                nb[j][y] = nb[j].get(y, 0.0) + ww
        nb[j].pop(i, None)
        nb[i] = {}
        A[j] += A[i]
        ctr[j] += ctr[i]
        alive[i] = False
        parent[i] = j
        count -= 1
    root = parent.copy()
    for x in range(k):                                   # suit les fusions jusqu'à la plaque finale
        _jc()
        r = x
        while root[r] != r:
            _jc()
            r = root[r]
        root[x] = r
    return root[lab]


def _split_chart(Gp, lab, target):
    """Moins de plaques que de parties demandées (modèle sans creux franc) : on coupe la plus grande en deux autour de deux graines très éloignées (distances géodésiques), jusqu'à `target`."""
    area = Gp['area']
    lab = lab.copy()
    n = int(lab.max()) + 1
    while n < target:
        A = np.bincount(lab, weights=area, minlength=n)
        i = int(np.argmax(A))
        idx = np.where(lab == i)[0]
        if len(idx) < 4:
            break
        sub = Gp['graph'][idx][:, idx]
        d0, _ = _dijkstra(sub, [0])
        d0 = np.where(np.isfinite(d0), d0, -1.0)
        s1 = int(np.argmax(d0))
        d1, _ = _dijkstra(sub, [s1])
        d1 = np.where(np.isfinite(d1), d1, -1.0)
        s2 = int(np.argmax(d1))
        if s1 == s2:
            break
        da, _ = _dijkstra(sub, [s1])
        db, _ = _dijkstra(sub, [s2])
        side = np.where(np.isfinite(da), da, 1e30) > np.where(np.isfinite(db), db, 1e30)
        if side.all() or not side.any():
            break
        lab[idx[side]] = n
        n += 1
    return lab


def _smooth(lab, pairs, n_parts, rounds=2):
    """Retire les faces isolées le long des frontières : une face dont au moins deux voisins sont d'une autre partie, et aucun de la sienne, change de partie."""
    a, b = pairs
    for _ in range(rounds):
        cnt = np.zeros((len(lab), n_parts), dtype=np.int32)
        np.add.at(cnt, (a, lab[b]), 1)
        np.add.at(cnt, (b, lab[a]), 1)
        maj = cnt.argmax(axis=1)
        own = cnt[np.arange(len(lab)), lab]
        flip = (cnt[np.arange(len(lab)), maj] >= 2) & (own == 0) & (maj != lab)
        if not flip.any():
            break
        lab = np.where(flip, maj, lab)
    return lab


def _shell_labels(f, area):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    nv = int(f.max()) + 1
    a = np.concatenate([f[:, 0], f[:, 1], f[:, 2]])
    b = np.concatenate([f[:, 1], f[:, 2], f[:, 0]])
    _n, vc = connected_components(coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(nv, nv)), directed=False)
    fc = vc[f[:, 0]]
    order = np.argsort(-np.bincount(fc, weights=area))
    rank = np.empty(len(order), dtype=np.int64)
    rank[order] = np.arange(len(order))
    return rank[fc], len(order)


def _renumber(lab):
    """Numéros de parties consécutifs (une graine peut avoir perdu toute sa région). Renvoie (étiquettes, nombre, numéros d'origine conservés)."""
    used = np.unique(lab)
    remap = np.full(int(lab.max()) + 1, -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return remap[lab], len(used), used


def _simplify_work(v, f):
    if len(f) <= MAX_WORK:
        return v, f
    try:
        import fast_simplification
        v2, f2 = fast_simplification.simplify(np.asarray(v, dtype=np.float32), np.asarray(f, dtype=np.int32), target_reduction=min(0.97, 1.0 - MAX_WORK / float(len(f))))
        v2, f2 = np.asarray(v2, dtype=float), np.asarray(f2, dtype=np.int64)
        keep = (f2[:, 0] != f2[:, 1]) & (f2[:, 1] != f2[:, 2]) & (f2[:, 0] != f2[:, 2])
        f2 = f2[keep]
        used, inv = np.unique(f2, return_inverse=True)
        return v2[used], np.asarray(inv).reshape(-1, 3)
    except Exception:
        if len(f) <= 4 * MAX_WORK:
            return v, f
        raise ValueError("Modèle trop détaillé pour ce plugin (fast-simplification absent) : réduisez-le d'abord")


def _graph_for(m, crease):
    strength = 0.0 if crease is None else _CREASE.get(crease, _CREASE['medium'])
    if strength not in m['graphs']:
        m['graphs'][strength] = _make_graph(m['wv'], m['wf'], strength)
    return m['graphs'][strength]


def segment(m, mode, parts, crease, seeds=None, rounds=2):
    """Découpe le maillage de travail de `m`. Renvoie dict(labels (par face de travail), n, seeds, share (% de surface par partie))."""
    _jc()
    G = _graph_for(m, crease)
    area = G['area']
    if mode == 'shells':
        lab, n = _shell_labels(m['wf'], area)
        if n > MAX_PARTS:
            raise ValueError(f"Ce modèle compte {n} pièces séparées (maximum {MAX_PARTS}) : choisissez un autre mode")
        used = []
    else:
        used = []
        if mode == 'seeds':
            used = [int(s) for s in (seeds or [])]
            if not used or len(set(used)) != len(used) or any(s < 0 or s >= len(area) for s in used):
                raise ValueError("Posez au moins une graine sur le modèle")
            if len(used) > MAX_PARTS:
                raise ValueError(f"Trop de parties (maximum {MAX_PARTS})")
        if mode == 'seeds':
            lab = _labels_from_seeds(G, used)
        else:
            lab = np.unique(_merge_charts(G, _charts(G, crease), parts), return_inverse=True)[1].astype(np.int64)
            if int(lab.max()) + 1 < parts:
                lab = _split_chart(_graph_for(m, None), lab, parts)
        lab = _smooth(lab, G['pairs'], int(lab.max()) + 1, rounds)
        lab, n, kept = _renumber(lab)
        if mode == 'seeds':
            used = [used[int(i)] for i in kept]          # les graines suivent la numérotation
    share = [100.0 * float(area[lab == i].sum()) / (float(area.sum()) or 1.0) for i in range(n)]
    return {'labels': lab.astype(np.uint8), 'n': n, 'seeds': used, 'share': [round(x, 1) for x in share]}


def _to_full(m, wlab):
    """Partie de chaque face du modèle complet (le maillage de travail est le modèle lui-même s'il est assez léger)."""
    if m['wf'] is m['f'] or len(m['wf']) == len(m['f']) and m['wv'] is m['v']:
        return wlab
    from scipy.spatial import cKDTree
    if 'tree' not in m:
        m['tree'] = cKDTree(_geometry(m['wv'], m['wf'])[0])
    cen, _n, _a = _geometry(m['v'], m['f'])
    _d, k = m['tree'].query(cen)
    return wlab[k]




def _regions_pipeline(mesh, face_rgb, tol, spec, bed_w, bed_d, merge_gap=5.0, greedy=False):
    """Découpe en régions, répare chacune, ajoute les connecteurs demandés, regroupe les morceaux voisins d'une même couleur,
    puis range chaque couleur sur son plateau. Renvoie (objets par couleur {k: [objets]}, bilan de réparation, tient, connecteurs)."""
    _jc()
    labels, colors, _sizes = _group_colors(face_rgb, tol)
    region, region_color, f_ids, coords = _regions(mesh, labels, 1 if greedy else 4)
    verts = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    if greedy:                                              # régions voulues : aucune n'est absorbée (un maillage léger a peu de faces par partie)
        mixed = [comp for comp in _bodies(f_ids) if len(np.unique(labels[comp])) > 1]
    else:
        labels, mixed = _absorb_strays(labels, f_ids, verts=verts, faces=faces)
    region, region_color, f_ids, coords = _regions(mesh, labels, 1 if greedy else 4)
    stats = {'filled': 0, 'open': 0, 'nonmanifold': 0}
    pegstat = {'pegs': 0}
    shells = {}
    orient = {}
    skip = set()
    for comp in mixed:
        _jc()
        try:
            res = _split_body_by_planes(verts, faces, f_ids, coords, labels, comp, greedy, spec if greedy else None, pegstat)
            pieces, pdown = res if res else (None, {})
            regs = {}
            for r in np.unique(region[comp]):
                _jc()
                if r >= 0:
                    regs.setdefault(region_color[r], []).append(int(r))
            if greedy:                                      # une zone peut compter plusieurs régions : la pièce est portée par la première
                if pieces is None or not set(pieces) <= set(regs):
                    continue
            elif pieces is None or any(len(regs.get(k, [])) != 1 for k in pieces) or set(regs) != set(pieces):
                continue
            for k, (v, f) in pieces.items():
                _jc()
                shells[regs[k][0]] = (v, f)
                skip.update(regs[k][1:])
                if k in pdown:
                    orient[regs[k][0]] = pdown[k]
        except Exception as e:
            app_logger.warning(f"[Séparation couleur] coupe plane impossible : {e}")
    for r in range(len(region_color)):
        _jc()
        if r in shells or r in skip:
            continue
        idx = np.nonzero(region == r)[0]
        used, inv = np.unique(faces[idx], return_inverse=True)
        v, f, st = _repair_mesh(verts[used], inv.reshape(-1, 3))
        for k in stats:
            _jc()
            stats[k] += st[k]
        shells[r] = (v, f)
    fixed_orient = set(orient)
    for r in list(shells):
        _jc()
        if r in orient:
            continue
        try:
            res = _trim_rim(*shells[r])
        except Exception as e:
            app_logger.warning(f"[Séparation couleur] bord non redressé : {e}")
            res = None
        if res:
            shells[r], orient[r] = res
    conn = {'made': pegstat['pegs'], 'skipped': 0, 'error': None, 'seats': 0, 'voxel': pegstat.get('voxel', 0)}
    if len(region_color) > 1:
        try:
            solids = {}
            for r, (v, f) in shells.items():
                _jc()
                m = _solid(v, f)
                if m is not None:
                    solids[r] = m
            carved, sdown, pegs = carve_seats(solids, region_color, spec=spec)   # coupes au cutter : base plane de la petite pièce, logement à fond plan, tenons
            conn['seats'] = len(carved)
            conn['made'] += pegs
            changed = set(carved)
            for r, d in sdown.items():
                _jc()
                if r not in fixed_orient:
                    orient[r] = d
            for r in changed:
                _jc()
                shells[r] = _unsolid(solids[r])
        except ImportError:
            conn['error'] = 'manifold3d'
        except Exception as e:
            app_logger.warning(f"[Séparation couleur] logements/connecteurs impossibles : {e}")
            conn['error'] = str(e)
    per_color, fits = {}, True
    for k in range(len(colors)):
        _jc()
        keep, flat = [], []
        for r in range(len(region_color)):
            _jc()
            if region_color[r] != k or r in skip:
                continue
            v, f = shells[r]
            if r in orient:                                 # pièce à face de coupe plane : posée à plat sur le plateau, hors regroupement
                if greedy and abs(float(np.einsum('ij,ij->', v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])) / 6.0)) < 5.0:
                    continue                                # éclat de coupe (moins de 5 mm³) : écarté
                R = _rot_down(orient[r])
                ctr = v.mean(axis=0)
                flat.append(((v - ctr) @ R.T, f))
                continue
            try:
                from scipy.sparse import coo_matrix
                from scipy.sparse.csgraph import connected_components
                n = len(v)
                lab = connected_components(coo_matrix((np.ones(len(f) * 2, dtype=np.int8), (np.concatenate([f[:, 0], f[:, 1]]), np.concatenate([f[:, 1], f[:, 2]]))), shape=(n, n)), directed=False)[1]
                fl = lab[f[:, 0]]
                for c in np.unique(fl):
                    _jc()
                    ff = f[fl == c]
                    vol = abs(float(np.einsum('ij,ij->', v[ff[:, 0]], np.cross(v[ff[:, 1]], v[ff[:, 2]])) / 6.0))
                    if vol > 0.5 or len(ff) > 400:      # éclats de coupe sans volume : écartés
                        if len(np.unique(fl)) == 1:
                            keep.append((v, f))
                        else:
                            u, inv = np.unique(ff, return_inverse=True)
                            keep.append((v[u], inv.reshape(-1, 3)))
            except Exception:
                keep.append((v, f))
        sh = _group_shells(keep, merge_gap) + flat
        if not sh:
            continue
        objs, ok = _arrange(sh, bed_w, bed_d)
        per_color[k] = objs
        fits = fits and ok
    return per_color, stats, fits, conn


def build_3mf(plates, bed_w, bed_d, out_path, plate_names=None):
    """Écrit le 3MF. `plates` = liste de plateaux ; chaque plateau = liste de dict
    {name, vertices (Nx3, centrés en XY, z ≥ 0), faces (Mx3), cx, cy (centre dans le plateau, mm)}."""
    _jc()
    count = len(plates)
    objects_xml, build_xml, config_objects, config_plates, materials_xml = [], [], [], [], []
    obj_id = 0
    filaments = []   # couleurs distinctes, dans l'ordre : le n° de filament d'un objet = sa position ici (1, 2, 3…)
    for pieces in plates:
        _jc()
        for piece in pieces:
            _jc()
            if piece.get('rgb') is not None and tuple(int(x) for x in piece['rgb']) not in filaments:
                filaments.append(tuple(int(x) for x in piece['rgb']))
    for p_idx, pieces in enumerate(plates):
        _jc()
        ox, oy = _plate_origin(p_idx, count, bed_w, bed_d)
        instances = []
        for piece in pieces:
            _jc()
            obj_id += 1
            v = piece['vertices']
            f = piece['faces']
            verts = ''.join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in v)
            tris = ''.join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in f)
            name = quoteattr(piece['name'])
            pid = ''
            if piece.get('rgb') is not None:     # couleur de la pièce (séparation par couleur) : matière de base 3MF, lue aussi par Stellio
                mat_id = 100000 + obj_id
                r, g_, b_ = (int(x) for x in piece['rgb'])
                materials_xml.append(f'<basematerials id="{mat_id}"><base name="{r:02X}{g_:02X}{b_:02X}" displaycolor="#{r:02X}{g_:02X}{b_:02X}FF"/></basematerials>')
                pid = f' pid="{mat_id}" pindex="0"'
            objects_xml.append(f'<object id="{obj_id}" name={name}{pid} type="model"><mesh><vertices>{verts}</vertices>'
                               f'<triangles>{tris}</triangles></mesh></object>')
            tx, ty = ox + piece['cx'], oy + piece['cy']
            build_xml.append(f'<item objectid="{obj_id}" transform="1 0 0 0 1 0 0 0 1 {tx:.4f} {ty:.4f} 0" printable="1"/>')
            ext = ''
            if piece.get('rgb') is not None:
                ext = f'<metadata key="extruder" value="{filaments.index(tuple(int(x) for x in piece["rgb"])) + 1}"/>'
            config_objects.append(f'<object id="{obj_id}"><metadata key="name" value={name}/>{ext}</object>')
            instances.append(f'<model_instance><metadata key="object_id" value="{obj_id}"/>'
                             f'<metadata key="instance_id" value="0"/><metadata key="identify_id" value="{obj_id}"/></model_instance>')
        config_plates.append(f'<plate><metadata key="plater_id" value="{p_idx + 1}"/>'
                             f'<metadata key="plater_name" value={quoteattr((plate_names[p_idx] if plate_names and p_idx < len(plate_names) else "") or "")}/><metadata key="locked" value="false"/>'
                             + ''.join(instances) + '</plate>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
             'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" requiredextensions="">\n'
             '<metadata name="Application">Stellio</metadata>\n<metadata name="BambuStudio:3mfVersion">1</metadata>\n'
             '<resources>' + ''.join(materials_xml) + ''.join(objects_xml) + '</resources>\n<build>' + ''.join(build_xml) + '</build>\n</model>')
    config = '<?xml version="1.0" encoding="UTF-8"?>\n<config>' + ''.join(config_objects) + ''.join(config_plates) + '</config>'
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                     '<Default Extension="config" ContentType="text/xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    project = None
    if filaments:
        import json
        w, d = int(round(bed_w)), int(round(bed_d))
        project = json.dumps({'from': 'project', 'filament_colour': ['#%02X%02X%02X' % c for c in filaments],
                              'filament_type': ['PLA'] * len(filaments),
                              'printable_area': ['0x0', f'{w}x0', f'{w}x{d}', f'0x{d}']}, indent=2)
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('3D/3dmodel.model', model)
        zf.writestr('Metadata/model_settings.config', config)
        if project:
            zf.writestr('Metadata/project_settings.config', project)
    return obj_id


def _is_unc(path):
    return path.startswith('//') or path.startswith('\\\\')


def _unc(path):
    return path.replace('\\', '/')


def _clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', (name or '').strip()).strip('. ')
    if name.lower().endswith('.3mf'):
        name = name[:-4].rstrip('. ')
    return name[:120]


def _dest_dir(paths, source_id, sub_rel):
    """Dossier de sortie : source + sous-dossier choisis dans la fenêtre ; sinon dossier du premier fichier
    (si on peut y écrire) ; sinon dossier de données de Stellio. Les dossiers réseau (SMB) sont acceptés.
    Lève ValueError si le choix est invalide."""
    folder = None
    if source_id:
        conn = get_db()
        try:
            row = conn.execute("SELECT path FROM sources WHERE id = ? AND user_id = ?", (source_id, session['user_id'])).fetchone()
        finally:
            conn.close()
        if not row or not row['path']:
            raise ValueError("Dossier de destination introuvable")
        base = row['path']
        parts = [x for x in (sub_rel or '').replace('\\', '/').strip('/').split('/') if x]
        if any(x in ('.', '..') or re.search(r'[<>:"|?*]', x) for x in parts):
            raise ValueError("Dossier de destination invalide")
        if _is_unc(base):
            folder = '/'.join([_unc(base).rstrip('/')] + parts)
            kw = _smb_kwargs_for_path(session['user_id'], folder)
            if kw is None:
                raise ValueError("Source réseau introuvable pour ce dossier")
            smbclient.makedirs(folder, exist_ok=True, **kw)
        else:
            folder = os.path.join(base, *parts)
            os.makedirs(folder, exist_ok=True)
    if not folder:
        first = paths[0]
        if _is_unc(first):
            folder = _unc(first).rsplit('/', 1)[0]
        else:
            folder = os.path.dirname(first)
            if not (folder and os.path.isdir(folder) and os.access(folder, os.W_OK)):
                folder = os.path.join(DATA_DIR, 'nesting_output')
                os.makedirs(folder, exist_ok=True)
    return folder


def _resolve_dir(source_id, sub_rel):
    """(dossier, parties) d'un sous-dossier d'une source, SANS rien créer. Lève ValueError si le choix est invalide."""
    conn = get_db()
    try:
        row = conn.execute("SELECT path FROM sources WHERE id = ? AND user_id = ?", (source_id, session['user_id'])).fetchone()
    finally:
        conn.close()
    if not row or not row['path']:
        raise ValueError("Source introuvable")
    base = row['path']
    parts = [x for x in (sub_rel or '').replace('\\', '/').strip('/').split('/') if x]
    if any(x in ('.', '..') or re.search(r'[<>:"|?*\x00-\x1f]', x) for x in parts):
        raise ValueError("Dossier invalide")
    if _is_unc(base):
        folder = '/'.join([_unc(base).rstrip('/')] + parts)
        kw = _smb_kwargs_for_path(session['user_id'], folder)
        if kw is None:
            raise ValueError("Source réseau introuvable pour ce dossier")
        return folder, parts, kw
    return os.path.join(base, *parts), parts, None


def api_split_color_folders():
    """Sous-dossiers d'un dossier d'une source (pour choisir où enregistrer, comme pour les téléchargements)."""
    try:
        folder, parts, kw = _resolve_dir(str(request.args.get('source_id') or ''), request.args.get('sub'))
        names = []
        if kw is not None:
            for e in smbclient.scandir(folder, **kw):
                if e.is_dir() and not e.name.startswith(('.', '$')):
                    names.append(e.name)
        else:
            with os.scandir(folder) as it:
                for e in it:
                    if e.is_dir() and not e.name.startswith('.'):
                        names.append(e.name)
        names.sort(key=str.lower)
        return jsonify({"sub": '/'.join(parts), "folders": names[:500], "truncated": len(names) > 500})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Séparation couleur] dossiers illisibles : {e}")
        return jsonify({"error": "Dossier illisible"}), 400


def api_split_color_mkdir():
    """Crée un sous-dossier dans une source (un seul niveau à la fois) et renvoie son chemin relatif."""
    data = request.json or {}
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(data.get('name') or '')).strip('. ')[:80]
    if not name:
        return jsonify({"error": "Nom de dossier invalide"}), 400
    try:
        _f, parts, _kw = _resolve_dir(str(data.get('source_id') or ''), data.get('sub'))
        folder, parts2, kw = _resolve_dir(str(data.get('source_id') or ''), '/'.join(parts + [name]))
        if kw is not None:
            smbclient.makedirs(folder, exist_ok=True, **kw)
        else:
            os.makedirs(folder, exist_ok=True)
        return jsonify({"ok": True, "sub": '/'.join(parts2)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Séparation couleur] création de dossier impossible : {e}")
        return jsonify({"error": "Création du dossier impossible"}), 400


def _out_path(folder, name, count):
    base = _clean_filename(name) or f'fusion_{count}_pieces'
    unc = _is_unc(folder)
    kw = (_smb_kwargs_for_path(session['user_id'], folder) or {}) if unc else {}
    join = (lambda n: _unc(folder).rstrip('/') + '/' + n) if unc else (lambda n: os.path.join(folder, n))
    exists = (lambda p: smbclient.path.exists(p, **kw)) if unc else os.path.exists
    candidate = join(base + '.3mf')
    n = 2
    while exists(candidate):
        candidate = join(f'{base}_{n}.3mf')
        n += 1
    return candidate


def _write_output(plates, bed_w, bed_d, out_path, plate_names=None):
    if not _is_unc(out_path):
        build_3mf(plates, bed_w, bed_d, out_path, plate_names)
        return
    kw = _smb_kwargs_for_path(session['user_id'], out_path)
    if kw is None:
        raise ValueError("Source réseau introuvable pour ce dossier")
    buf = io.BytesIO()
    build_3mf(plates, bed_w, bed_d, buf, plate_names)
    with smbclient.open_file(out_path, mode='wb', **kw) as fh:
        fh.write(buf.getvalue())


# ── Séparer par couleur (1.2.0) : un 3MF multicolore → un 3MF avec un plateau par couleur ──

def _hex(rgb):
    return '#%02X%02X%02X' % tuple(int(x) for x in rgb)


def _group_colors(face_rgb, tolerance):
    """Regroupe les faces par couleur. Renvoie (étiquette par face, couleurs [(r,g,b)], effectifs).
    tolerance (0-100) : des couleurs proches (distance RVB ≤ tolérance) sont fusionnées dans la plus fréquente."""
    uniq, inv, counts = np.unique(np.asarray(face_rgb, dtype=np.int32), axis=0, return_inverse=True, return_counts=True)
    inv = np.asarray(inv).reshape(-1)
    order = np.argsort(-counts, kind='stable')
    reps, remap = [], np.zeros(len(uniq), dtype=np.int32)
    for i in order:
        target = None
        if tolerance > 0:
            for k, r in enumerate(reps):
                if float(np.linalg.norm(uniq[i] - uniq[r])) <= tolerance:
                    target = k
                    break
        if target is None:
            reps.append(int(i))
            target = len(reps) - 1
        remap[i] = target
    labels = remap[inv]
    sizes = np.bincount(labels, minlength=len(reps))
    return labels, [tuple(int(x) for x in uniq[r]) for r in reps], [int(x) for x in sizes]


def _load_colored_mesh(path):
    """Maillage 3MF de TOUS les plateaux, avec la couleur de chaque face (metadata['stellio_face_rgb'])."""
    if _resolve_3mf_plate_mesh is None:
        raise ValueError("Lecture des couleurs 3MF indisponible")
    if _is_unc(path):
        kw = _smb_kwargs_for_path(session['user_id'], path)
        if kw is None:
            raise ValueError("Source réseau introuvable pour ce fichier")
        with smbclient.open_file(_unc(path), mode='rb', share_access='r', **kw) as fh:
            source = fh.read()
    else:
        source = path
    mesh = _resolve_3mf_plate_mesh(source, None, True, None)
    if mesh is None or len(getattr(mesh, 'faces', [])) == 0:
        raise ValueError("Maillage 3MF vide ou illisible")
    rgb = mesh.metadata.get('stellio_face_rgb') if hasattr(mesh, 'metadata') else None
    if rgb is None or len(rgb) != len(mesh.faces):
        raise ValueError("Ce 3MF ne contient aucune information de couleur")
    return mesh, np.asarray(rgb)


def split_mesh_by_color(mesh, face_rgb, tolerance=0.0):
    """Une pièce par couleur : [{'rgb', 'vertices', 'faces', 'count'}], de la plus grande à la plus petite."""
    _jc()
    labels, colors, sizes = _group_colors(face_rgb, tolerance)
    verts = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces)
    out = []
    for k, rgb in enumerate(colors):
        _jc()
        sel = faces[labels == k]
        used, inv = np.unique(sel, return_inverse=True)
        out.append({'rgb': rgb, 'vertices': verts[used], 'faces': inv.reshape(-1, 3), 'count': int(sizes[k]), 'label': k})
    return out


def _preview(pieces, max_tris=30000):
    """Aperçu léger pour la page : triangles de chaque couleur, recentrés et quantifiés en entiers 16 bits (base64).
    Au-delà de `max_tris` au total, chaque couleur est échantillonnée régulièrement (le rendu reste fidèle à l'échelle d'une vignette)."""
    _jc()
    import numpy as np
    allv = np.vstack([np.asarray(p['vertices'], dtype=float) for p in pieces])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    center = np.array([(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, lo[2]])
    half = max(float(np.max(hi - lo)) / 2.0, 1e-6)
    q = 12000.0 / half
    total = sum(len(p['faces']) for p in pieces) or 1
    out = []
    for p in pieces:
        _jc()
        f = np.asarray(p['faces'])
        v = np.asarray(p['vertices'], dtype=float)
        budget = max(300, int(max_tris * len(f) / total))
        if len(f) > budget:
            f = f[np.linspace(0, len(f) - 1, budget).astype(int)]
        tri = np.clip(np.round((v[f] - center) * q), -32000, 32000).astype('<i2')
        out.append({"hex": _hex(p['rgb']), "tris": base64.b64encode(tri.tobytes()).decode('ascii')})
    return {"q": q, "extent": [float(x) for x in (hi - lo)], "pieces": out}


def _preview_or_none(pieces):
    try:
        return _preview(pieces)
    except Exception as e:
        app_logger.warning(f"[Séparation couleur] aperçu indisponible : {e}")
        return None


_REGION_COLORS = ('#E6194B', '#3CB44B', '#4363D8', '#F58231', '#911EB4', '#42D4F4', '#F032E6', '#BFEF45', '#FABED4', '#469990', '#DCBEFF', '#9A6324')
_LOCK = threading.Lock()
_MODELS = OrderedDict()
_RESULTS = OrderedDict()


class _Mesh:
    def __init__(self, v, f):
        self.vertices, self.faces = v, f


def _load_geometry(path):
    """Sommets et faces d'un 3MF (tous les plateaux, couleurs ignorées) ou d'un STL, soudés ; faces dégénérées retirées."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in ('.3mf', '.stl'):
        raise ValueError("Seuls les fichiers 3MF et STL sont pris en charge")
    source = path
    if _is_unc(path):
        kw = _smb_kwargs_for_path(session['user_id'], path)
        if kw is None:
            raise ValueError("Source réseau introuvable pour ce fichier")
        with smbclient.open_file(_unc(path), mode='rb', share_access='r', **kw) as fh:
            source = fh.read()
    if ext == '.3mf':
        if _resolve_3mf_plate_mesh is None:
            raise ValueError("Lecture 3MF indisponible")
        mesh = _resolve_3mf_plate_mesh(source, None, True, None)
    else:
        import trimesh
        mesh = trimesh.load(io.BytesIO(source) if isinstance(source, bytes) else source, file_type='stl', force='mesh')
    if mesh is None or len(getattr(mesh, 'faces', [])) == 0:
        raise ValueError("Maillage vide ou illisible")
    v = np.array(mesh.vertices, dtype=float)
    f = np.array(mesh.faces, dtype=np.int64)
    uniq, inv = np.unique(np.round(v, 4), axis=0, return_inverse=True)
    f = np.asarray(inv).reshape(-1)[f]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    if len(f) == 0:
        raise ValueError("Maillage vide ou illisible")
    used, inv2 = np.unique(f, return_inverse=True)
    return uniq[used], np.asarray(inv2).reshape(-1, 3)


def _region_model(path):
    try:
        st = os.stat(path) if not _is_unc(path) else None
        key = (path, st.st_mtime_ns, st.st_size) if st else (path,)
    except OSError:
        key = (path,)
    with _LOCK:
        if key in _MODELS:
            _MODELS.move_to_end(key)
            return _MODELS[key]
    v, f = _load_geometry(path)
    wv, wf = _simplify_work(v, f)
    m = {'key': key, 'v': v, 'f': f, 'wv': wv, 'wf': wf, 'graphs': {}}
    with _LOCK:
        _MODELS[key] = m
        while len(_MODELS) > 2:
            _MODELS.popitem(last=False)
    return m


_MODES = ('auto', 'shells', 'seeds')
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def _num(data, key, default, lo, hi):
    v = data.get(key)
    try:
        x = float(default if v in (None, '') else v)
    except (TypeError, ValueError):
        raise ValueError(f"Paramètre invalide : {key}")
    return min(max(x, lo), hi)


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode('ascii')


def _params(data):
    """(mode, parties, creux, graines) d'une requête de régions ; `region_mode` (page fusionnée) ou `mode` (routes de régions)."""
    mode = data.get('region_mode') if data.get('region_mode') in _MODES else (data.get('mode') if data.get('mode') in _MODES else 'auto')
    crease = data.get('crease') if data.get('crease') in _CREASE else 'medium'
    parts = int(_num(data, 'parts', 3, 2, MAX_PARTS))
    seeds = []
    if mode == 'seeds':
        raw = data.get('seeds')
        if not isinstance(raw, list):
            raise ValueError("Posez au moins une graine sur le modèle")
        try:
            seeds = [int(x) for x in raw][:MAX_PARTS + 1]
        except (TypeError, ValueError):
            raise ValueError("Graines invalides")
    return mode, parts, crease, seeds


def _segment_cached(m, mode, parts, crease, seeds):
    key = (m['key'], mode, parts if mode == 'auto' else 0, crease if mode != 'shells' else '', tuple(seeds))
    with _LOCK:
        hit = _RESULTS.get(key)
        if hit is not None:
            _RESULTS.move_to_end(key)
            return hit
    r = segment(m, mode, parts, crease, seeds, 5)
    r['full'] = _to_full(m, r['labels'].astype(np.int64))
    with _LOCK:
        _RESULTS[key] = r
        while len(_RESULTS) > 4:
            _RESULTS.popitem(last=False)
    return r


def _region_faces(path, mode='auto', parts=3, crease='medium', seeds=(), palette=None):
    """Maillage complet + couleur (RVB) de chaque face selon la partie trouvée par le moteur de régions (auto, pièces ou graines).
    `palette` : couleurs choisies par partie (sinon couleurs par défaut). Résultat gardé pour l'aperçu puis l'export."""
    m = _region_model(path)
    r = _segment_cached(m, mode, parts, crease, list(seeds))
    full, n = r['full'], int(r['n'])
    cols = list(palette or [])[:n]
    cols += list(_REGION_COLORS[len(cols):max(n, 1)]) if len(cols) < n else []
    pal = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in cols[:max(n, 1)]], dtype=np.int32)
    return _Mesh(m['v'], m['f']), pal[full]


def api_split_color_3mf():
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path:
        return jsonify({"error": "Sélectionnez un fichier 3MF"}), 400
    regions = data.get('mode') == 'regions'                # découpe de la géométrie en parties (au lieu des couleurs peintes)
    ext = os.path.splitext(path)[1].lower()
    if ext != '.3mf' and not (regions and ext == '.stl'):
        return jsonify({"error": "Seuls les fichiers 3MF multicolores sont pris en charge"}), 400
    try:
        parts = int(min(max(float(data.get('parts') or 3), 2), MAX_PARTS))
        crease = data.get('crease') if data.get('crease') in _CREASE else 'medium'
        bed_w = float(data.get('bed_width') or 220)
        bed_d = float(data.get('bed_height') or 220)
        tol = min(max(float(data.get('tolerance') or 0), 0.0), 100.0)
        use_conn = data.get('connectors') not in (False, 0, '0', 'false')      # tenons de positionnement (actifs par défaut)
        csize = min(max(float(data.get('conn_size') or 0), 0.0), 30.0)
        clen = min(max(float(data.get('conn_length') or 0), 0.0), 30.0)
        mgap = min(max(float(data.get('merge_gap') if data.get('merge_gap') not in (None, '') else 5), 0.0), 500.0)
        cclear = min(max(float(data.get('conn_clearance') if data.get('conn_clearance') not in (None, '') else 0.2), 0.0), 1.0)
    except (TypeError, ValueError):
        return jsonify({"error": "Paramètres invalides"}), 400
    if bed_w < 20 or bed_d < 20:
        return jsonify({"error": "Dimensions de plateau invalides"}), 400
    if not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    if not _is_unc(path) and not os.path.exists(path):
        return jsonify({"error": "Fichier introuvable"}), 404
    try:
        if regions:
            tol = 0.0
            rmode, parts, crease, rseeds = _params(data)
            pal = []
            for p in data.get('palette') or []:
                hx = str(p.get('hex') if isinstance(p, dict) else p or '')
                if not _HEX.match(hx):
                    raise ValueError("Couleur de filament invalide")
                pal.append(hx.upper())
            mesh, face_rgb = _region_faces(path, rmode, parts, crease, rseeds, pal)
        else:
            mesh, face_rgb = _load_colored_mesh(path)
        pieces = split_mesh_by_color(mesh, face_rgb, tol)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Séparation couleur] lecture impossible : {e}")
        return jsonify({"error": f"Lecture du fichier impossible : {e}"}), 500
    default_rgb = None
    try:
        default_rgb = tuple(_thumb_base_rgb()) if _thumb_base_rgb else None
    except Exception:
        default_rgb = None
    total_faces = sum(p['count'] for p in pieces) or 1
    colors = [{"hex": _hex(p['rgb']), "faces": p['count'], "percent": round(100.0 * p['count'] / total_faces, 1),
               "default": (not regions) and default_rgb is not None and tuple(p['rgb']) == default_rgb} for p in pieces]
    if len(pieces) > MAX_COLORS:
        return jsonify({"error": f"Trop de couleurs distinctes ({len(pieces)}, maximum {MAX_COLORS}) : augmentez la tolérance de regroupement",
                        "colors": colors[:MAX_COLORS], "color_count": len(pieces)}), 400
    if data.get('dry_run'):
        pv = _preview_or_none(pieces) if pieces else None
        out = {"color_count": len(pieces), "colors": colors, "preview": pv}
        if pieces and pv is None:
            out["preview_error"] = "Aperçu indisponible pour ce fichier (voir les logs de Stellio)."
        return jsonify(out), 200
    if len(pieces) < 2:
        return jsonify({"error": ("Une seule région trouvée : augmentez le nombre de parties" if regions else "Une seule couleur détectée : rien à séparer"), "colors": colors, "color_count": len(pieces)}), 400

    base = _safe_name(path)
    plates, names = [], []
    try:
        spec = {'size': csize, 'length': clen, 'clearance': cclear} if use_conn else None
        per_color, repaired, fits, conn = _regions_pipeline(mesh, face_rgb, tol, spec, bed_w, bed_d, mgap, greedy=regions)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Séparation couleur] échec : {e}")
        return jsonify({"error": f"Échec de la préparation des pièces : {e}"}), 500
    for p in pieces:
        objs = per_color.get(p['label'])
        if not objs:
            continue
        plate = []
        for j, o in enumerate(objs, 1):
            label = f"{base} {_hex(p['rgb'])}" + (f" ({j})" if len(objs) > 1 else '')
            plate.append({'name': label, 'vertices': o['vertices'], 'faces': o['faces'], 'cx': o['cx'], 'cy': o['cy'], 'rgb': p['rgb']})
        plates.append(plate)
        names.append(_hex(p['rgb']))
    try:
        folder = _dest_dir([path], str(data.get('source_id') or '').strip() or None, data.get('target_subfolder'))
        out_path = _out_path(folder, data.get('filename') or f'{base}_couleurs', len(plates))
        _write_output(plates, bed_w, bed_d, out_path, names)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Séparation couleur] échec : {e}")
        return jsonify({"error": f"Échec de la création du fichier 3MF : {e}"}), 500
    try:
        invalidate_cache()
    except Exception:
        pass
    return jsonify({
        "output_path": out_path,
        "output_filename": os.path.basename(_unc(out_path)),
        "plate_count": len(plates),
        "repair": repaired,
        "connectors": conn,
        "mode": "regions" if regions else "colors",
        "colors": colors,
        "preview": _preview_or_none(pieces),
        "too_big": not fits,
    }), 200


def api_split_color_files():
    """Fichiers 3MF de la bibliothèque (cache de Stellio), filtrés par nom : sélecteur de la page du plugin."""
    if session.get('role') == 'viewer':
        return jsonify({"error": "Réservé au compte propriétaire"}), 403
    q = (request.args.get('q') or '').strip().lower()
    exts = ('.3mf', '.stl') if request.args.get('stl') else ('.3mf',)
    files = _library_files()
    out = []
    for f in files:
        p = str(f.get('path') or '')
        name = str(f.get('name') or os.path.basename(p))
        if p.lower().endswith(exts) and q in name.lower() and _is_path_within_sources(p, session['user_id']):
            out.append({"path": p, "name": name})
            if len(out) >= 60:
                break
    return jsonify({"files": out})


def _asyncable(fn):
    """Corps {"async": true} : le traitement part en tâche de fond (202 + job_id, suivi sur /api/jobs/<id>) si Stellio fournit le service."""
    def wrapper(*a, **k):
        d = request.get_json(silent=True) or {}
        if d.get('async') and run_view_async:
            return run_view_async(fn.__name__, fn)
        return fn(*a, **k)
    wrapper.__name__ = fn.__name__
    return wrapper


def _owner_post(fn):
    def wrapper(*a, **k):
        if session.get('role') == 'viewer':
            return jsonify({"error": "Réservé au compte propriétaire"}), 403
        return fn(*a, **k)
    wrapper.__name__ = fn.__name__
    return wrapper


def api_split_color_browse():
    """Ouvre l'explorateur de fichiers de Stellio (application de bureau) pour choisir le dossier d'enregistrement.
    Le dossier doit se trouver dans une source de la bibliothèque : on renvoie la source et le sous-dossier correspondants."""
    try:
        import webview
        dlg = _wv_dialog(webview, 'FOLDER') if _wv_dialog else webview.FOLDER_DIALOG
        result = webview.windows[0].create_file_dialog(dlg)
    except (ImportError, IndexError, AttributeError):
        return jsonify({"error": "L'explorateur n'est disponible que dans l'application de bureau", "code": "no_picker"}), 501
    except Exception as e:
        app_logger.warning(f"[Séparation couleur] explorateur : {e}")
        return jsonify({"error": "Impossible d'ouvrir l'explorateur"}), 500
    folder = (result[0] if result else None)
    if not folder:
        return jsonify({"error": "Annulé", "code": "cancelled"}), 400
    norm = str(folder).replace('\\', '/').rstrip('/')
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, path FROM sources WHERE user_id = ?", (session['user_id'],)).fetchall()
    finally:
        conn.close()
    best = None
    for r in rows:
        base = str(r['path'] or '').replace('\\', '/').rstrip('/')
        if base and (norm.lower() == base.lower() or norm.lower().startswith(base.lower() + '/')):
            if best is None or len(base) > len(best[1]):
                best = (r['id'], base)
    if best is None:
        return jsonify({"error": "Ce dossier n'est dans aucune de tes sources : ajoute-le d'abord comme source, ou choisis un dossier de la liste.", "code": "outside"}), 400
    return jsonify({"source_id": str(best[0]), "sub": norm[len(best[1]):].strip('/'), "path": norm})


# ── Régions : aperçu interactif et 3MF peint (ex-plugin « Split by region », fusionné ici) ──

def _write_bytes(path, data):
    if not _is_unc(path):
        with open(path, 'wb') as fh:
            fh.write(data)
        return
    kw = _smb_kwargs_for_path(session['user_id'], path)
    if kw is None:
        raise ValueError("Source réseau introuvable pour ce dossier")
    with smbclient.open_file(path, mode='wb', **kw) as fh:
        fh.write(data)


def _paint_code(state):
    """Valeur de l'attribut paint_color (Bambu / Orca) d'un triangle peint avec le filament n° `state` (≥ 2) : arbre à un nœud, nibbles écrits à l'envers."""
    if state < 3:
        return '%X' % (state << 2)
    return '%XC' % (state - 3)


def _painted_3mf(v, f, fs, palette, name, bed_w, bed_d):
    """3MF peint : un objet, attribut paint_color par triangle, filaments (couleurs et matières) dans les réglages du projet."""
    import json
    lo, hi = v.min(axis=0), v.max(axis=0)
    v = v - np.array([(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, lo[2]])
    verts = ''.join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in v)
    codes = {s: _paint_code(s) for s in range(2, len(palette) + 1)}
    tris = []
    for (a, b, c), s in zip(f.tolist(), fs.tolist()):
        tris.append(f'<triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{codes[s]}"/>' if s >= 2 else f'<triangle v1="{a}" v2="{b}" v3="{c}"/>')
    nm = quoteattr(name)
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
             'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" requiredextensions="">\n'
             '<metadata name="Application">Stellio</metadata>\n<metadata name="BambuStudio:3mfVersion">1</metadata>\n'
             f'<resources><object id="1" name={nm} type="model"><mesh><vertices>{verts}</vertices><triangles>{"".join(tris)}</triangles></mesh></object></resources>\n'
             f'<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 {bed_w / 2.0:.4f} {bed_d / 2.0:.4f} 0" printable="1"/></build>\n</model>')
    config = ('<?xml version="1.0" encoding="UTF-8"?>\n<config><object id="1"><metadata key="name" value=' + nm + '/><metadata key="extruder" value="1"/></object>'
              '<plate><metadata key="plater_id" value="1"/><metadata key="plater_name" value=""/><metadata key="locked" value="false"/>'
              '<model_instance><metadata key="object_id" value="1"/><metadata key="instance_id" value="0"/><metadata key="identify_id" value="1"/></model_instance></plate></config>')
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                     '<Default Extension="config" ContentType="text/xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    w, d = int(round(bed_w)), int(round(bed_d))
    project = json.dumps({'from': 'project', 'filament_colour': [p['hex'].upper() for p in palette],
                          'filament_type': [p.get('type') or 'PLA' for p in palette],
                          'printable_area': ['0x0', f'{w}x0', f'{w}x{d}', f'0x{d}']}, indent=2)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('3D/3dmodel.model', model)
        zf.writestr('Metadata/model_settings.config', config)
        zf.writestr('Metadata/project_settings.config', project)
    return buf.getvalue()


def api_split_color_region_model():
    """Maillage de travail (au plus MAX_WORK faces) envoyé tel quel à la page : les numéros de faces des graines et des parties restent valables."""
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path or not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    try:
        m = _region_model(path)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Régions 3D] lecture impossible : {e}")
        return jsonify({"error": f"Lecture du fichier impossible : {e}"}), 500
    wv, wf = m['wv'], m['wf']
    lo, hi = wv.min(axis=0), wv.max(axis=0)
    ctr = (lo + hi) / 2.0
    G = _graph_for(m, 'medium')
    return jsonify({"size": [float(x) for x in hi - lo], "faces": int(len(m['f'])), "work_faces": int(len(wf)), "shells": int(G['ncomp']),
                    "pos": _b64((wv - ctr).astype('<f4')), "idx": _b64(wf.astype('<u4')), "extent": [float(x) for x in hi - lo]})


def api_split_color_region_run():
    """Segmentation (aperçu : dry_run) ou création du 3MF peint multi-filament."""
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path:
        return jsonify({"error": "Sélectionnez un fichier 3MF ou STL"}), 400
    if not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    if not _is_unc(path) and not os.path.exists(path):
        return jsonify({"error": "Fichier introuvable"}), 404
    try:
        m = _region_model(path)
        mode, parts, crease, seeds = _params(data)
        r = _segment_cached(m, mode, parts, crease, seeds)
        out = {"labels": _b64(r['labels']), "parts": r['n'], "share": r['share'], "seeds": r['seeds'], "mode": mode}
        if data.get('dry_run'):
            return jsonify(out)
        palette = []
        for p in data.get('palette') or []:
            hx = str(p.get('hex') or '')
            if not _HEX.match(hx):
                raise ValueError("Couleur de filament invalide")
            palette.append({'hex': hx, 'type': re.sub(r'[^A-Za-z0-9+\- ]', '', str(p.get('type') or 'PLA'))[:16] or 'PLA', 'name': str(p.get('name') or '')[:60]})
        if len(palette) < r['n']:
            raise ValueError(f"Choisissez une couleur pour chacune des {r['n']} parties")
        palette = palette[:r['n']]
        bed_w, bed_d = _num(data, 'bed_width', 256, 20, 2000), _num(data, 'bed_depth', 256, 20, 2000)
        fs = (r['full'] + 1).astype(np.uint8)              # partie i = filament i + 1 (le filament 1 est la couleur de base)
        base = _safe_name(path)
        blob = _painted_3mf(m['v'], m['f'], fs, palette, base, bed_w, bed_d)
        folder = _dest_dir([path], str(data.get('source_id') or '').strip() or None, data.get('target_subfolder'))
        out_path = _out_path(folder, data.get('filename') or f'{base}_regions', 1)
        _write_bytes(out_path, blob)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except ImportError as e:
        return jsonify({"error": f"Module de calcul manquant ({e}) : scipy est livré avec Stellio"}), 500
    except Exception as e:
        app_logger.warning(f"[Régions 3D] échec : {e}")
        return jsonify({"error": f"Échec de la séparation : {e}"}), 500
    try:
        invalidate_cache()
    except Exception:
        pass
    out.update({"output_path": out_path, "output_filename": os.path.basename(_unc(out_path)), "faces": int(len(m['f']))})
    return jsonify(out)



_ROUTES = (
    ('/api/x/split-color/files', ['GET'], 'api_split_color_files', ('login_required', )),
    ('/api/x/split-color/folders', ['GET'], 'api_split_color_folders', ('login_required', )),
    ('/api/x/split-color/browse', ['POST'], 'api_split_color_browse', ('login_required', '_owner_post')),
    ('/api/x/split-color/mkdir', ['POST'], 'api_split_color_mkdir', ('login_required', '_owner_post')),
    ('/api/x/split-color/split', ['POST'], 'api_split_color_3mf', ('login_required', '_owner_post', '_asyncable')),
    ('/api/x/split-color/region-model', ['POST'], 'api_split_color_region_model', ('login_required', '_owner_post')),
    ('/api/x/split-color/region-run', ['POST'], 'api_split_color_region_run', ('login_required', '_owner_post', '_asyncable')),
)


def init(ns, routes=True):
    """Reçoit les services de main.py (dict des globals) et enregistre les routes Flask."""
    g = globals()
    g['_MAIN'] = ns
    missing = [n for n in _REQUIRED if n not in ns]
    if missing:
        raise RuntimeError(f"split_color.init : services manquants : {missing}")
    for n in _REQUIRED + _OPTIONAL + _OVERRIDABLE:
        if n in ns:
            g[n] = ns[n]
    if routes:
        for rule, methods, fname, decos in _ROUTES:
            view = g[fname]
            for d in reversed(decos):
                view = g[d](view)
            g['app'].add_url_rule(rule, endpoint='split_color_' + fname, view_func=view, methods=methods)
    return {}

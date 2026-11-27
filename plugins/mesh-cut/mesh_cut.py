"""Stellio — plugin signé « Découpe 3D » (catalogue stellio-plugins)

Découpe un modèle 3MF / STL en pièces qui tiennent sur le plateau : plans de coupe X / Y / Z (manuels ou automatiques), connecteurs d'emboîtement
(tenon rond, carré ou en croix, tige libre, logement d'aimant) avec jeu réglable, pièces posées à plat sur leur face de coupe, nouveau 3MF + guide d'assemblage PDF.
Le fichier d'origine n'est jamais modifié. Plugin à code hôte : installé signé par une clé de confiance (voir docs/plugins.md).
Routes : /api/x/mesh-cut/… ; page : cut.html.
"""
import base64
import io
import math
import os
import re
import zipfile
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
                app_logger.info(f"[Découpe 3D] pymeshfix indisponible : {e}")
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


def _solid(v, f):
    """Manifold (manifold3d, livré avec Stellio) d'un maillage fermé ; None s'il n'est pas utilisable."""
    from manifold3d import Manifold, Mesh
    m = Manifold(Mesh(vert_properties=np.ascontiguousarray(v, dtype=np.float32), tri_verts=np.ascontiguousarray(f, dtype=np.uint32)))
    return None if (m.is_empty() or not str(m.status()).endswith('NoError')) else m


def _unsolid(m):
    mesh = m.to_mesh()
    return np.array(mesh.vert_properties[:, :3], dtype=float), np.array(mesh.tri_verts, dtype=np.int64)


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


def api_mesh_cut_folders():
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
        app_logger.warning(f"[Découpe 3D] dossiers illisibles : {e}")
        return jsonify({"error": "Dossier illisible"}), 400


def api_mesh_cut_mkdir():
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
        app_logger.warning(f"[Découpe 3D] création de dossier impossible : {e}")
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


def api_mesh_cut_browse():
    """Ouvre l'explorateur de fichiers de Stellio (application de bureau) pour choisir le dossier d'enregistrement.
    Le dossier doit se trouver dans une source de la bibliothèque : on renvoie la source et le sous-dossier correspondants."""
    try:
        import webview
        dlg = _wv_dialog(webview, 'FOLDER') if _wv_dialog else webview.FOLDER_DIALOG
        result = webview.windows[0].create_file_dialog(dlg)
    except (ImportError, IndexError, AttributeError):
        return jsonify({"error": "L'explorateur n'est disponible que dans l'application de bureau", "code": "no_picker"}), 501
    except Exception as e:
        app_logger.warning(f"[Découpe 3D] explorateur : {e}")
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


# ── Découpe 3D : plans de coupe, connecteurs, pièces à plat, guide d'assemblage ──

AXES = {'x': 0, 'y': 1, 'z': 2}
MAX_CUTS = 12
MAX_PIECES = 80
_JOINTS = ('peg', 'dowel', 'magnet')       # tenon solidaire (mâle/femelle) · tige libre (femelle/femelle) · logement d'aimant
_SHAPES = ('round', 'square', 'cross')
_TXT = {
    'fr': {'guide': "Guide d'assemblage", 'pieces': 'pièces', 'cuts': 'Coupes', 'conns': 'Connecteurs', 'steps': "Ordre de montage", 'piece': 'Pièce',
           'dowel': 'Tige', 'join': 'Assembler la pièce {a} avec la pièce {b}', 'start': 'Départ : pièce {a}', 'size': 'Dimensions', 'with': 'Se joint à',
           'peg': 'tenon', 'hole': 'logement', 'magnet': 'aimant', 'dowels': 'tiges libres à imprimer : {n}', 'model': 'Modèle', 'view': 'Vue éclatée'},
    'en': {'guide': 'Assembly guide', 'pieces': 'pieces', 'cuts': 'Cuts', 'conns': 'Connectors', 'steps': 'Assembly order', 'piece': 'Piece',
           'dowel': 'Dowel', 'join': 'Join piece {a} to piece {b}', 'start': 'Start with piece {a}', 'size': 'Size', 'with': 'Joins',
           'peg': 'peg', 'hole': 'socket', 'magnet': 'magnet', 'dowels': 'loose dowels to print: {n}', 'model': 'Model', 'view': 'Exploded view'},
}


def _load_mesh(path):
    """Maillage (sommets, faces) d'un 3MF (tous les plateaux) ou d'un STL, de la bibliothèque. Lève ValueError si illisible."""
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
    return np.array(mesh.vertices, dtype=float), np.array(mesh.faces, dtype=np.int64)


def _bb(m):
    return np.asarray(m.bounding_box(), dtype=float)


def auto_cuts(size, bed):
    """Coupes régulières pour que chaque pièce tienne dans `bed` = (x, y, z) : un nombre minimal de plans par axe."""
    cuts = []
    for ax, name in enumerate('xyz'):
        lim = max(float(bed[ax]) - 2.0, 10.0)
        n = int(math.ceil(float(size[ax]) / lim - 1e-9)) - 1
        for i in range(1, n + 1):
            cuts.append((name, float(size[ax]) * i / (n + 1)))
    return cuts


def _parse_cuts(raw, size):
    cuts = []
    for c in raw or []:
        ax = str(c.get('axis', '')).lower()
        if ax not in AXES:
            raise ValueError("Axe de coupe invalide")
        pos = float(c.get('pos'))
        lim = float(size[AXES[ax]])
        if not (0.5 < pos < lim - 0.5):
            raise ValueError(f"Plan de coupe {ax.upper()} = {pos:g} mm hors du modèle (0 à {lim:.1f} mm)")
        cuts.append((ax, pos))
    return sorted(cuts, key=lambda c: (AXES[c[0]], c[1]))


def _cut_pieces(solid, cuts):
    """Tranche le solide par tous les plans ; une pièce coupée en îlots séparés donne autant de pièces."""
    _jc()
    pieces = [solid]
    for ax, pos in cuts:
        _jc()
        a = AXES[ax]
        nrm = [0.0, 0.0, 0.0]
        nrm[a] = 1.0
        nxt = []
        for p in pieces:
            _jc()
            bb = _bb(p)
            if bb[a] < pos - 1e-6 and bb[3 + a] > pos + 1e-6:
                up, low = p.split_by_plane(nrm, pos)
                for h in (low, up):
                    _jc()
                    if not h.is_empty():
                        nxt.extend(c for c in h.decompose() if c.volume() >= 0.5)
            else:
                nxt.append(p)
        pieces = nxt
        if len(pieces) > MAX_PIECES:
            raise ValueError(f"Trop de pièces (plus de {MAX_PIECES}) : réduisez le nombre de coupes")
    return pieces


def _to_z(m, ax):
    """Manifold tourné pour que l'axe `ax` devienne z (puis projection 2D) ; correspondance 2D→3D dans _from_2d."""
    if ax == 'x':
        return m.rotate([0, -90, 0])
    if ax == 'y':
        return m.rotate([90, 0, 0])
    return m


def _from_2d(ax, u, v, pos):
    return {'x': (pos, v, -u), 'y': (u, pos, -v), 'z': (u, v, pos)}[ax]


def _section(a, b, ax, pos, thick=0.3):
    """Section commune (2D) de deux pièces qui se touchent sur le plan `pos` de l'axe `ax`, ou None."""
    from manifold3d import Manifold
    k = AXES[ax]
    lo = np.minimum(_bb(a)[:3], _bb(b)[:3]) - 1.0
    hi = np.maximum(_bb(a)[3:], _bb(b)[3:]) + 1.0
    ext = hi - lo
    ea, eb = ext.copy(), ext.copy()
    ea[k] = thick
    eb[k] = thick
    oa, ob = lo.copy(), lo.copy()
    oa[k], ob[k] = pos - thick, pos
    sa = (a ^ Manifold.cube(ea.tolist()).translate(oa.tolist()))
    sb = (b ^ Manifold.cube(eb.tolist()).translate(ob.tolist()))
    if sa.is_empty() or sb.is_empty():
        return None
    cs = _to_z(sa, ax).project() ^ _to_z(sb, ax).project()
    return None if cs.area() < 4.0 else cs


def _inside(polys, pts):
    """Règle pair-impair : points intérieurs à un ensemble de contours (trous compris)."""
    pts = np.asarray(pts, dtype=float)
    inside = np.zeros(len(pts), dtype=bool)
    for poly in polys:
        p = np.asarray(poly, dtype=float)
        q = np.roll(p, -1, axis=0)
        for (x1, y1), (x2, y2) in zip(p, q):
            if y1 == y2:
                continue
            hit = ((pts[:, 1] > min(y1, y2)) & (pts[:, 1] <= max(y1, y2))
                   & (pts[:, 0] < (x2 - x1) * (pts[:, 1] - y1) / (y2 - y1) + x1))
            inside ^= hit
    return inside


def _pick_points(cs, side, clearance):
    """Positions (2D) des connecteurs dans la section `cs` : à l'intérieur d'une marge de sécurité ; un seul, deux si la section est longue."""
    from manifold3d import JoinType
    er = cs.offset(-(side / 2.0 + clearance + 1.2), JoinType.Miter)
    if er.is_empty() or er.area() < 0.5:
        return []
    polys = er.to_polygons()
    x0, y0, x1, y1 = er.bounds()
    gx, gy = np.meshgrid(np.linspace(x0, x1, 29), np.linspace(y0, y1, 29))
    g = np.column_stack([gx.ravel(), gy.ravel()])
    g = g[_inside(polys, g)]
    if len(g) == 0:
        c = np.array([(x0 + x1) / 2.0, (y0 + y1) / 2.0])
        return [c] if _inside(polys, [c])[0] else []
    ctr = g.mean(axis=0)
    first = g[np.argmin(np.linalg.norm(g - ctr, axis=1))]
    if len(g) < 6:
        return [first]
    _u, _s, vt = np.linalg.svd(g - ctr, full_matrices=False)
    t = (g - ctr) @ vt[0]
    span = float(t.max() - t.min())
    if span < 45.0 or span < 4 * side:
        return [first]
    pts = []
    for target in (t.min() + 0.22 * span, t.min() + 0.78 * span):
        pts.append(g[np.argmin(np.abs(t - target) + 3.0 * np.abs((g - ctr) @ vt[1]))])
    return pts


def _profile(shape, size, grow=0.0):
    from manifold3d import CrossSection
    s = size + 2.0 * grow
    if shape == 'round':
        return CrossSection.circle(s / 2.0, 32)
    if shape == 'square':
        return CrossSection.square([s, s], True)
    t = max(size / 3.0, 1.2) + 2.0 * grow                     # croix : deux barres
    bar = CrossSection.square([s, t], True)
    return bar + bar.rotate(90.0)


def _peg(shape, size, length, embed):
    """Tenon le long de +z : enfoncé de `embed` dans la pièce porteuse, dépasse de `length`, extrémité biseautée."""
    from manifold3d import Manifold
    bevel = min(0.6, size / 4.0)
    sc = max(size - 2 * bevel, 0.4) / size
    body = Manifold.extrude(_profile(shape, size), embed + length - bevel + 0.05).translate([0, 0, -embed])
    tip = Manifold.extrude(_profile(shape, size), bevel, 0, 0.0, (sc, sc)).translate([0, 0, length - bevel])
    return body + tip


def _hole(shape, size, depth, clearance):
    """Logement le long de +z depuis le plan de coupe (dépasse de 0,3 mm côté vide pour une coupe nette)."""
    from manifold3d import Manifold
    return Manifold.extrude(_profile(shape, size, clearance), depth + 0.3).translate([0, 0, -0.3])


def _dowel(shape, size, length, clearance):
    """Tige libre (le jeu est dans les logements) : chanfreinée aux deux bouts, couchée le long de x."""
    from manifold3d import Manifold
    total = 2.0 * length - 0.6
    bevel = min(0.6, size / 4.0)
    sc = max(size - 2 * bevel, 0.4) / size
    body = Manifold.extrude(_profile(shape, size), total - 2 * bevel + 0.1).translate([0, 0, bevel - 0.05])
    t1 = Manifold.extrude(_profile(shape, size), bevel, 0, 0.0, (sc, sc)).translate([0, 0, total - bevel])
    t0 = Manifold.extrude(_profile(shape, size), bevel, 0, 0.0, (sc, sc)).mirror([0, 0, 1]).translate([0, 0, bevel])
    return (body + t1 + t0).rotate([0, 90, 0])


def _orient_conn(m, ax, origin, sign=1):
    """Place un solide construit le long de +z : sa base à `origin`, tourné vers +axe (sign = 1) ou -axe (sign = -1)."""
    if sign < 0:
        m = m.rotate([180, 0, 0])
    if ax == 'x':
        m = m.rotate([0, 90, 0])
    elif ax == 'y':
        m = m.rotate([-90, 0, 0])
    return m.translate([float(origin[0]), float(origin[1]), float(origin[2])])


def _add_connectors(pieces, cuts, spec):
    """Connecteurs sur chaque interface. Renvoie (pièces modifiées, liste de jonctions, tiges libres, faces d'appui par pièce)."""
    _jc()
    from manifold3d import Manifold
    mode, shape = spec['mode'], spec['shape']
    size, length, clear = spec['size'], spec['length'], spec['clearance']
    embed = 1.5
    joints, dowels = [], []
    faces = {i: [] for i in range(len(pieces))}
    orig = list(pieces)                                      # sections et boîtes mesurées sur les pièces d'origine (les tenons agrandissent les boîtes)
    bbs = [_bb(p) for p in orig]
    for ax, pos in cuts:
        _jc()
        k = AXES[ax]
        for i in range(len(orig)):
            _jc()
            if abs(bbs[i][3 + k] - pos) > 1e-3:
                continue
            for j in range(len(orig)):
                _jc()
                if i == j or abs(bbs[j][k] - pos) > 1e-3:
                    continue
                if (np.minimum(bbs[i][3:], bbs[j][3:]) - np.maximum(bbs[i][:3], bbs[j][:3]))[[x for x in range(3) if x != k]].min() < 1.0:
                    continue
                try:
                    cs = _section(orig[i], orig[j], ax, pos)
                except Exception:
                    cs = None
                if cs is None:
                    continue
                a, b = pieces[i], pieces[j]
                area = float(cs.area())
                made = 0
                if mode != 'none':
                    for (u, v) in _pick_points(cs, size, clear):
                        _jc()
                        o = _from_2d(ax, float(u), float(v), pos)
                        try:
                            if mode == 'peg':
                                peg = _orient_conn(_peg(shape, size, length, embed), ax, o)
                                probe = _orient_conn(Manifold.extrude(_profile(shape, size * 0.9), embed).translate([0, 0, -embed]), ax, o)
                                out = _orient_conn(Manifold.extrude(_profile(shape, size * 0.9), length * 0.8), ax, o)
                                if (a ^ probe).volume() < 0.7 * probe.volume() or (b ^ out).volume() < 0.7 * out.volume():
                                    continue
                                pieces[i] = a + peg
                                pieces[j] = b - _orient_conn(_hole(shape, size, length + 0.5, clear), ax, o)
                            else:                                   # tige libre ou aimant : un logement dans chaque pièce
                                depth = length if mode == 'dowel' else spec['magnet_depth']
                                size_h = size
                                pa = _orient_conn(_hole(shape if mode == 'dowel' else 'round', size_h, depth, clear), ax, o, -1)
                                pb = _orient_conn(_hole(shape if mode == 'dowel' else 'round', size_h, depth, clear), ax, o, 1)
                                if (a ^ pa).volume() < 0.5 * pa.volume() or (b ^ pb).volume() < 0.5 * pb.volume():
                                    continue
                                pieces[i] = a - pa
                                pieces[j] = b - pb
                                if mode == 'dowel':
                                    dowels.append(_dowel(shape, size, length, clear))
                            a, b = pieces[i], pieces[j]
                            made += 1
                        except Exception as e:
                            app_logger.warning(f"[Découpe 3D] connecteur ignoré : {e}")
                joints.append({'ax': ax, 'pos': pos, 'lo': i, 'hi': j, 'area': area, 'n': made})
                nrm = np.zeros(3)
                nrm[k] = 1.0
                faces[i].append((nrm.copy(), area, made > 0 and mode == 'peg'))
                faces[j].append((-nrm, area, False))
    return pieces, joints, dowels, faces


def _flat_pieces(pieces, faces):
    """Chaque pièce posée sur sa plus grande face de coupe sans tenon (sinon sa meilleure face) : [(sommets, faces, rotation)]."""
    _jc()
    out = []
    for i, p in enumerate(pieces):
        _jc()
        v, f = _unsolid(p)
        cand = sorted(faces.get(i, []), key=lambda c: (c[2], -c[1]))      # sans tenon d'abord, puis la plus grande
        if cand:
            R = _rot_down(cand[0][0])
            w = v @ R.T
        else:
            w = _orient_for_print(v, f)
            R = None
        out.append((w, f, R))
    return out


def _plates(items, bed_w, bed_d):
    """Range les pièces sur des plateaux (autant que nécessaire). items = [(nom, sommets, faces)] → (plateaux, tient)."""
    _jc()
    prepared = []
    for name, v, f in items:
        _jc()
        lo, hi = v.min(axis=0), v.max(axis=0)
        prepared.append((name, v - np.array([(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, lo[2]]), f, float(hi[0] - lo[0]), float(hi[1] - lo[1])))
    prepared.sort(key=lambda it: -(it[3] * it[4]))
    groups, cur, fits = [], [], True
    for it in prepared:
        _jc()
        trial = cur + [it]
        _pos, tw, td = _pack([(x[3], x[4]) for x in trial], bed_w)
        if tw <= bed_w and td <= bed_d:
            cur = trial
        else:
            if cur:
                groups.append(cur)
            cur = [it]
            fits = fits and it[3] <= bed_w and it[4] <= bed_d
    if cur:
        groups.append(cur)
    plates = []
    for grp in groups:
        _jc()
        pos, tw, td = _pack([(x[3], x[4]) for x in grp], bed_w)
        plate = []
        for (name, v, f, w, d), (px, py) in zip(grp, pos):
            _jc()
            plate.append({'name': name, 'vertices': v, 'faces': f, 'cx': bed_w / 2.0 + px + w / 2.0 - tw / 2.0, 'cy': bed_d / 2.0 + py + d / 2.0 - td / 2.0})
        plates.append(plate)
    return plates, fits


def _hue(i, n):
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((i / max(n, 1)) % 1.0, 0.55, 0.92)
    return '#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))


def _decimate(v, f, cell, origin):
    """Réduction par regroupement de sommets sur une grille de côté `cell` : la surface reste continue (contrairement à un échantillon de triangles)."""
    key = np.floor((v - origin) / cell).astype(np.int64)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    sums = np.zeros((len(uniq), 3))
    np.add.at(sums, inv, v)
    nv = sums / np.bincount(inv)[:, None]
    nf = inv[f]
    nf = nf[(nf[:, 0] != nf[:, 1]) & (nf[:, 1] != nf[:, 2]) & (nf[:, 0] != nf[:, 2])]
    return nv, nf


def _reduce_sets(sets, max_tris):
    """Réduit tous les ensembles [(v, f, hex)] avec la même grille (les pièces voisines gardent des bords concordants)."""
    total = sum(len(s[1]) for s in sets)
    if total <= max_tris:
        return sets
    allv = np.vstack([s[0][np.unique(s[1])] for s in sets])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    n = 160.0
    best = sets
    for _ in range(8):
        cell = float(np.max(hi - lo)) / n
        red = [(*_decimate(sv, sf, cell, lo), hx) for sv, sf, hx in sets]
        count = sum(len(r[1]) for r in red)
        best = red
        if count <= max_tris:
            break
        n *= 0.8
    return best


def _preview_model(v, f, extra=None, max_tris=30000):
    """Aperçu léger (triangles recentrés, entiers 16 bits en base64) d'un ou plusieurs ensembles [(v, f, hex)]."""
    sets = _reduce_sets(extra or [(v, f, '#9aa7b8')], max_tris)
    allv = np.vstack([s[0][np.unique(s[1])] for s in sets])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    center = (lo + hi) / 2.0
    q = 12000.0 / max(float(np.max(hi - lo)) / 2.0, 1e-6)
    total = sum(len(s[1]) for s in sets) or 1
    out = []
    for sv, sf, hx in sets:
        budget = max(300, int(max_tris * 1.3 * len(sf) / total))
        if len(sf) > budget:
            sf = sf[np.linspace(0, len(sf) - 1, budget).astype(int)]
        tri = np.clip(np.round((sv[sf] - center) * q), -32000, 32000).astype('<i2')
        out.append({'hex': hx, 'tris': base64.b64encode(tri.tobytes()).decode('ascii')})
    return {'q': q, 'extent': [float(x) for x in (hi - lo)], 'center': [float(x) for x in center], 'pieces': out}


def _project(v, yaw, el):
    cy, sy, ce, se = math.cos(yaw), math.sin(yaw), math.cos(el), math.sin(el)
    x1 = v[:, 0] * cy - v[:, 1] * sy
    y1 = v[:, 0] * sy + v[:, 1] * cy
    return np.column_stack([x1, v[:, 2] * ce + y1 * se, y1 * ce - v[:, 2] * se])


def _draw_pieces(ax, geoms, labels, yaw=-0.6, el=0.62, max_tris=60000):
    """Dessine des pièces [(v, f, hex)] en perspective simple (tri en profondeur) ; labels = [(point 3D, texte)]."""
    _jc()
    from matplotlib.collections import PolyCollection
    from matplotlib.colors import to_rgb
    polys, cols, depth = [], [], []
    total = sum(len(g[1]) for g in geoms) or 1
    for v, f, hx in geoms:
        _jc()
        if len(f) > max_tris * len(f) / total:
            f = f[np.linspace(0, len(f) - 1, int(max_tris * len(f) / total)).astype(int)]
        P = _project(v, yaw, el)
        tri = P[f]
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        nrm /= (np.linalg.norm(nrm, axis=1)[:, None] + 1e-12)
        k = 0.38 + 0.62 * np.abs(-0.3 * nrm[:, 0] + 0.45 * nrm[:, 1] + 0.55 * nrm[:, 2])
        base = np.array(to_rgb(hx))
        polys.append(tri[:, :, :2])
        cols.append(np.clip(base[None, :] * k[:, None], 0, 1))
        depth.append(tri[:, :, 2].mean(axis=1))
    if not polys:
        return
    polys, cols, depth = np.concatenate(polys), np.concatenate(cols), np.concatenate(depth)
    order = np.argsort(-depth)
    ax.add_collection(PolyCollection(polys[order], facecolors=cols[order], edgecolors=cols[order], linewidths=0.3))
    allp = polys.reshape(-1, 2)
    pad = 0.05 * max(np.ptp(allp[:, 0]), np.ptp(allp[:, 1]), 1.0)
    ax.set_xlim(allp[:, 0].min() - pad, allp[:, 0].max() + pad)
    ax.set_ylim(allp[:, 1].min() - pad, allp[:, 1].max() + pad)
    ax.set_aspect('equal')
    ax.axis('off')
    for pt, txt in labels:
        _jc()
        q = _project(np.array([pt], dtype=float), yaw, el)[0]
        ax.text(q[0], q[1], txt, ha='center', va='center', fontsize=9, fontweight='bold', color='#111',
                bbox=dict(boxstyle='circle,pad=0.25', fc='white', ec='#333', lw=0.8))


def _guide_pdf(name, geoms, centers, sizes, joints, dowel_count, cuts, spec, lang):
    """Guide d'assemblage PDF : vue éclatée numérotée, une fiche par pièce (deux vues) et l'ordre de montage."""
    _jc()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    tx = _TXT.get(lang) or _TXT['fr']
    n = len(geoms)
    buf = io.BytesIO()
    allc = np.array(centers)
    mid = allc.mean(axis=0)
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(11.69, 8.27))
        fig.text(0.05, 0.94, f"{tx['guide']} — {name}", fontsize=18, fontweight='bold')
        fig.text(0.05, 0.905, f"{n} {tx['pieces']}" + (f" · {tx['dowels'].format(n=dowel_count)}" if dowel_count else ''), fontsize=11, color='#444')
        cut_txt = ' · '.join(f"{a.upper()} = {p:.1f} mm" for a, p in cuts) or '—'
        jn = sum(j['n'] for j in joints)
        fig.text(0.05, 0.875, f"{tx['cuts']} : {cut_txt}   |   {tx['conns']} : {jn} ({spec['mode']}, {spec['shape']}, {spec['size']:g} mm)", fontsize=9, color='#444')
        ax = fig.add_axes([0.05, 0.05, 0.62, 0.8])
        ex = 0.35
        egeo = []
        for i, (v, f, hx) in enumerate(geoms):
            _jc()
            d = (centers[i] - mid) * ex
            egeo.append((v + d, f, hx))
        _draw_pieces(ax, egeo, [(centers[i] + (centers[i] - mid) * ex, str(i + 1)) for i in range(n)])
        ax.set_title(tx['view'], fontsize=10)
        steps = _order_steps(n, joints, sizes)
        y = 0.82
        fig.text(0.70, y, tx['steps'], fontsize=12, fontweight='bold')
        for s in steps[:26]:
            _jc()
            y -= 0.028
            fig.text(0.70, y, (tx['start'].format(a=s[0] + 1) if s[1] is None else tx['join'].format(a=s[1] + 1, b=s[0] + 1)), fontsize=9)
        pdf.savefig(fig)
        plt.close(fig)
        for start in range(0, n, 4):
            _jc()
            fig = plt.figure(figsize=(11.69, 8.27))
            for slot, i in enumerate(range(start, min(start + 4, n))):
                _jc()
                col, row = slot % 2, slot // 2
                x0, y0 = 0.04 + col * 0.48, 0.52 - row * 0.48
                v, f, hx = geoms[i]
                for k, yaw in enumerate((-0.6, 2.5)):
                    _jc()
                    a = fig.add_axes([x0 + k * 0.2, y0 + 0.04, 0.2, 0.34])
                    _draw_pieces(a, [(v, f, hx)], [], yaw=yaw)
                near = sorted({(j['hi'] if j['lo'] == i else j['lo']) + 1 for j in joints if i in (j['lo'], j['hi'])})
                fig.text(x0 + 0.01, y0 + 0.40, f"{tx['piece']} {i + 1}", fontsize=14, fontweight='bold')
                fig.text(x0 + 0.01, y0 + 0.015, f"{tx['size']} : {sizes[i][0]:.1f} × {sizes[i][1]:.1f} × {sizes[i][2]:.1f} mm   {tx['with']} : {', '.join(map(str, near)) or '—'}", fontsize=8.5, color='#333')
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()


def _order_steps(n, joints, sizes):
    """Ordre de montage : on part de la plus grosse pièce, puis on ajoute les voisines. [(pièce, pièce de rattachement ou None)]."""
    start = int(np.argmax([s[0] * s[1] * s[2] for s in sizes])) if n else 0
    seen, steps, queue = {start}, [(start, None)], [start]
    while queue:
        cur = queue.pop(0)
        for j in joints:
            if cur not in (j['lo'], j['hi']):
                continue
            o = j['hi'] if j['lo'] == cur else j['lo']
            if o not in seen:
                seen.add(o)
                steps.append((o, cur))
                queue.append(o)
    for i in range(n):
        if i not in seen:
            steps.append((i, None))
    return steps


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


def _num(data, key, default, lo, hi):
    v = data.get(key)
    try:
        x = float(default if v in (None, '') else v)
    except (TypeError, ValueError):
        raise ValueError(f"Paramètre invalide : {key}")
    return min(max(x, lo), hi)


def _model_for(path):
    """(sommets recalés à l'origine, faces, dimensions, solide) du modèle. Réparation légère d'abord (soudure, trous) ; pymeshfix seulement si le volume reste inutilisable."""
    v, f = _load_mesh(path)
    v, f, _st = _repair_core(v, f)
    solid = _solid(v, f)
    if solid is None:
        v, f, _st = _repair_mesh(v, f)
        solid = _solid(v, f)
    lo = v[np.unique(f)].min(axis=0)
    v = v - lo
    if solid is not None:
        solid = solid.translate((-lo).tolist())
    return v, f, v[np.unique(f)].max(axis=0), solid


def api_mesh_cut_model():
    """Aperçu du modèle et ses dimensions (pour placer les plans de coupe)."""
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path or not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    try:
        v, f = _load_mesh(path)
        v, f, _st = _repair_core(v, f)            # mêmes dimensions que celles utilisées pour la coupe
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Découpe 3D] lecture impossible : {e}")
        return jsonify({"error": f"Lecture du fichier impossible : {e}"}), 500
    used = v[np.unique(f)]
    v = v - used.min(axis=0)
    return jsonify({"size": [float(x) for x in used.max(axis=0) - used.min(axis=0)], "faces": int(len(f)), "preview": _preview_model(v, f)})


def api_mesh_cut_run():
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path:
        return jsonify({"error": "Sélectionnez un fichier 3MF ou STL"}), 400
    if not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    if not _is_unc(path) and not os.path.exists(path):
        return jsonify({"error": "Fichier introuvable"}), 404
    try:
        bed = (_num(data, 'bed_width', 220, 20, 2000), _num(data, 'bed_depth', 220, 20, 2000), _num(data, 'bed_height', 250, 20, 2000))
        spec = {'mode': data.get('joint') if data.get('joint') in _JOINTS + ('none',) else 'peg',
                'shape': data.get('shape') if data.get('shape') in _SHAPES else 'round',
                'size': _num(data, 'conn_size', 8, 3, 40), 'length': _num(data, 'conn_length', 8, 2, 40),
                'clearance': _num(data, 'conn_clearance', 0.2, 0, 1.0), 'magnet_depth': _num(data, 'magnet_depth', 3, 1, 20)}
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    lang = str(data.get('lang') or 'fr')[:2]
    try:
        v, f, size, solid = _model_for(path)
        cuts = auto_cuts(size, bed) if data.get('auto') else _parse_cuts(data.get('cuts'), size)
        if len(cuts) > MAX_CUTS:
            return jsonify({"error": f"Trop de coupes (maximum {MAX_CUTS})"}), 400
        if not cuts:
            return jsonify({"error": "Ajoutez au moins un plan de coupe", "size": [float(x) for x in size]}), 400
        if solid is None:
            return jsonify({"error": "Le modèle n'est pas un volume fermé exploitable (même après réparation)"}), 400
        pieces = _cut_pieces(solid, cuts)
        if len(pieces) < 2:
            return jsonify({"error": "Les plans de coupe ne séparent rien"}), 400
        geo0 = [(_unsolid(p), _hue(i, len(pieces))) for i, p in enumerate(pieces)]
        pre = _preview_model(None, None, [(g[0][0], g[0][1], g[1]) for g in geo0])
        info = [{"n": i + 1, "size": [round(float(x), 1) for x in (_bb(p)[3:] - _bb(p)[:3])], "hex": geo0[i][1]} for i, p in enumerate(pieces)]
        if data.get('dry_run'):
            return jsonify({"pieces": info, "cuts": [{"axis": a, "pos": round(p, 2)} for a, p in cuts], "preview": pre})
        sizes = [tuple(_bb(p)[3:] - _bb(p)[:3]) for p in pieces]
        centers = [(_bb(p)[:3] + _bb(p)[3:]) / 2.0 for p in pieces]
        pieces, joints, dowels, faces = _add_connectors(pieces, cuts, spec)
        flat = _flat_pieces(pieces, faces)
        base = _safe_name(path)
        items = [(f"{base} {i + 1:02d}", w, fc) for i, (w, fc, _r) in enumerate(flat)]
        for k, d in enumerate(dowels, 1):
            dv, df = _unsolid(d)
            items.append((f"{base} tige {k}", dv, df))
        plates, fits = _plates(items, bed[0], bed[1])
        folder = _dest_dir([path], str(data.get('source_id') or '').strip() or None, data.get('target_subfolder'))
        out_path = _out_path(folder, data.get('filename') or f'{base}_decoupe', len(plates))
        _write_output(plates, bed[0], bed[1], out_path, [f"Plateau {i + 1}" for i in range(len(plates))])
        guide = None
        if data.get('guide', True):
            try:
                geoms = [(_unsolid(p)[0], _unsolid(p)[1], geo0[i][1]) for i, p in enumerate(pieces)]
                pdf = _guide_pdf(base, geoms, centers, sizes, joints, len(dowels), cuts, spec, lang)
                guide = out_path[:-4] + '_guide.pdf'
                _write_bytes(guide, pdf)
            except Exception as e:
                app_logger.warning(f"[Découpe 3D] guide PDF indisponible : {e}")
                guide = None
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except ImportError:
        return jsonify({"error": "manifold3d est requis pour découper (livré avec Stellio)"}), 500
    except Exception as e:
        app_logger.warning(f"[Découpe 3D] échec : {e}")
        return jsonify({"error": f"Échec de la découpe : {e}"}), 500
    try:
        invalidate_cache()
    except Exception:
        pass
    return jsonify({"output_path": out_path, "output_filename": os.path.basename(_unc(out_path)), "guide": os.path.basename(_unc(guide)) if guide else None,
                    "piece_count": len(pieces), "plate_count": len(plates), "connectors": sum(j['n'] for j in joints), "dowels": len(dowels),
                    "too_big": not fits, "pieces": info, "preview": pre})


def api_mesh_cut_files():
    """Fichiers 3MF / STL de la bibliothèque (cache de Stellio), filtrés par nom."""
    if session.get('role') == 'viewer':
        return jsonify({"error": "Réservé au compte propriétaire"}), 403
    q = (request.args.get('q') or '').strip().lower()
    files = _library_files()
    out = []
    for f in files:
        p = str(f.get('path') or '')
        name = str(f.get('name') or os.path.basename(p))
        if p.lower().endswith(('.3mf', '.stl')) and q in name.lower() and _is_path_within_sources(p, session['user_id']):
            out.append({"path": p, "name": name})
            if len(out) >= 60:
                break
    return jsonify({"files": out})


_ROUTES = (
    ('/api/x/mesh-cut/files', ['GET'], 'api_mesh_cut_files', ('login_required', )),
    ('/api/x/mesh-cut/folders', ['GET'], 'api_mesh_cut_folders', ('login_required', )),
    ('/api/x/mesh-cut/browse', ['POST'], 'api_mesh_cut_browse', ('login_required', '_owner_post')),
    ('/api/x/mesh-cut/mkdir', ['POST'], 'api_mesh_cut_mkdir', ('login_required', '_owner_post')),
    ('/api/x/mesh-cut/model', ['POST'], 'api_mesh_cut_model', ('login_required', '_owner_post')),
    ('/api/x/mesh-cut/cut', ['POST'], 'api_mesh_cut_run', ('login_required', '_owner_post', '_asyncable')),
)


def init(ns, routes=True):
    """Reçoit les services de main.py (dict des globals) et enregistre les routes Flask."""
    g = globals()
    g['_MAIN'] = ns
    missing = [n for n in _REQUIRED if n not in ns]
    if missing:
        raise RuntimeError(f"mesh_cut.init : services manquants : {missing}")
    for n in _REQUIRED + _OPTIONAL + _OVERRIDABLE:
        if n in ns:
            g[n] = ns[n]
    if routes:
        for rule, methods, fname, decos in _ROUTES:
            view = g[fname]
            for d in reversed(decos):
                view = g[d](view)
            g['app'].add_url_rule(rule, endpoint='mesh_cut_' + fname, view_func=view, methods=methods)
    return {}

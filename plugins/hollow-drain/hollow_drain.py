"""Stellio — plugin signé « Évidement et drainage » (catalogue stellio-plugins)

Creuse un modèle 3MF / STL (cavité interne à épaisseur de paroi constante) pour économiser la résine ou le filament, puis perce
automatiquement des trous de drainage (point bas de chaque poche) et d'évent (point haut) pour évacuer la résine ou la poudre ; bouchons optionnels.
Le fichier d'origine n'est jamais modifié. Calcul : voxels + distance euclidienne (scipy), surface par marching cubes (scikit-image),
booléens exacts avec manifold3d (livrés avec Stellio). Plugin à code hôte : installé signé par une clé de confiance (voir docs/plugins.md).
Routes : /api/x/hollow-drain/… ; page : hollow.html.
"""
import base64
import io
import math
import os
import re
import threading
import zipfile
from collections import OrderedDict

_REQUIRED = (
    'DATA_DIR',
    '_is_path_within_sources',
    '_smb_kwargs_for_path',
    '_resolve_3mf_plate_mesh',
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

MAX_PREVIEW_TRIS = 120000     # triangles envoyés à la page pour la vue en coupe
MAX_CAVITY_TRIS = 200000      # au-delà, la cavité est simplifiée avant le booléen (parois épaisses : sans risque)
BIAS = 0.25                   # marge (en voxels) : la paroi obtenue n'est jamais plus mince que demandée
_MAX_VOXELS = 45_000_000       # au-delà, le calcul est refusé (mémoire)
_QUALITY = {1: 3_000_000, 2: 10_000_000, 3: 24_000_000}   # nombre maximal de voxels (brouillon / normal / fin)



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
                app_logger.info(f"[Évidement 3D] pymeshfix indisponible : {e}")
            except Exception:
                pass
    return v, f, st


def _solid(v, f):
    """Manifold (manifold3d, livré avec Stellio) d'un maillage fermé ; None s'il n'est pas utilisable."""
    from manifold3d import Manifold, Mesh
    m = Manifold(Mesh(vert_properties=np.ascontiguousarray(v, dtype=np.float32), tri_verts=np.ascontiguousarray(f, dtype=np.uint32)))
    return None if (m.is_empty() or not str(m.status()).endswith('NoError')) else m


def _unsolid(m):
    mesh = m.to_mesh()
    return np.array(mesh.vert_properties[:, :3], dtype=float), np.array(mesh.tri_verts, dtype=np.int64)


def _is_unc(path):
    return path.startswith('//') or path.startswith('\\\\')


def _unc(path):
    return path.replace('\\', '/')


def _clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', (name or '').strip()).strip('. ')
    if name.lower().endswith(('.3mf', '.stl')):
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


def api_hollow_folders():
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
        app_logger.warning(f"[Évidement 3D] dossiers illisibles : {e}")
        return jsonify({"error": "Dossier illisible"}), 400


def api_hollow_mkdir():
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
        app_logger.warning(f"[Évidement 3D] création de dossier impossible : {e}")
        return jsonify({"error": "Création du dossier impossible"}), 400


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


def api_hollow_browse():
    """Ouvre l'explorateur de fichiers de Stellio (application de bureau) pour choisir le dossier d'enregistrement.
    Le dossier doit se trouver dans une source de la bibliothèque : on renvoie la source et le sous-dossier correspondants."""
    try:
        import webview
        dlg = _wv_dialog(webview, 'FOLDER') if _wv_dialog else webview.FOLDER_DIALOG
        result = webview.windows[0].create_file_dialog(dlg)
    except (ImportError, IndexError, AttributeError):
        return jsonify({"error": "L'explorateur n'est disponible que dans l'application de bureau", "code": "no_picker"}), 501
    except Exception as e:
        app_logger.warning(f"[Évidement 3D] explorateur : {e}")
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


def api_hollow_files():
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


# ── Évidement : cavité à paroi constante ──

def _tri_volume(v, f):
    tri = np.asarray(v, dtype=float)[np.asarray(f, dtype=np.int64)]
    return float(np.einsum('ij,ij->', tri[:, 0], np.cross(tri[:, 1], tri[:, 2])) / 6.0)


def _model_for(path):
    """(sommets, faces, dimensions) du modèle, réparé (soudure, trous, orientation). Lève ValueError si ce n'est pas un volume fermé."""
    v, f = _load_mesh(path)
    v, f, _st = _repair_core(v, f)
    if _solid(v, f) is None:
        v, f, _st = _repair_mesh(v, f)
        if _solid(v, f) is None:
            raise ValueError("Le modèle n'est pas un volume fermé exploitable (même après réparation)")
    used = v[np.unique(f)]
    return v, f, used.max(axis=0) - used.min(axis=0)


def _grid_pitch(size, wall, quality):
    """Pas de voxel : fixé par la qualité, mais jamais plus gros que paroi/1,8 (sinon la paroi serait imprécise). Pour un gros modèle à paroi fine,
    la grille grossit au lieu de refuser ; seule la mémoire (_check_memory) ou une limite absolue de voxels arrête le calcul."""
    budget = _QUALITY.get(int(quality), _QUALITY[2])
    vol = float(np.prod(np.maximum(size, 1.0)))
    pitch = max(wall / {1: 4.0, 2: 7.0, 3: 10.0}.get(int(quality), 7.0), (vol / budget) ** (1.0 / 3.0))   # petit modèle : grille fine → intérieur lisse
    cap = wall / 1.8
    if pitch > cap:
        pitch = cap
        if vol / pitch ** 3 > _MAX_VOXELS:
            raise ValueError("Modèle trop grand pour une paroi aussi fine : augmentez l'épaisseur de paroi")
    return pitch


def _voxel_surface(v, f, pitch, chunk=30000):
    """Voxels touchés par la surface (grille de pas `pitch`, origine = centre du voxel 0). Les triangles sont traités par morceaux et subdivisés à la taille d'un voxel :
    la mémoire reste bornée même avec un maillage organique très dense et un pas fin (la voxélisation de trimesh subdivise tout d'un coup et peut saturer la RAM)."""
    _jc()
    from trimesh import remesh
    v = np.asarray(v, dtype=float)
    f = np.asarray(f, dtype=np.int64)
    used = v[np.unique(f)]
    lo = used.min(axis=0)
    shape = np.ceil((used.max(axis=0) - lo) / pitch).astype(int) + 1
    surf = np.zeros(tuple(int(x) for x in shape), dtype=bool)
    for i in range(0, len(f), chunk):
        _jc()
        sub = f[i:i + chunk]
        u, inv = np.unique(sub, return_inverse=True)
        vv, ff = remesh.subdivide_to_size(v[u], np.asarray(inv).reshape(-1, 3), max_edge=0.75 * pitch)
        pts = vv[np.unique(ff)]
        idx = np.clip(np.rint((pts - lo) / pitch).astype(np.int64), 0, shape - 1)
        surf[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return surf, lo


def _check_memory(voxels):
    """Refuse proprement un calcul qui saturerait la RAM (le PC se figerait) : ~100 octets par voxel de la grille, plus une marge."""
    try:
        import psutil
        free = float(psutil.virtual_memory().available)
    except Exception:
        return
    if float(voxels) * 110.0 + 4e8 > free * 0.8:
        raise ValueError("Mémoire disponible insuffisante pour ce calcul : choisissez la qualité « brouillon », une paroi plus épaisse, ou fermez d'autres applications")


def _make_cavity(v, f, wall, quality):
    """Surface de la cavité : points intérieurs situés à plus de `wall` de la surface (voxels + distance euclidienne), extraits par marching cubes.
    Renvoie (sommets, faces, pas de voxel) ; faces orientées vers l'extérieur de la cavité (vers la matière)."""
    _jc()
    from scipy import ndimage
    from skimage import measure
    v = np.asarray(v, dtype=float)
    size = v[np.unique(f)].max(axis=0) - v[np.unique(f)].min(axis=0)
    pitch = _grid_pitch(size, wall, quality)
    _check_memory(float(np.prod(size / pitch + 8.0)))
    surf, origin = _voxel_surface(v, f, pitch)
    filled = ndimage.binary_fill_holes(surf)
    pad = 3
    surf = np.pad(surf, pad)
    filled = np.pad(filled, pad)
    dist = ndimage.distance_transform_edt(~surf) * pitch      # distance au voxel de surface le plus proche
    field = np.where(filled, dist, -dist).astype(np.float32)
    del dist, filled, surf
    smooth = field.size <= 70_000_000                           # lissage de l'intérieur (sinon les marches de la grille de voxels laissent des facettes)
    if smooth:
        _jc()
        field = ndimage.gaussian_filter(field, sigma=1.2, mode='nearest')
    level = float(wall) + (BIAS + (0.3 if smooth else 0.0)) * pitch     # marge supplémentaire : le lissage ne rapproche jamais la cavité de la surface
    if float(field.max()) <= level:
        raise ValueError("Aucune cavité possible : l'épaisseur de paroi demandée est trop grande pour ce modèle")
    org = np.asarray(origin, dtype=float) - pad * pitch
    vs, fs, _n, _val = measure.marching_cubes(field, level=level, spacing=(pitch, pitch, pitch))
    vs = vs + org
    fs = np.asarray(fs, dtype=np.int64)
    if _tri_volume(vs, fs) < 0:
        fs = fs[:, ::-1].copy()
    if smooth and len(fs) < 1500000:
        _jc()
        try:
            import trimesh
            tm = trimesh.Trimesh(vs, fs, process=False)
            trimesh.smoothing.filter_taubin(tm, lamb=0.5, nu=-0.53, iterations=15)     # lissage qui conserve le volume
            vs = np.asarray(tm.vertices, dtype=float)
        except Exception:
            pass
    return vs, fs, pitch


def _pockets(v, f, min_volume, limit=200):
    """Poches (composantes connexes) d'un maillage de cavité : [(sommets, faces, volume mm³)], les plus grosses d'abord ; les poches trop petites sont ignorées."""
    _jc()
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    n = len(v)
    a = np.concatenate([f[:, 0], f[:, 1], f[:, 2]])
    b = np.concatenate([f[:, 1], f[:, 2], f[:, 0]])
    _c, lab = connected_components(coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n, n)), directed=False)
    fl = lab[f[:, 0]]
    order = np.argsort(fl, kind='stable')
    fs_ = f[order]
    cuts = np.flatnonzero(np.diff(fl[order])) + 1
    out = []
    for sub in np.split(fs_, cuts):
        _jc()
        if len(sub) < 4:
            continue
        used, inv = np.unique(sub, return_inverse=True)
        sv, sf = v[used], np.asarray(inv).reshape(-1, 3)
        vol = _tri_volume(sv, sf)
        if vol >= max(min_volume, 1e-6):
            out.append((sv, sf, vol))
    out.sort(key=lambda p: -p[2])
    return out[:limit]


def _simplify(v, f, cap):
    """Réduit un maillage à ~cap triangles (fast-simplification, livré avec Stellio) ; sans lui, le maillage est gardé tel quel."""
    _jc()
    if len(f) <= cap:
        return v, f
    try:
        import fast_simplification
        v2, f2 = fast_simplification.simplify(np.asarray(v, dtype=np.float32), np.asarray(f, dtype=np.int32), target_reduction=min(0.95, 1.0 - cap / float(len(f))))
        return np.asarray(v2, dtype=float), np.asarray(f2, dtype=np.int64)
    except Exception:
        return v, f


class _Column:
    """Intersections d'une droite verticale (x, y) avec un maillage : hauteurs z triées (sans dépendance à rtree). Les triangles sont rangés dans une grille 2D :
    chaque appel n'examine que ceux de la case (modèles de plusieurs millions de triangles sans blocage)."""

    def __init__(self, v, f, cells=256):
        self.tri = np.asarray(v, dtype=float)[np.asarray(f, dtype=np.int64)]
        lo = self.tri[:, :, :2].min(axis=1)
        hi = self.tri[:, :, :2].max(axis=1)
        self.o = lo.min(axis=0)
        span = np.maximum(hi.max(axis=0) - self.o, 1e-9)
        self.n = int(cells)
        self.cs = span / self.n
        c0 = np.clip(((lo - self.o) / self.cs).astype(np.int64), 0, self.n - 1)
        c1 = np.clip(((hi - self.o) / self.cs).astype(np.int64), 0, self.n - 1)
        w, h = c1[:, 0] - c0[:, 0] + 1, c1[:, 1] - c0[:, 1] + 1
        cnt = w * h
        tid = np.repeat(np.arange(len(self.tri)), cnt)
        k = np.arange(len(tid)) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        cx = c0[tid, 0] + k % w[tid]
        cy = c0[tid, 1] + k // w[tid]
        key = cx * self.n + cy
        o = np.argsort(key, kind='stable')
        self.ids = tid[o]
        self.start = np.searchsorted(key[o], np.arange(self.n * self.n + 1))

    def hits(self, x, y):
        cx = int(np.clip((x - self.o[0]) / self.cs[0], 0, self.n - 1))
        cy = int(np.clip((y - self.o[1]) / self.cs[1], 0, self.n - 1))
        c = cx * self.n + cy
        t = self.tri[self.ids[self.start[c]:self.start[c + 1]]]
        if not len(t):
            return np.zeros(0)
        a, b, c3 = t[:, 0], t[:, 1], t[:, 2]
        d = (b[:, 1] - c3[:, 1]) * (a[:, 0] - c3[:, 0]) + (c3[:, 0] - b[:, 0]) * (a[:, 1] - c3[:, 1])
        ok = np.abs(d) > 1e-12
        d = np.where(ok, d, 1.0)
        l1 = ((b[:, 1] - c3[:, 1]) * (x - c3[:, 0]) + (c3[:, 0] - b[:, 0]) * (y - c3[:, 1])) / d
        l2 = ((c3[:, 1] - a[:, 1]) * (x - c3[:, 0]) + (a[:, 0] - c3[:, 0]) * (y - c3[:, 1])) / d
        l3 = 1.0 - l1 - l2
        ok &= (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        z = (l1 * a[:, 2] + l2 * b[:, 2] + l3 * c3[:, 2])[ok]
        return np.sort(z)


def _tunnel(col, x, y, z0, direction, r):
    """Depuis le point (x, y, z0) de la cavité, vers le bas (direction -1) ou le haut (+1) : cote z où le trou doit s'arrêter pour traverser la paroi
    sur toute sa largeur (centre + 6 points du pourtour), ou None si la verticale ne sort pas du modèle."""
    def first(px, py):
        h = col.hits(px, py)
        h = h[h < z0 - 1e-6] if direction < 0 else h[h > z0 + 1e-6]
        if not len(h):
            return None
        return float(h.max() if direction < 0 else h.min())
    centre = first(x, y)
    if centre is None:
        return None
    zs = [centre]
    for k in range(6):
        a = k * math.pi / 3.0
        z = first(x + 0.9 * r * math.cos(a), y + 0.9 * r * math.sin(a))
        if z is not None:
            zs.append(z)
    return min(zs) if direction < 0 else max(zs)


def _pick_hole(col, pv, direction, r, pitch):
    """Meilleur endroit pour un trou sur une poche : parmi les sommets les plus bas (direction -1) ou les plus hauts (+1), celui dont le tunnel est le plus court.
    Renvoie {x, y, z0, z1} ou None."""
    z = pv[:, 2]
    ext = float(z.min() if direction < 0 else z.max())
    tol = max(0.3, pitch)
    idx = np.where(z <= ext + tol)[0] if direction < 0 else np.where(z >= ext - tol)[0]
    c = pv[:, :2].mean(axis=0)                 # candidats les plus proches du centre de la poche d'abord : à tunnel égal, le trou est centré
    idx = idx[np.argsort(np.linalg.norm(pv[idx, :2] - c, axis=1))][:24]
    best = None
    for i in idx:
        x, y, z0 = (float(k) for k in pv[i])
        z1 = _tunnel(col, x, y, z0, direction, r)
        if z1 is None:
            continue
        length = abs(z1 - z0)
        if best is None or length < best[0] - 0.3:
            best = (length, {'x': x, 'y': y, 'z0': z0, 'z1': z1})
    return best[1] if best else None


def _cylinder(x, y, zlo, zhi, r, seg=32, r_top=None):
    from manifold3d import Manifold
    return Manifold.cylinder(float(zhi - zlo), float(r), float(r if r_top is None else r_top), seg).translate((float(x), float(y), float(zlo)))


def _plug(r, length, clearance):
    """Bouchon à imprimer : tige légèrement conique (jeu appliqué) + tête plate, couché sur le plateau (tête en bas)."""
    from manifold3d import Manifold
    rp = max(r - clearance, 0.6)
    head = Manifold.cylinder(1.2, r + 1.2, r + 1.2, 32)
    shaft = Manifold.cylinder(float(length), rp, rp * 0.9, 32).translate((0.0, 0.0, 1.2))
    return head + shaft


def hollow(v, f, P):
    """Évide le modèle (v, f) selon les paramètres P. Renvoie un dict : vertices, faces, holes, plugs, stats."""
    _jc()
    outer = _solid(v, f)
    if outer is None:
        raise ValueError("Le modèle n'est pas un volume fermé exploitable")
    cv, cf, pitch = _make_cavity(v, f, P['wall'], P['quality'])
    pockets = _pockets(cv, cf, P['min_pocket'])
    if not pockets:
        raise ValueError("Aucune cavité : paroi trop épaisse ou poches plus petites que le volume minimal")
    cav_v = np.vstack([p[0] for p in pockets])
    offs = np.cumsum([0] + [len(p[0]) for p in pockets[:-1]])
    cav_f = np.vstack([p[1] + o for p, o in zip(pockets, offs)])
    cav_v, cav_f = _simplify(cav_v, cav_f, MAX_CAVITY_TRIS)
    cavity = _solid(cav_v, cav_f)
    if cavity is None:                       # simplification refusée : cavité complète
        cav_v = np.vstack([p[0] for p in pockets])
        cav_f = np.vstack([p[1] + o for p, o in zip(pockets, offs)])
        cavity = _solid(cav_v, cav_f)
    if cavity is None:
        raise ValueError("Cavité inexploitable : essayez une autre épaisseur ou une autre qualité")
    body = outer - cavity
    holes, plugs, skipped, cutters = [], [], 0, []
    if P['holes']:
        col = _Column(v, f)
        r = P['diameter'] / 2.0
        down = P['drain_side'] != 'top'
        plan = [('drain', -1 if down else 1)] + ([('vent', 1 if down else -1)] if P['vent'] else [])
        for pv, _pf, _vol in pockets:
            _jc()
            for kind, d in plan:
                _jc()
                h = _pick_hole(col, pv, d, r, pitch)
                if h is None:
                    skipped += 1
                    continue
                margin = max(2.0 * r, 2.0)
                if d < 0:
                    zlo, zhi = h['z1'] - 0.6, h['z0'] + margin
                else:
                    zlo, zhi = h['z0'] - margin, h['z1'] + 0.6
                cutters.append(_cylinder(h['x'], h['y'], zlo, zhi, r))
                h.update({'kind': kind, 'dir': d, 'r': r, 'length': abs(h['z1'] - h['z0'])})
                holes.append(h)
        if cutters:
            from manifold3d import Manifold, OpType
            body = body - (Manifold.batch_boolean(cutters, OpType.Add) if len(cutters) > 1 else cutters[0])
        if P['plugs'] and holes:
            used = v[np.unique(f)]
            x = float(used[:, 0].max()) + 8.0 + r
            y = float(used[:, 1].min()) + r + 1.2
            z = float(used[:, 2].min())
            for h in holes:
                _jc()
                m = _plug(r, min(max(h['length'] + 1.0, 3.0), 10.0), P['clearance']).translate((x, y, z))
                plugs.append(_unsolid(m))
                x += 2 * r + 6.0
    rv, rf = _unsolid(body)
    before, after = abs(_tri_volume(v, f)), abs(_tri_volume(rv, rf))
    stats = {'volume_before': before, 'volume_after': after, 'saved': before - after, 'saved_pct': (100.0 * (before - after) / before) if before > 0 else 0.0,
             'pockets': len(pockets), 'holes': len(holes), 'skipped': skipped, 'pitch': pitch, 'faces': int(len(rf))}
    return {'vertices': rv, 'faces': rf, 'holes': holes, 'plugs': plugs, 'stats': stats}


# ── Sortie : 3MF / STL, aperçu en coupe, routes ──

_CACHE = OrderedDict()          # derniers résultats : « Créer » juste après « Aperçu » ne recalcule rien
_CACHE_LOCK = threading.Lock()


def _fmt(x):
    return ('%.5f' % x).rstrip('0').rstrip('.') or '0'


def _build_3mf(objects):
    """3MF minimal (millimètres) : un objet par entrée (nom, sommets, faces). Lisible par Bambu Studio, OrcaSlicer, PrusaSlicer, Cura."""
    _jc()
    from xml.sax.saxutils import quoteattr
    res, build = [], []
    for i, (name, v, f) in enumerate(objects, 1):
        _jc()
        vs = ''.join('<vertex x="%s" y="%s" z="%s"/>' % (_fmt(a), _fmt(b), _fmt(c)) for a, b, c in np.asarray(v, dtype=float).tolist())
        ts = ''.join('<triangle v1="%d" v2="%d" v3="%d"/>' % (a, b, c) for a, b, c in np.asarray(f, dtype=np.int64).tolist())
        res.append('<object id="%d" name=%s type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles></mesh></object>' % (i, quoteattr(name), vs, ts))
        build.append('<item objectid="%d"/>' % i)
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Application">Stellio</metadata><resources>%s</resources><build>%s</build></model>' % (''.join(res), ''.join(build)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr('3D/3dmodel.model', model)
    return buf.getvalue()


def _build_stl(v, f):
    """STL binaire."""
    tri = np.asarray(v, dtype=np.float32)[np.asarray(f, dtype=np.int64)]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(tri), dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    rec['n'], rec['v'] = n, tri
    return b'Stellio'.ljust(80, b' ') + np.uint32(len(tri)).tobytes() + rec.tobytes()


def _out_path(folder, name, ext):
    base = _clean_filename(name) or 'modele_creux'
    unc = _is_unc(folder)
    kw = (_smb_kwargs_for_path(session['user_id'], folder) or {}) if unc else {}
    join = (lambda n: _unc(folder).rstrip('/') + '/' + n) if unc else (lambda n: os.path.join(folder, n))
    exists = (lambda p: smbclient.path.exists(p, **kw)) if unc else os.path.exists
    candidate = join(base + ext)
    n = 2
    while exists(candidate):
        candidate = join(f'{base}_{n}{ext}')
        n += 1
    return candidate


def _pack(v, f, cap=MAX_PREVIEW_TRIS):
    """Maillage allégé pour la page : sommets float32 recentrés + indices uint32, en base64."""
    v = np.asarray(v, dtype=float)
    f = np.asarray(f, dtype=np.int64)
    v, f = _simplify(v, f, cap)
    used, inv = np.unique(f, return_inverse=True)
    v, f = v[used], np.asarray(inv).reshape(-1, 3)
    lo, hi = v.min(axis=0), v.max(axis=0)
    c = (lo + hi) / 2.0
    return {'extent': [float(x) for x in (hi - lo)], 'center': [float(x) for x in c], 'tris': int(len(f)),
            'pos': base64.b64encode(np.ascontiguousarray(v - c, dtype='<f4').tobytes()).decode('ascii'),
            'idx': base64.b64encode(np.ascontiguousarray(f, dtype='<u4').tobytes()).decode('ascii')}


def _model_id(path):
    try:
        st = os.stat(path) if not _is_unc(path) else None
        return (path, st.st_mtime_ns, st.st_size) if st else (path,)
    except OSError:
        return (path,)


def _params(data, size):
    wall = _num(data, 'wall', 2.0, 0.6, 20)
    if wall * 2.2 >= float(np.min(size)):
        raise ValueError("Épaisseur de paroi trop grande : la plus petite dimension du modèle est %.1f mm (il faut au moins %.1f mm)" % (float(np.min(size)), wall * 2.2))
    return {'wall': round(wall, 3), 'quality': int(_num(data, 'quality', 2, 1, 3)),
            'holes': bool(data.get('holes', True)), 'vent': bool(data.get('vent', True)),
            'drain_side': 'top' if data.get('drain_side') == 'top' else 'bottom',
            'diameter': round(_num(data, 'diameter', 3.5, 1.5, 15), 3), 'plugs': bool(data.get('plugs', False)),
            'clearance': round(_num(data, 'clearance', 0.2, 0, 1), 3), 'min_pocket': round(_num(data, 'min_pocket', 20, 0, 100000), 3)}


def _compute(path, data):
    _jc()
    v, f, size = _model_for(path)
    P = _params(data, size)
    key = (_model_id(path), tuple(sorted(P.items())))
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key], P, v, f
    res = hollow(v, f, P)
    res['preview'] = _pack(res['vertices'], res['faces'])
    with _CACHE_LOCK:
        _CACHE[key] = res
        while len(_CACHE) > 2:
            _jc()
            _CACHE.popitem(last=False)
    return res, P, v, f


def _public_stats(res):
    s = res['stats']
    return {'volume_before': round(s['volume_before'] / 1000.0, 2), 'volume_after': round(s['volume_after'] / 1000.0, 2), 'saved': round(s['saved'] / 1000.0, 2),
            'saved_pct': round(s['saved_pct'], 1), 'pockets': s['pockets'], 'holes': s['holes'], 'skipped': s['skipped'], 'pitch': round(s['pitch'], 3), 'faces': s['faces']}


def api_hollow_model():
    """Dimensions, volume et aperçu du modèle choisi."""
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path or not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    try:
        v, f, size = _model_for(path)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Évidement 3D] lecture impossible : {e}")
        return jsonify({"error": f"Lecture du fichier impossible : {e}"}), 500
    return jsonify({"size": [float(x) for x in size], "faces": int(len(f)), "volume": round(abs(_tri_volume(v, f)) / 1000.0, 2), "preview": _pack(v, f)})


def api_hollow_run():
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path:
        return jsonify({"error": "Sélectionnez un fichier 3MF ou STL"}), 400
    if not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    if not _is_unc(path) and not os.path.exists(path):
        return jsonify({"error": "Fichier introuvable"}), 404
    try:
        res, P, v, f = _compute(path, data)
        out = {"stats": _public_stats(res), "holes": [{"kind": h['kind'], "x": round(h['x'], 2), "y": round(h['y'], 2), "z": round(h['z0'], 2)} for h in res['holes']],
               "preview": res['preview'], "params": P}
        if P['holes'] and not res['holes']:
            out['warning'] = 'no_holes'
        if data.get('dry_run'):
            return jsonify(out)
        fmt = '.stl' if data.get('format') == 'stl' else '.3mf'
        base = re.sub(r'[\x00-\x1f<>]', '', os.path.splitext(os.path.basename(path))[0]).strip() or 'modele'
        folder = _dest_dir([path], str(data.get('source_id') or '').strip() or None, data.get('target_subfolder'))
        out_path = _out_path(folder, data.get('filename') or f'{base}_creux', fmt)
        extra = None
        if fmt == '.3mf':
            objs = [(base + ' (creux)', res['vertices'], res['faces'])] + [(f'{base} bouchon {i + 1}', pv, pf) for i, (pv, pf) in enumerate(res['plugs'])]
            _write_bytes(out_path, _build_3mf(objs))
        else:
            _write_bytes(out_path, _build_stl(res['vertices'], res['faces']))
            if res['plugs']:
                allv = np.vstack([p[0] for p in res['plugs']])
                offs = np.cumsum([0] + [len(p[0]) for p in res['plugs'][:-1]])
                allf = np.vstack([p[1] + o for p, o in zip(res['plugs'], offs)])
                extra = out_path[:-4] + '_bouchons.stl'
                _write_bytes(extra, _build_stl(allv, allf))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except ImportError as e:
        return jsonify({"error": f"Module de calcul manquant ({e}) : scipy, scikit-image et manifold3d sont livrés avec Stellio"}), 500
    except MemoryError:
        return jsonify({"error": "Mémoire insuffisante : choisissez la qualité « brouillon » ou une paroi plus épaisse"}), 500
    except Exception as e:
        app_logger.warning(f"[Évidement 3D] échec : {e}")
        return jsonify({"error": f"Échec de l'évidement : {e}"}), 500
    try:
        invalidate_cache()
    except Exception:
        pass
    out.update({"output_path": out_path, "output_filename": os.path.basename(_unc(out_path)), "plugs_file": os.path.basename(_unc(extra)) if extra else None,
                "plug_count": len(res['plugs'])})
    return jsonify(out)


_ROUTES = (
    ('/api/x/hollow-drain/files', ['GET'], 'api_hollow_files', ('login_required', )),
    ('/api/x/hollow-drain/folders', ['GET'], 'api_hollow_folders', ('login_required', )),
    ('/api/x/hollow-drain/browse', ['POST'], 'api_hollow_browse', ('login_required', '_owner_post')),
    ('/api/x/hollow-drain/mkdir', ['POST'], 'api_hollow_mkdir', ('login_required', '_owner_post')),
    ('/api/x/hollow-drain/model', ['POST'], 'api_hollow_model', ('login_required', '_owner_post')),
    ('/api/x/hollow-drain/run', ['POST'], 'api_hollow_run', ('login_required', '_owner_post', '_asyncable')),
)


def init(ns, routes=True):
    """Reçoit les services de main.py (dict des globals) et enregistre les routes Flask."""
    g = globals()
    g['_MAIN'] = ns
    missing = [n for n in _REQUIRED if n not in ns]
    if missing:
        raise RuntimeError(f"hollow_drain.init : services manquants : {missing}")
    for n in _REQUIRED + _OPTIONAL + _OVERRIDABLE:
        if n in ns:
            g[n] = ns[n]
    if routes:
        for rule, methods, fname, decos in _ROUTES:
            view = g[fname]
            for d in reversed(decos):
                view = g[d](view)
            g['app'].add_url_rule(rule, endpoint='hollow_drain_' + fname, view_func=view, methods=methods)
    return {}

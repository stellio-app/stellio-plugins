"""Stellio — plugin signé « Peinture filaments » (catalogue stellio-plugins)

Peint un modèle 3MF / STL (pinceau, pot de peinture, gomme) avec les couleurs des bobines de TON stock de filament, puis crée un 3MF peint
(attribut paint_color, lu par Bambu Studio / OrcaSlicer et par Stellio). Le fichier d'origine n'est jamais modifié.
Plugin à code hôte : installé signé par une clé de confiance (voir docs/plugins.md).
Routes : /api/x/paint-stock/… ; page : paint.html.
"""
import base64
import io
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

def _safe_name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r'[\x00-\x1f<>]', '', base).strip() or 'piece'


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


def api_paint_stock_folders():
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
        app_logger.warning(f"[Peinture filaments] dossiers illisibles : {e}")
        return jsonify({"error": "Dossier illisible"}), 400


def api_paint_stock_mkdir():
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
        app_logger.warning(f"[Peinture filaments] création de dossier impossible : {e}")
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


def api_paint_stock_browse():
    """Ouvre l'explorateur de fichiers de Stellio (application de bureau) pour choisir le dossier d'enregistrement.
    Le dossier doit se trouver dans une source de la bibliothèque : on renvoie la source et le sous-dossier correspondants."""
    try:
        import webview
        dlg = _wv_dialog(webview, 'FOLDER') if _wv_dialog else webview.FOLDER_DIALOG
        result = webview.windows[0].create_file_dialog(dlg)
    except (ImportError, IndexError, AttributeError):
        return jsonify({"error": "L'explorateur n'est disponible que dans l'application de bureau", "code": "no_picker"}), 501
    except Exception as e:
        app_logger.warning(f"[Peinture filaments] explorateur : {e}")
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


def api_paint_stock_files():
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


# ── Peinture : maillage de travail (soudé, au plus MAX_PROXY faces), états par sommet, export 3MF peint ──

MAX_PROXY = 150000      # au-delà, le modèle est réduit par regroupement de sommets pour l'édition ; l'export repasse sur le maillage complet
MAX_SLOTS = 16          # filaments numérotés (AMS 4 × 4)
EPS_DEGENERATE = 1e-12


def _prepare(path):
    """Maillage de travail : sommets soudés, faces dégénérées retirées, sommets inutilisés écartés. Renvoie (v, f)."""
    v, f = _load_mesh(path)
    uniq, inv = np.unique(np.round(v, 4), axis=0, return_inverse=True)
    f = np.asarray(inv).reshape(-1)[f]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    if len(f) == 0:
        raise ValueError("Maillage vide ou illisible")
    used, inv2 = np.unique(f, return_inverse=True)
    return uniq[used], np.asarray(inv2).reshape(-1, 3)


def _cluster(v, cell, origin):
    """Grappes de sommets sur une grille (mêmes grappes à l'aller et au retour : grille et origine sont renvoyées par /model)."""
    key = np.floor((v - np.asarray(origin, dtype=float)) / cell).astype(np.int64)
    _u, inv = np.unique(key, axis=0, return_inverse=True)
    return np.asarray(inv).reshape(-1)


def _proxy(v, f):
    """(sommets, faces, grille) du maillage d'édition. grille = None quand le maillage est utilisé tel quel."""
    if len(f) <= MAX_PROXY:
        return v, f, None
    lo, hi = v.min(axis=0), v.max(axis=0)
    n = 220.0
    for _ in range(10):
        cell = float(np.max(hi - lo)) / n
        inv = _cluster(v, cell, lo)
        k = int(inv.max()) + 1
        nf = inv[f]
        nf = nf[(nf[:, 0] != nf[:, 1]) & (nf[:, 1] != nf[:, 2]) & (nf[:, 0] != nf[:, 2])]
        if len(nf) <= MAX_PROXY:
            break
        n *= 0.85
    sums = np.zeros((k, 3))
    np.add.at(sums, inv, v)
    nv = sums / np.bincount(inv, minlength=k)[:, None]
    return nv, nf, {'cell': cell, 'origin': [float(x) for x in lo]}


def _refine(v, f, L, budget):
    """Subdivision conforme : coupe en deux au milieu toute arête plus longue que L (1→2, 1→3 ou 1→4 selon le nombre d'arêtes coupées, sans jonction en T).
    Déterministe : /model et /paint obtiennent exactement le même maillage. Renvoie (v, f) ou None si le budget de faces serait dépassé."""
    v = np.asarray(v, dtype=float).copy()
    f = np.asarray(f, dtype=np.int64).copy()
    for _ in range(14):
        nv = len(v)
        a = np.stack([f[:, 0], f[:, 1], f[:, 2]], axis=1)
        e = np.stack([a[:, [0, 1]], a[:, [1, 2]], a[:, [2, 0]]], axis=1)          # (n, 3, 2) : arêtes 0-1, 1-2, 2-0
        lo, hi = e.min(axis=2), e.max(axis=2)
        keys = lo * nv + hi
        length = np.linalg.norm(v[lo] - v[hi], axis=2)
        long_ = length > L
        if not long_.any():
            return v, f
        uk, first = np.unique(keys[long_], return_index=True)
        flat_lo, flat_hi = lo[long_][first], hi[long_][first]
        mids = (v[flat_lo] + v[flat_hi]) / 2.0
        pos = np.searchsorted(uk, keys)
        pos = np.minimum(pos, len(uk) - 1)
        hit = uk[pos] == keys
        M = np.where(hit, nv + pos, -1)                                             # sommet milieu de chaque arête (ou -1)
        ns = (M >= 0).sum(axis=1)
        add = int((ns == 1).sum() + 2 * (ns == 2).sum() + 3 * (ns == 3).sum())
        if len(f) + add > budget:
            return None
        v = np.vstack([v, mids])
        out = [f[ns == 0]]
        i3 = np.nonzero(ns == 3)[0]
        if len(i3):
            p, m = f[i3], M[i3]
            out += [np.stack([p[:, 0], m[:, 0], m[:, 2]], 1), np.stack([m[:, 0], p[:, 1], m[:, 1]], 1),
                    np.stack([m[:, 2], m[:, 1], p[:, 2]], 1), np.stack([m[:, 0], m[:, 1], m[:, 2]], 1)]
        i1 = np.nonzero(ns == 1)[0]
        if len(i1):
            k = np.argmax(M[i1] >= 0, axis=1)
            idx = (k[:, None] + np.arange(3)) % 3
            p, m = np.take_along_axis(f[i1], idx, 1), np.take_along_axis(M[i1], idx, 1)
            out += [np.stack([p[:, 0], m[:, 0], p[:, 2]], 1), np.stack([m[:, 0], p[:, 1], p[:, 2]], 1)]
        i2 = np.nonzero(ns == 2)[0]
        if len(i2):
            u = np.argmax(M[i2] < 0, axis=1)                                        # arête non coupée
            k = (u + 1) % 3
            idx = (k[:, None] + np.arange(3)) % 3
            p, m = np.take_along_axis(f[i2], idx, 1), np.take_along_axis(M[i2], idx, 1)
            out += [np.stack([m[:, 0], p[:, 1], m[:, 1]], 1), np.stack([p[:, 0], m[:, 0], m[:, 1]], 1), np.stack([p[:, 0], m[:, 1], p[:, 2]], 1)]
        f = np.vstack(out)
    return v, f


EDIT_BUDGET = 120000
MAX_REFINED = 600000      # faces max du maillage affiné au pinceau accepté à l'export


def _edit_mesh(v, f):
    """Maillage d'édition pour un modèle de taille raisonnable : subdivisé jusqu'à une arête max L (≥ 1 mm) pour que le pinceau puisse
    colorer une partie d'une grande face. Renvoie (v, f, L) ; L = None si le maillage est déjà assez fin ou trop dense."""
    diag = float(np.linalg.norm(v.max(axis=0) - v.min(axis=0))) or 1.0
    L = max(1.0, diag / 250.0)
    for _ in range(12):
        r = _refine(v, f, L, EDIT_BUDGET)
        if r is not None:
            return r[0], r[1], (L if len(r[1]) != len(f) else None)
        L *= 1.5
    return v, f, None


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode('ascii')


def api_paint_stock_model():
    """Maillage d'édition du modèle (sommets recentrés en Float32, faces en Uint32) et dimensions."""
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path or not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    if not _is_unc(path) and not os.path.exists(path):
        return jsonify({"error": "Fichier introuvable"}), 404
    try:
        v, f = _prepare(path)
        refine = None
        if len(f) <= MAX_PROXY:
            pv, pf, refine = _edit_mesh(v, f)
            grid = None
        else:
            pv, pf, grid = _proxy(v, f)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Peinture filaments] lecture impossible : {e}")
        return jsonify({"error": f"Lecture du fichier impossible : {e}"}), 500
    used = pv[np.unique(pf)]
    lo, hi = used.min(axis=0), used.max(axis=0)
    ctr = (lo + hi) / 2.0
    return jsonify({"size": [float(x) for x in hi - lo], "faces": int(len(f)), "proxy_faces": int(len(pf)), "grid": grid, "refine": refine, "center": [float(x) for x in ctr], "verts": int(len(pv)),
                    "pos": _b64((pv - ctr).astype('<f4')), "tris": _b64(pf.astype('<u4'))})


def _paint_code(state):
    """Valeur de l'attribut paint_color (Bambu / Orca) d'un triangle peint avec le filament n° `state` (≥ 2) : arbre à un nœud, nibbles écrits à l'envers."""
    if state < 3:
        return '%X' % (state << 2)
    return '%XC' % (state - 3)


def _face_states(vs, f):
    """État d'une face = état de la majorité de ses trois sommets (premier sommet si tous différents)."""
    a, b, c = vs[f[:, 0]], vs[f[:, 1]], vs[f[:, 2]]
    return np.where(b == c, b, a)


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


_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def api_paint_stock_paint():
    data = request.json or {}
    path = data.get('path')
    if not isinstance(path, str) or not path or not _is_path_within_sources(path, session['user_id']):
        return jsonify({"error": "Fichier hors des sources de la bibliothèque"}), 400
    if not _is_unc(path) and not os.path.exists(path):
        return jsonify({"error": "Fichier introuvable"}), 404
    try:
        bed_w, bed_d = _num(data, 'bed_width', 220, 20, 2000), _num(data, 'bed_depth', 220, 20, 2000)
        palette = []
        for p in data.get('palette') or []:
            hx = str(p.get('hex') or '')
            if not _HEX.match(hx):
                raise ValueError("Couleur de filament invalide")
            palette.append({'hex': hx, 'type': re.sub(r'[^A-Za-z0-9+\- ]', '', str(p.get('type') or 'PLA'))[:16] or 'PLA', 'name': str(p.get('name') or '')[:60]})
        if not palette:
            raise ValueError("Choisissez au moins une couleur")
        if len(palette) > MAX_SLOTS:
            raise ValueError(f"Trop de filaments (maximum {MAX_SLOTS})")
        raw = base64.b64decode(str(data.get('states') or ''), validate=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Paramètres invalides"}), 400
    try:
        v, f = _prepare(path)
        states = np.frombuffer(raw, dtype=np.uint8)
        grid, refine = data.get('grid'), data.get('refine')
        stale = jsonify({"error": "Le fichier a changé depuis l'ouverture : rouvrez-le"}), 409
        mesh = data.get('mesh')
        if mesh and not grid:                                     # maillage affiné au pinceau (contours lisses) : envoyé tel quel par la page
            ctr = np.asarray(mesh.get('center'), dtype=float).reshape(3)
            pv = np.frombuffer(base64.b64decode(str(mesh.get('pos') or ''), validate=True), dtype='<f4').astype(float).reshape(-1, 3) + ctr
            pf = np.frombuffer(base64.b64decode(str(mesh.get('tris') or ''), validate=True), dtype='<u4').astype(np.int64).reshape(-1, 3)
            if not len(pf) or len(pf) > MAX_REFINED or int(pf.max()) >= len(pv) or int(states.size) != len(pf):
                return stale
            lo, hi = v.min(axis=0), v.max(axis=0)
            if not np.all(pv.min(axis=0) >= lo - 1.0) or not np.all(pv.max(axis=0) <= hi + 1.0):
                return stale                                      # ne correspond plus au fichier
            v, f = pv, pf
            fs = np.where(states > len(palette), 0, states).astype(np.uint8)
        elif grid:                                                  # gros modèle : états par face du maillage allégé, reportés sur le modèle complet
            cell, origin = float(grid['cell']), grid['origin']
            inv = _cluster(v, cell, origin)
            cf = inv[f]
            keep = (cf[:, 0] != cf[:, 1]) & (cf[:, 1] != cf[:, 2]) & (cf[:, 0] != cf[:, 2])
            pf = cf[keep]
            if int(states.size) != len(pf):
                return stale
            states = np.where(states > len(palette), 0, states)
            cnt = np.zeros((int(inv.max()) + 1, len(palette) + 1), dtype=np.int32)
            for j in range(3):
                np.add.at(cnt, (pf[:, j], states), 1)
            vs = cnt.argmax(axis=1).astype(np.uint8)
            fs = _face_states(vs, cf)
        else:
            if refine:
                r = _refine(v, f, float(refine), EDIT_BUDGET)
                if r is None:
                    return stale
                v, f = r
            if int(states.size) != len(f):
                return stale
            fs = np.where(states > len(palette), 0, states).astype(np.uint8)
        fs = np.where(fs == 0, 1, fs)                         # non peint = filament 1 (couleur de base)
        tri = v[f]
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2.0
        total = float(area.sum()) or 1.0
        share = [round(100.0 * float(area[fs == i + 1].sum()) / total, 1) for i in range(len(palette))]
        base = _safe_name(path)
        blob = _painted_3mf(v, f, fs, palette, base, bed_w, bed_d)
        folder = _dest_dir([path], str(data.get('source_id') or '').strip() or None, data.get('target_subfolder'))
        out_path = _out_path(folder, data.get('filename') or f'{base}_peint', 1)
        _write_bytes(out_path, blob)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app_logger.warning(f"[Peinture filaments] échec : {e}")
        return jsonify({"error": f"Échec de la création du 3MF : {e}"}), 500
    try:
        invalidate_cache()
    except Exception:
        pass
    return jsonify({"output_path": out_path, "output_filename": os.path.basename(_unc(out_path)), "colors": len(palette), "share": share, "faces": int(len(f))})


_ROUTES = (
    ('/api/x/paint-stock/files', ['GET'], 'api_paint_stock_files', ('login_required', )),
    ('/api/x/paint-stock/folders', ['GET'], 'api_paint_stock_folders', ('login_required', )),
    ('/api/x/paint-stock/browse', ['POST'], 'api_paint_stock_browse', ('login_required', '_owner_post')),
    ('/api/x/paint-stock/mkdir', ['POST'], 'api_paint_stock_mkdir', ('login_required', '_owner_post')),
    ('/api/x/paint-stock/model', ['POST'], 'api_paint_stock_model', ('login_required', '_owner_post')),
    ('/api/x/paint-stock/paint', ['POST'], 'api_paint_stock_paint', ('login_required', '_owner_post', '_asyncable')),
)


def init(ns, routes=True):
    """Reçoit les services de main.py (dict des globals) et enregistre les routes Flask."""
    g = globals()
    g['_MAIN'] = ns
    missing = [n for n in _REQUIRED if n not in ns]
    if missing:
        raise RuntimeError(f"paint_stock.init : services manquants : {missing}")
    for n in _REQUIRED + _OPTIONAL + _OVERRIDABLE:
        if n in ns:
            g[n] = ns[n]
    if routes:
        for rule, methods, fname, decos in _ROUTES:
            view = g[fname]
            for d in reversed(decos):
                view = g[d](view)
            g['app'].add_url_rule(rule, endpoint='paint_stock_' + fname, view_func=view, methods=methods)
    return {}

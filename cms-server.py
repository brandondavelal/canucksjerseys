#!/usr/bin/env python3
"""Local CMS server for the Canucks Jerseys site.

Run it from the project folder:   python3 cms-server.py
then open                         http://localhost:8765/collection-admin.html

It serves the site and lets the admin page write straight into the project:
  - order.js                       the manual order of the listings
  - images.js                      which photos each listing has
  - images/listings/<id>/...       the photos themselves (resized to max 1800px JPEG)
Nothing is pushed anywhere: the changes are just files in the repo, ready to commit and push.
Listens on 127.0.0.1 only.
"""
import http.server, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT', sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8765))
LISTINGS = os.path.join(ROOT, 'images', 'listings')
MAX_UPLOAD = 60 * 1024 * 1024
ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,119}$')
HAS_SIPS = shutil.which('sips') is not None


def read_manifest():
    try:
        text = open(os.path.join(ROOT, 'images.js'), encoding='utf-8').read()
        return json.loads(text[text.index('{'):text.rindex('}') + 1])
    except Exception:
        return {}


def write_manifest(m):
    m = {k: v for k, v in sorted(m.items()) if v}
    body = ('/* photos for each listing, written by the local CMS (collection-admin.html). id -> list of image paths. */\n'
            'var GALLERY_IMAGES = ' + json.dumps(m, indent=2) + ';\n')
    with open(os.path.join(ROOT, 'images.js'), 'w', encoding='utf-8') as f:
        f.write(body)


def write_order(ids):
    body = ('/* manual order saved from collection-admin.html (ids from the sheet). Empty = sheet order. */\n'
            'var GALLERY_ORDER = ' + json.dumps(ids, indent=2) + ';\n')
    with open(os.path.join(ROOT, 'order.js'), 'w', encoding='utf-8') as f:
        f.write(body)


def listing_dir(lid):
    return os.path.join(LISTINGS, lid)


def own_path(lid, rel):
    """a manifest path is only trusted if it points inside this listing's own folder"""
    rel = str(rel)
    prefix = 'images/listings/' + lid + '/'
    if not rel.startswith(prefix) or '..' in rel or '\\' in rel:
        return None
    full = os.path.normpath(os.path.join(ROOT, rel))
    return full if full.startswith(listing_dir(lid) + os.sep) else None


def process_image(raw, name):
    """save an upload as a JPEG no bigger than 1800px on its longest side (sips ships with macOS)"""
    os.makedirs(os.path.join(ROOT, 'images', 'listings'), exist_ok=True)
    ext = os.path.splitext(name)[1].lower() or '.img'
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'in' + ext)
        open(src, 'wb').write(raw)
        out = os.path.join(td, 'out.jpg')
        if HAS_SIPS:
            r = subprocess.run(['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '80', '-Z', '1800', src, '--out', out],
                               capture_output=True, text=True)
            if r.returncode == 0 and os.path.exists(out):
                return open(out, 'rb').read(), '.jpg'
        if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg'):
            return raw, ext.replace('.jpeg', '.jpg')
    raise ValueError('unsupported image type')


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        if '/api/' in (args[0] if args else ''):
            sys.stderr.write('[cms] ' + fmt % args + '\n')

    # ---- helpers
    def send_json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def local_only(self):
        """API calls must come from this machine's own pages (blocks other websites from posting to localhost)"""
        host = (self.headers.get('Host') or '').split(':')[0]
        origin = self.headers.get('Origin')
        if host not in ('localhost', '127.0.0.1', '[::1]'):
            return False
        if origin and urllib.parse.urlparse(origin).hostname not in ('localhost', '127.0.0.1', '::1'):
            return False
        return self.headers.get('X-CMS') == '1'

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_UPLOAD:
            raise ValueError('too large')
        return self.rfile.read(n)

    # ---- routes
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/.git') or path.endswith('cms-server.py'):
            return self.send_error(404)
        if path == '/api/ping':
            if not self.local_only():
                return self.send_json({'ok': False}, 403)
            return self.send_json({'ok': True, 'resize': HAS_SIPS})
        if path == '/api/git':
            if not self.local_only():
                return self.send_json({'ok': False}, 403)
            try:
                out = subprocess.run(['git', 'status', '--porcelain', '--', 'order.js', 'images.js', 'images/listings'],
                                     cwd=ROOT, capture_output=True, text=True, timeout=10).stdout
                files = [l[3:] for l in out.splitlines() if l.strip()]
            except Exception:
                files = []
            return self.send_json({'ok': True, 'changed': files})
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not path.startswith('/api/') or not self.local_only():
            return self.send_json({'ok': False, 'error': 'forbidden'}, 403)
        try:
            if path == '/api/order':
                ids = json.loads(self.body() or b'{}').get('ids', [])
                if not isinstance(ids, list) or not all(isinstance(i, str) and ID_RE.match(i) for i in ids):
                    raise ValueError('bad ids')
                write_order(ids)
                return self.send_json({'ok': True, 'saved': len(ids)})
            m = re.match(r'^/api/images/([a-z0-9-]+)/(upload|set)$', path)
            if m and ID_RE.match(m.group(1)):
                lid, action = m.group(1), m.group(2)
                manifest = read_manifest()
                if action == 'upload':
                    raw = self.body()
                    name = urllib.parse.unquote(self.headers.get('X-Filename') or 'photo')
                    data, ext = process_image(raw, name)
                    os.makedirs(listing_dir(lid), exist_ok=True)
                    fname = '%d-%03d%s' % (int(time.time() * 1000), len(manifest.get(lid, [])) + 1, ext)
                    open(os.path.join(listing_dir(lid), fname), 'wb').write(data)
                    rel = 'images/listings/%s/%s' % (lid, fname)
                    manifest.setdefault(lid, []).append(rel)
                    write_manifest(manifest)
                    return self.send_json({'ok': True, 'path': rel, 'images': manifest[lid]})
                # set: new order / removals for this listing
                imgs = json.loads(self.body() or b'{}').get('images', [])
                keep = [p for p in imgs if own_path(lid, p) and os.path.exists(own_path(lid, p))]
                for old in manifest.get(lid, []):
                    if old not in keep and own_path(lid, old) and os.path.exists(own_path(lid, old)):
                        os.remove(own_path(lid, old))  # a photo taken off the listing is deleted from the repo folder
                if keep:
                    manifest[lid] = keep
                else:
                    manifest.pop(lid, None)
                    try:
                        os.rmdir(listing_dir(lid))
                    except OSError:
                        pass
                write_manifest(manifest)
                return self.send_json({'ok': True, 'images': keep})
            return self.send_json({'ok': False, 'error': 'not found'}, 404)
        except Exception as e:  # report, never crash the server
            return self.send_json({'ok': False, 'error': str(e)}, 400)


if __name__ == '__main__':
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print('Canucks Jerseys CMS  ->  http://localhost:%d/collection-admin.html' % PORT)
    print('site                 ->  http://localhost:%d/' % PORT)
    print('photo resizing: %s' % ('on (sips)' if HAS_SIPS else 'off (sips not found - photos saved as uploaded)'))
    print('Ctrl+C to stop.')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

"""Retired application endpoint and authenticated final snapshot export."""
import base64, datetime, hashlib, hmac, html, json, os, pathlib, shutil, sqlite3, tarfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

CONFIG = json.loads(base64.b64decode('eyJwcm9qZWN0X2lkIjogIm1lZHBhcmthbGxvLXBlcmZvcm1hbmNlLXJlcG9ydC1jbGVhbiIsICJsYWJlbCI6ICLsi6TsoIHtmozsnZgiLCAibmV3X3VybCI6ICJodHRwczovL21lZHByay1tZWRwYXJrLXBlcmZvcm1hbmNlLXJlcG9ydC5teWNhZmUyNC5haSIsICJ0b2tlbiI6ICJNVUl1MXo5cEI1VkxTcHVRaWdTTkVqZFRxdlpCeG1SVTNUVnFDTDMwdmZHcVlhTmoiLCAiZGF0YWJhc2VzIjogW10sICJmaWxlcyI6IFsib3ZlcnNlYXNfc25hcHNob3RfMjAyNl8xMS5qc29uIiwgInNhbGVzb3BzX3Jvb3RfbGl2ZV8yMDI2XzA4Lmpzb24iLCAibmFycmF0aXZlX3JvdW5kcy5qc29uIiwgInJlZ2lvbl9jb3JyZWN0aW9uXzIwMjYwOTA4X3YyLmF1ZGl0Lmpzb24iLCAibG9hZF8yMDI1X2FjdHVhbHNfMjAyNjA5MDkuYmVmb3JlLmpzb24iLCAiYXVndXN0X2RvbWVzdGljX2Nsb3NlXzIwMjYwOTA5LmF1ZGl0Lmpzb24iLCAib3ZlcnNlYXNfc25hcHNob3RfMjAyNl8wOC5qc29uIiwgIi5zZXNzaW9uX3NlY3JldCIsICJvdmVyc2Vhc19zbmFwc2hvdF8yMDI2XzA5Lmpzb24iLCAic2FsZXNvcHNfYWN0dWFsX3N5bmMuYXVkaXQuanNvbiIsICJyZWdpb25fY29ycmVjdGlvbl8yMDI2MDkwOF92Mi5iZWZvcmUuanNvbiIsICJyZWdpb25fY29ycmVjdGlvbl8yMDI2MDkwOF92NC5hdWRpdC5qc29uIiwgImF1Z3VzdF9vdmVyc2Vhc19wcm92aXNpb25hbF9jbG9zZV8yMDI2MDkwOC5iZWZvcmUuanNvbiIsICJwZXJmb3JtYW5jZV9kYXRhLmpzb24iLCAic2FsZXNvcHNfcm9vdF9saXZlXzIwMjZfMTEuanNvbiIsICJzYWxlc29wc19hY3R1YWxfc3luYy5iZWZvcmUuanNvbiIsICJuYXJyYXRpdmVfcHJvdmlzaW9uYWxfY2xvc2UuanNvbiIsICJvdmVyc2Vhc19zbmFwc2hvdF8yMDI2XzEwLmpzb24iLCAiZmxhc2hfYmFzZWxpbmUuanNvbiIsICJzYWxlc29wc19yb290X2xpdmVfMjAyNl8wOS5qc29uIiwgInJlZ2lvbl9jb3JyZWN0aW9uXzIwMjYwOTA4X3Y0Lndyb25nX3N0YXRlX2JlZm9yZV9yZXN0b3JlLmpzb24iLCAic2FsZXNvcHNfcm9vdF9saXZlXzIwMjZfMTAuanNvbiIsICJhdWd1c3RfZG9tZXN0aWNfY2xvc2VfMjAyNjA5MDkuYmVmb3JlLmpzb24iLCAibG9hZF8yMDI1X2FjdHVhbHNfMjAyNjA5MDkuYXVkaXQuanNvbiIsICJhdWd1c3Rfb3ZlcnNlYXNfcHJvdmlzaW9uYWxfY2xvc2VfMjAyNjA5MDguYXVkaXQuanNvbiJdLCAiZGlzcGxheSI6IGZhbHNlfQ=='))
LIVE = pathlib.Path('/app/user_data')
LOCK = threading.Lock()
STATE = {'retired': True, 'write_blocked': True, 'new_url': CONFIG['new_url'] if CONFIG else ''}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def export_snapshot():
    with LOCK:
        base = LIVE / '.medpark_cutover_20261014'
        marker, archive = base / 'manifest.json', base / 'final_snapshot.tar.gz'
        if marker.exists() and archive.exists():
            return json.loads(marker.read_text()), archive
        data = base / 'data'
        data.mkdir(parents=True, exist_ok=True)
        manifest = {'project_id': CONFIG['project_id'], 'new_url': CONFIG['new_url'], 'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'databases': [], 'file_hashes': {}}
        members = []
        for relative in CONFIG['databases']:
            source, target = LIVE / relative, data / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect('file:' + str(source) + '?mode=ro', uri=True) as current, sqlite3.connect(target) as copied:
                current.backup(copied)
                integrity = copied.execute('pragma integrity_check').fetchone()[0]
                foreign_keys = len(copied.execute('pragma foreign_key_check').fetchall())
                if integrity != 'ok' or foreign_keys:
                    raise RuntimeError('Final database integrity check failed')
                tables = [x[0] for x in copied.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
                counts = {t: copied.execute('select count(*) from "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}
                copied.execute('pragma wal_checkpoint(TRUNCATE)')
                copied.execute('pragma journal_mode=DELETE')
            copied.close()
            current.close()
            manifest['databases'].append({'relative_path': relative, 'integrity': integrity, 'foreign_key_errors': foreign_keys, 'table_counts': counts})
            members.append((target, relative))
        for relative in CONFIG['files']:
            source = LIVE / relative
            if not source.is_file():
                continue
            manifest['file_hashes'][relative] = digest(source)
            if source.suffix == '.json' or 'secret' in source.name.lower():
                target = data / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                members.append((target, relative))
        with tarfile.open(archive.with_suffix('.tmp'), 'w:gz') as tar:
            for path, relative in members:
                tar.add(path, arcname=relative, recursive=False)
        archive.with_suffix('.tmp').replace(archive)
        manifest['snapshot_sha256'] = digest(archive)
        manifest['snapshot_bytes'] = archive.stat().st_size
        marker.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        return manifest, archive


def notice_page():
    name, url = html.escape(CONFIG['label']), html.escape(CONFIG['new_url'], quote=True)
    return ('''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MedPark — 운영 주소 변경 안내</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#eff4f8;color:#182b3d;font:17px/1.7 system-ui,sans-serif}.card{width:min(680px,100%);padding:40px;background:white;border-radius:20px;box-shadow:0 14px 50px #1b38551a}.brand{font-weight:800;color:#08727b;letter-spacing:.09em}h1{font-size:28px;line-height:1.4;margin:18px 0}.alert{background:#fff4de;border-left:4px solid #d99015;padding:14px 18px;border-radius:5px}a.button{display:block;margin:28px 0 14px;padding:15px 20px;border-radius:10px;background:#08727b;color:white;text-align:center;font-weight:700;text-decoration:none}.url{overflow-wrap:anywhere;font-size:14px;color:#526979}.small{font-size:14px;color:#526979}</style><main class="card"><div class="brand">MEDPARK</div><h1>''' + name + '''<br>운영 주소가 변경되었습니다.</h1><div class="alert">이 주소에서는 데이터 입력·수정·저장이 중단되었습니다.</div><p>모든 업무는 아래 새 주소에서 진행해 주세요.<br>기존 계정으로 로그인하실 수 있습니다.</p><a class="button" href="''' + url + '''">새 프로그램으로 이동</a><div class="url">''' + url + '''</div><p class="small">즐겨찾기와 바탕화면 바로가기도 새 주소로 변경해 주세요.</p></main></html>''').encode()


def response(method, path, headers):
    route = urlsplit(path).path
    if route.startswith('/_cutover/'):
        if not hmac.compare_digest(str(headers.get('X-MedPark-Cutover', '')), CONFIG['token']):
            return 401, 'application/json', json.dumps({'error': 'Unauthorized'}).encode(), {}
        if method not in ('GET', 'HEAD'):
            return 405, 'application/json', b'{"error":"GET required"}', {}
        if route == '/_cutover/status':
            return 200, 'application/json', json.dumps(STATE).encode(), {}
        manifest, archive = export_snapshot()
        if route == '/_cutover/manifest':
            return 200, 'application/json', json.dumps(manifest, ensure_ascii=False).encode(), {}
        if route == '/_cutover/snapshot':
            return 200, 'application/gzip', archive, {'Content-Disposition': 'attachment; filename=final_snapshot.tar.gz'}
        return 404, 'application/json', b'{"error":"Not found"}', {}
    if CONFIG.get('display') and method in ('GET', 'HEAD') and any(route.startswith(p) for p in ('/play/', '/tv/', '/media/', '/builtin-films/')):
        return 302, 'text/plain', b'Playback moved', {'Location': CONFIG['new_url'].rstrip('/') + path}
    browser = 'text/html' in str(headers.get('Accept', '')) or (method in ('GET', 'HEAD') and not route.startswith('/api/'))
    if browser:
        return 200 if method in ('GET', 'HEAD') else 410, 'text/html; charset=utf-8', notice_page(), {}
    body = {'code': 'APPLICATION_MOVED', 'error': '운영 주소가 변경되어 이 주소의 입력·수정·저장이 중단되었습니다. 새 주소를 이용해 주세요.', 'new_url': CONFIG['new_url'], 'write_blocked': True}
    return 410, 'application/json; charset=utf-8', json.dumps(body, ensure_ascii=False).encode(), {}


class Handler(BaseHTTPRequestHandler):
    def handle_request(self):
        try:
            status, content_type, body, extra = response(self.command, self.path, self.headers)
            length = body.stat().st_size if isinstance(body, pathlib.Path) else len(body)
            self.send_response(status)
            for key, value in {'Content-Type': content_type, 'Content-Length': str(length), 'Cache-Control': 'no-store, max-age=0', 'X-MedPark-Retired': '1', **extra}.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != 'HEAD':
                if isinstance(body, pathlib.Path):
                    with body.open('rb') as f: shutil.copyfileobj(f, self.wfile)
                else: self.wfile.write(body)
        except Exception:
            self.send_error(500, 'Final snapshot export failed')
    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = handle_request


def app(environ, start_response):
    headers = {k[5:].replace('_', '-'): v for k, v in environ.items() if k.startswith('HTTP_')}
    # Case-insensitive header access is needed by the shared response function.
    from email.message import Message
    message = Message()
    for k, v in headers.items(): message[k] = v
    status, content_type, body, extra = response(environ['REQUEST_METHOD'], environ.get('PATH_INFO', '/') + ('?' + environ['QUERY_STRING'] if environ.get('QUERY_STRING') else ''), message)
    length = body.stat().st_size if isinstance(body, pathlib.Path) else len(body)
    from http.client import responses
    start_response(str(status) + ' ' + responses[status], list({'Content-Type': content_type, 'Content-Length': str(length), 'Cache-Control': 'no-store, max-age=0', 'X-MedPark-Retired': '1', **extra}.items()))
    if environ['REQUEST_METHOD'] == 'HEAD': return [b'']
    if isinstance(body, pathlib.Path):
        def chunks():
            with body.open('rb') as f:
                for b in iter(lambda: f.read(1048576), b''): yield b
        return chunks()
    return [body]


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8000'))), Handler).serve_forever()

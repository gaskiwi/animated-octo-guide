#!/usr/bin/env python3
"""Claude Code HTTP proxy — runs as pacers4ever on host, called by container.

v2: ThreadingHTTPServer + semaphore so multiple Claude Code runs execute in
parallel (required for dynamic workflows' subagent fan-out). Concurrency is
capped via CC_MAX_CONCURRENT (default 4) to protect the mini PC.
"""
import json, logging, os, subprocess, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('cc_proxy')

PORT       = 18790
CLAUDE_BIN = str(Path.home() / 'cc_claude_code')
CC_RUNS    = str(Path.home() / 'cc_runs')
MAX_CONCURRENT = int(os.environ.get('CC_MAX_CONCURRENT', '4'))
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
Path(CC_RUNS).mkdir(parents=True, exist_ok=True)

# CLI login can expire; fall back to API-key auth by loading ANTHROPIC_API_KEY
# from the agent-node .env (no python-dotenv needed on the host).
def _load_env_key(name):
    if os.environ.get(name):
        return
    env_file = Path(__file__).parent / '.env'
    try:
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(name):
                _, _, val = line.partition('=')
                os.environ[name] = val.strip().strip('"\'')
                log.info('%s loaded from .env', name)
                return
    except OSError:
        pass

_load_env_key('ANTHROPIC_API_KEY')

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): log.info(fmt, *args)

    def do_GET(self):
        if self.path == '/health':
            self._json(200, {'status': 'ok', 'binary': CLAUDE_BIN, 'exists': os.path.isfile(CLAUDE_BIN)})
        else:
            self._json(404, {'error': 'not found'})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        except Exception as e:
            return self._json(400, {'error': str(e)})

        prompt  = body.get('prompt', '')
        system  = body.get('system', '')
        workdir = body.get('workdir') or tempfile.mkdtemp(prefix='cc_', dir=CC_RUNS)
        timeout = int(body.get('timeout', 600))

        try:
            Path(workdir).mkdir(parents=True, exist_ok=True)
            if system:
                (Path(workdir) / 'CLAUDE.md').write_text(system, encoding='utf-8')
        except Exception as e:
            return self._json(500, {'error': f'workdir not usable on host: {workdir}: {e}'})

        log.info('Running CC: workdir=%s prompt_len=%d', workdir, len(prompt))
        env = os.environ.copy()
        env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'

        try:
            with _slots:
                r = subprocess.run(
                    [CLAUDE_BIN, '--dangerously-skip-permissions', '--print', prompt],
                    cwd=workdir, env=env, capture_output=True, text=True,
                    timeout=timeout, stdin=subprocess.DEVNULL,
                )
            output = r.stdout.strip()
            if r.returncode != 0 and not output:
                return self._json(500, {'error': f'CC exited {r.returncode}: {r.stderr[:300]}'})
            files = [str(p.relative_to(workdir)) for p in Path(workdir).rglob('*')
                     if p.is_file() and p.name != 'CLAUDE.md']
            log.info('Done: %d chars, %d files', len(output), len(files))
            self._json(200, {'output': output, 'workdir': workdir, 'files': files})
        except subprocess.TimeoutExpired:
            self._json(500, {'error': f'Timeout after {timeout}s'})
        except Exception as e:
            self._json(500, {'error': str(e)})

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    log.info('Claude Code proxy on http://127.0.0.1:%d (max %d concurrent)', PORT, MAX_CONCURRENT)
    log.info('Binary: %s (exists=%s)', CLAUDE_BIN, os.path.isfile(CLAUDE_BIN))
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()

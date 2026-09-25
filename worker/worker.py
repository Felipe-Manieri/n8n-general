"""
General Worker (PC Windows) — contrato único de execução.

Rotas
  GET  /health          sem autenticação, só diz que o processo está vivo
  POST /task            contrato novo (task_id, status, result_pt, evidence)
  GET  /task/<task_id>  consulta o estado de uma tarefa
  POST /                rota legada {command} -> {ok, stdout, stderr} (mantida por compatibilidade;
                        NÃO traz status/evidence, então o n8n a trata como resultado desconhecido)

Autenticação: header X-AGENT-TOKEN. O token NUNCA fica no código: vem da variável de
ambiente WORKER_TOKEN ou do arquivo worker_token.txt ao lado deste script.

Contrato de resposta de POST /task
  {
    "task_id": "...",
    "status": "completed" | "running" | "failed",     (waiting_input é usado por agentes de RPA/Central)
    "result_pt": "texto curto em português",
    "evidence": {
      "verified": true|false,      # true só quando checagens independentes confirmaram o efeito
      "checks": [ {"type": "file_exists", "path": "...", "ok": true, ...} ],
      "exit_code": 0, "stdout_tail": "...", "stderr_tail": "..."
    },
    "error_code": "...",           # só em falha
    "started_at": "...", "finished_at": "..."
  }

Ações de POST /task
  ping                                    -> completed (evidence.verified=false: só prova que o processo responde)
  create_file  {path, content}            -> grava o arquivo (somente dentro do perfil do usuário) e verifica lendo de volta
  powershell   {command, verify?: [...]}  -> executa; se `verify` for enviado, o efeito é checado de forma independente
Checagens de `verify`: file_exists, dir_exists, path_absent, file_contains{text}, file_sha256{sha256}
"""
import hashlib
import hmac
import json
import os
import pathlib
import subprocess
import threading
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request

VERSION = "2.0-contrato"
BASE = pathlib.Path(__file__).resolve().parent
TASK_DIR = BASE / "tasks"
TASK_DIR.mkdir(exist_ok=True)
LOG_FILE = BASE / "worker.log"
USER_ROOT = pathlib.Path(os.environ.get("USERPROFILE", str(pathlib.Path.home()))).resolve()
MAX_TIMEOUT_S = 600
DEFAULT_WAIT_S = 25


def _load_token():
    tok = os.environ.get("WORKER_TOKEN", "").strip()
    if not tok:
        f = BASE / "worker_token.txt"
        if f.exists():
            tok = f.read_text(encoding="utf-8").strip()
    if not tok:
        raise SystemExit("Defina WORKER_TOKEN ou crie worker_token.txt ao lado do worker.py")
    return tok


TOKEN = _load_token()
app = Flask(__name__)
_lock = threading.Lock()
_tasks = {}  # task_id -> dict


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg):
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{now()} {msg}\n")
    except OSError:
        pass


def authorized():
    got = request.headers.get("X-AGENT-TOKEN", "")
    return hmac.compare_digest(got.encode("utf-8"), TOKEN.encode("utf-8"))


def _persist(t):
    try:
        (TASK_DIR / f"{t['task_id']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log(f"persist_error {t.get('task_id')}: {e}")


def _safe_id(task_id):
    tid = str(task_id or "").strip()
    if not tid or len(tid) > 80 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in tid):
        return None
    return tid


def _load_existing(tid):
    with _lock:
        if tid in _tasks:
            return _tasks[tid]
    f = TASK_DIR / f"{tid}.json"
    if f.exists():
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if t.get("status") == "running":  # processo reiniciou no meio da execução
            t.update(status="failed", error_code="WORKER_RESTARTED", finished_at=now(),
                     result_pt="O Worker reiniciou durante a execução; o resultado é desconhecido.")
            _persist(t)
        with _lock:
            _tasks[tid] = t
        return t
    return None


# ---------------------------------------------------------------- verificação independente
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_check(chk):
    typ = chk.get("type")
    path = chk.get("path", "")
    out = {"type": typ, "path": path, "ok": False}
    try:
        if typ == "file_exists":
            p = pathlib.Path(path)
            out["ok"] = p.is_file()
            if out["ok"]:
                out["size"] = p.stat().st_size
                out["sha256"] = _sha256(p)
        elif typ == "dir_exists":
            out["ok"] = pathlib.Path(path).is_dir()
        elif typ == "path_absent":
            out["ok"] = not pathlib.Path(path).exists()
        elif typ == "file_contains":
            p = pathlib.Path(path)
            out["ok"] = p.is_file() and str(chk.get("text", "")) in p.read_text(encoding="utf-8", errors="replace")
        elif typ == "file_sha256":
            p = pathlib.Path(path)
            out["ok"] = p.is_file() and _sha256(p).lower() == str(chk.get("sha256", "")).lower()
        else:
            out["error"] = "tipo de checagem desconhecido"
    except OSError as e:
        out["error"] = str(e)
    return out


def _finish(t, status, result_pt, evidence=None, error_code=None):
    t.update(status=status, result_pt=result_pt, finished_at=now())
    if evidence is not None:
        t["evidence"] = evidence
    if error_code:
        t["error_code"] = error_code
    _persist(t)
    log(f"task {t['task_id']} -> {status} {error_code or ''}")


# ---------------------------------------------------------------- ações
def act_ping(t, body):
    _finish(t, "completed", "Worker respondeu ao ping.",
            {"verified": False, "checks": [], "note": "ping prova apenas que o processo está vivo"})


def act_create_file(t, body):
    raw = body.get("path", "")
    content = str(body.get("content", ""))
    try:
        p = pathlib.Path(raw).expanduser().resolve()
    except (OSError, ValueError):
        return _finish(t, "failed", "Caminho inválido.", error_code="BAD_PATH")
    if USER_ROOT not in p.parents and p != USER_ROOT:
        return _finish(t, "failed", f"create_file só escreve dentro de {USER_ROOT}.", error_code="PATH_NOT_ALLOWED")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except OSError as e:
        return _finish(t, "failed", f"Não consegui gravar o arquivo: {e}", error_code="WRITE_FAILED")
    want = hashlib.sha256(content.encode("utf-8")).hexdigest()
    checks = [run_check({"type": "file_exists", "path": str(p)}),
              run_check({"type": "file_sha256", "path": str(p), "sha256": want})]
    ok = all(c["ok"] for c in checks)
    _finish(t, "completed" if ok else "failed",
            f"Arquivo criado e conferido: {p}" if ok else "O arquivo foi gravado mas a conferência falhou.",
            {"verified": ok, "checks": checks}, None if ok else "VERIFY_FAILED")


def act_powershell(t, body):
    cmd = str(body.get("command", "")).strip()
    if not cmd:
        return _finish(t, "failed", "Campo command vazio.", error_code="EMPTY_COMMAND")
    timeout = min(int(body.get("timeout_s") or 60), MAX_TIMEOUT_S)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return _finish(t, "failed", f"Comando excedeu {timeout}s.", error_code="TIMEOUT")
    except OSError as e:
        return _finish(t, "failed", f"Não consegui iniciar o PowerShell: {e}", error_code="SPAWN_FAILED")
    ev = {"verified": False, "checks": [], "exit_code": r.returncode,
          "stdout_tail": r.stdout[-2000:], "stderr_tail": r.stderr[-2000:]}
    if r.returncode != 0:
        return _finish(t, "failed", f"O comando terminou com código {r.returncode}.", ev, "NONZERO_EXIT")
    verify = body.get("verify") or []
    if verify:
        ev["checks"] = [run_check(c) for c in verify]
        ev["verified"] = all(c["ok"] for c in ev["checks"])
        if not ev["verified"]:
            return _finish(t, "failed", "O comando rodou, mas o efeito esperado NÃO foi confirmado.", ev, "VERIFY_FAILED")
        return _finish(t, "completed", "Comando executado e efeito verificado.", ev)
    _finish(t, "completed", "Comando executado (exit 0), porém sem verificação independente do efeito.", ev)


ACTIONS = {"ping": act_ping, "create_file": act_create_file, "powershell": act_powershell}


def _run(t, body):
    try:
        ACTIONS[t["action"]](t, body)
    except Exception as e:  # nunca deixar a tarefa presa em running
        _finish(t, "failed", f"Erro interno do Worker: {e}", error_code="INTERNAL")


def _public(t):
    keys = ("task_id", "status", "result_pt", "evidence", "error_code", "started_at", "finished_at", "action")
    return {k: t[k] for k in keys if k in t}


# ---------------------------------------------------------------- rotas
@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "general-worker", "version": VERSION})


@app.post("/task")
def task():
    if not authorized():
        return jsonify({"status": "failed", "error_code": "UNAUTHORIZED", "result_pt": "Token inválido."}), 401
    body = request.get_json(silent=True) or {}
    tid = _safe_id(body.get("task_id"))
    if not tid:
        return jsonify({"status": "failed", "error_code": "BAD_TASK_ID", "result_pt": "task_id ausente ou inválido."}), 400
    action = body.get("action")
    if action not in ACTIONS:
        return jsonify({"task_id": tid, "status": "failed", "error_code": "UNKNOWN_ACTION",
                        "result_pt": f"Ação desconhecida: {action}. Use {', '.join(ACTIONS)}."}), 400

    existing = _load_existing(tid)
    if existing:  # idempotência: mesma tarefa nunca executa duas vezes
        return jsonify({**_public(existing), "duplicate": True})

    t = {"task_id": tid, "action": action, "status": "running", "started_at": now(),
         "result_pt": "Em execução."}
    with _lock:
        _tasks[tid] = t
    _persist(t)
    log(f"task {tid} start action={action}")
    th = threading.Thread(target=_run, args=(t, body), daemon=True)
    th.start()
    wait_s = min(int(body.get("wait_s") or DEFAULT_WAIT_S), 60)
    th.join(timeout=wait_s)
    return jsonify(_public(t))


@app.get("/task/<task_id>")
def task_status(task_id):
    if not authorized():
        return jsonify({"status": "failed", "error_code": "UNAUTHORIZED"}), 401
    tid = _safe_id(task_id)
    t = _load_existing(tid) if tid else None
    if not t:
        return jsonify({"task_id": tid, "status": "failed", "error_code": "NOT_FOUND",
                        "result_pt": "Tarefa desconhecida neste Worker."}), 404
    return jsonify(_public(t))


@app.post("/")
def legacy():
    if not authorized():
        return "unauthorized", 401
    command = (request.get_json(silent=True) or {}).get("command", "")
    if not command:
        return jsonify({"ok": False, "error": "campo command vazio", "legacy": True})
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                           capture_output=True, text=True, timeout=30)
        return jsonify({"ok": r.returncode == 0, "stdout": r.stdout[-4000:], "stderr": r.stderr[-4000:], "legacy": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "legacy": True})


if __name__ == "__main__":
    print(f"General Worker {VERSION} ouvindo na porta 8787")
    app.run(host="0.0.0.0", port=8787, threaded=True)

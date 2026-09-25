"""Testes do contrato do Worker. Uso: python test_worker.py [base_url]
O token é lido de WORKER_TOKEN ou de C:\\general_worker\\worker_token.txt (nunca é impresso)."""
import hashlib, json, os, pathlib, subprocess, sys, time, urllib.request, urllib.error, uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://100.107.36.118:8787").rstrip("/")
TOK = os.environ.get("WORKER_TOKEN") or pathlib.Path(r"C:\general_worker\worker_token.txt").read_text(encoding="utf-8").strip()
results = []


def call(method, path, body=None, token=TOK):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"X-AGENT-TOKEN": token} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw}


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def ps_exists(path):  # verificação FORA do Worker, por outro processo
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"Test-Path -LiteralPath '{path}'"], capture_output=True, text=True)
    return r.stdout.strip() == "True"


uid = uuid.uuid4().hex[:8]
home = pathlib.Path(os.environ["USERPROFILE"])
f1 = home / "general_worker_test" / f"e2e_{uid}.txt"

s, b = call("GET", "/health", token=None)
check("health sem token", s == 200 and b.get("ok"), b)

s, b = call("POST", "/task", {"task_id": "x1", "action": "ping"}, token="errado")
check("token inválido -> 401", s == 401, (s, b))

s, b = call("POST", "/task", {"task_id": f"ping-{uid}", "action": "ping"})
check("ping -> completed mas NÃO verificado", s == 200 and b["status"] == "completed" and b["evidence"]["verified"] is False, b)

content = f"teste-e2e-{uid}"
s, b = call("POST", "/task", {"task_id": f"file-{uid}", "action": "create_file", "path": str(f1), "content": content})
check("create_file -> completed + verified", s == 200 and b["status"] == "completed" and b["evidence"]["verified"] is True, b)
check("arquivo EXISTE no disco (checagem externa)", ps_exists(str(f1)))
check("conteúdo do arquivo confere", f1.exists() and f1.read_text(encoding="utf-8") == content)
check("sha256 da evidência confere", b["evidence"]["checks"][1]["ok"] and
      hashlib.sha256(content.encode()).hexdigest() == b["evidence"]["checks"][0].get("sha256"), b["evidence"])

s2, b2 = call("POST", "/task", {"task_id": f"file-{uid}", "action": "create_file", "path": str(f1), "content": "OUTRO"})
check("mesmo task_id não executa de novo (idempotência)", b2.get("duplicate") is True and f1.read_text(encoding="utf-8") == content, b2)

s, b = call("POST", "/task", {"task_id": f"fail-{uid}", "action": "powershell", "command": "exit 3"})
check("comando com exit 3 -> failed", b["status"] == "failed" and b["error_code"] == "NONZERO_EXIT", b)

s, b = call("POST", "/task", {"task_id": f"nover-{uid}", "action": "powershell", "command": "Write-Output oi"})
check("powershell sem verify -> completed mas verified=false", b["status"] == "completed" and b["evidence"]["verified"] is False, b)

ghost = home / "general_worker_test" / f"nao_criado_{uid}.txt"
s, b = call("POST", "/task", {"task_id": f"vf-{uid}", "action": "powershell", "command": "Write-Output feito",
                              "verify": [{"type": "file_exists", "path": str(ghost)}]})
check("comando 'ok' mas efeito ausente -> failed VERIFY_FAILED", b["status"] == "failed" and b["error_code"] == "VERIFY_FAILED", b)

f2 = home / "general_worker_test" / f"ps_{uid}.txt"
s, b = call("POST", "/task", {"task_id": f"psv-{uid}", "action": "powershell",
                              "command": f"Set-Content -LiteralPath '{f2}' -Value 'ok'",
                              "verify": [{"type": "file_exists", "path": str(f2)}, {"type": "file_contains", "path": str(f2), "text": "ok"}]})
check("powershell + verify -> completed verified", b["status"] == "completed" and b["evidence"]["verified"] is True, b)
check("arquivo do powershell EXISTE (checagem externa)", ps_exists(str(f2)))

s, b = call("POST", "/task", {"task_id": f"slow-{uid}", "action": "powershell", "command": "Start-Sleep 6; Write-Output fim", "wait_s": 1})
check("tarefa lenta -> running", b["status"] == "running", b)
time.sleep(9)
s, b = call("GET", f"/task/slow-{uid}")
check("consulta posterior -> completed", b["status"] == "completed", b)

s, b = call("POST", "/task", {"task_id": f"bad-{uid}", "action": "create_file", "path": r"C:\Windows\Temp\nao_pode.txt", "content": "x"})
check("create_file fora do perfil é recusado", b["status"] == "failed" and b["error_code"] == "PATH_NOT_ALLOWED", b)

s, b = call("GET", "/task/inexistente-123")
check("tarefa desconhecida -> 404", s == 404, (s, b))

s, b = call("POST", "/", {"command": "whoami"})
check("rota legada continua funcionando (sem status)", b.get("ok") is True and "status" not in b, b)

# limpeza
subprocess.run(["powershell", "-NoProfile", "-Command", f"Remove-Item -LiteralPath '{home / 'general_worker_test'}' -Recurse -Force"], capture_output=True)
bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} passaram")
sys.exit(1 if bad else 0)

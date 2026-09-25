#!/usr/bin/env python3
"""Validação estática dos workflows gerados (estrutura, conexões, referências entre nós, sintaxe JS, segredos)."""
import json, pathlib, re, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
errors = []


def err(m):
    errors.append(m)
    print("ERRO:", m)


def validate(path, expect_nodes=None):
    wf = json.loads(path.read_text(encoding="utf-8"))
    names = [n["name"] for n in wf["nodes"]]
    print(f"\n== {path.name}: {len(names)} nós")
    if len(set(names)) != len(names): err("nomes duplicados")
    ids = [n["id"] for n in wf["nodes"]]
    if len(set(ids)) != len(ids): err("ids duplicados")
    nset = set(names)
    incoming = set()
    for src, v in wf["connections"].items():
        if src not in nset: err(f"conexão com origem inexistente: {src}")
        for typ, outs in v.items():
            for o in outs:
                for c in (o or []):
                    incoming.add(c["node"])
                    if c["node"] not in nset: err(f"{src} -> {c['node']} (destino inexistente)")
    triggers = [n["name"] for n in wf["nodes"] if re.search(r"Trigger$|webhook$", n["type"])]
    subnodes = {n["name"] for n in wf["nodes"] if n["type"].startswith("@n8n/n8n-nodes-langchain.") and ("lmChat" in n["type"] or "memory" in n["type"])}
    for n in wf["nodes"]:
        if n["name"] not in incoming and n["name"] not in triggers and n["name"] not in subnodes:
            err(f"nó sem entrada: {n['name']}")
    # referências $('Nome')
    for n in wf["nodes"]:
        blob = json.dumps(n["parameters"], ensure_ascii=False)
        for m in re.finditer(r"\$\('([^']+)'\)", blob.replace("\\'", "'")):
            if m.group(1) not in nset: err(f"{n['name']} referencia nó inexistente: {m.group(1)}")
        if "$vars" in blob or "$env" in blob: err(f"{n['name']} usa $vars/$env")
        for k in ("query", "url", "body", "text", "chatId"):
            v = n["parameters"].get(k)
            if isinstance(v, str) and "{{" in v and not v.startswith("="):
                err(f"{n['name']}.{k} tem {{{{ }}}} sem '=' (não seria expressão)")
    # segredos
    raw = path.read_text(encoding="utf-8")
    for pat in (r"MEU_TOKEN_FORTE_123", r"e4cb4023", r"sk-[A-Za-z0-9]{20,}", r"xi-api-key\"\s*,\s*\"value\"\s*:\s*\"[^={]"):
        if re.search(pat, raw): err(f"possível segredo no JSON: {pat}")
    # sintaxe JS dos Code nodes
    with tempfile.TemporaryDirectory() as td:
        for i, n in enumerate(wf["nodes"]):
            if n["type"] == "n8n-nodes-base.code":
                f = pathlib.Path(td) / f"n{i}.js"
                f.write_text("async function __f($input,$,$json){\n" + n["parameters"]["jsCode"] + "\n}\n", encoding="utf-8")
                r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
                if r.returncode: err(f"sintaxe JS em '{n['name']}': {r.stderr.strip().splitlines()[0:3]}")
    if expect_nodes and len(names) != expect_nodes: err(f"esperava {expect_nodes} nós, tem {len(names)}")
    return wf


validate(ROOT / "GENERAL_V10_EXERCITO.json")
validate(ROOT / "AGENTE_EXECUTOR_v1.json")
print("\nRESULTADO:", "OK — nenhum erro estático" if not errors else f"{len(errors)} erro(s)")
sys.exit(1 if errors else 0)

"""Posta AI (Face, Insta, TikTok, Linkdn): agenda e publica posts na conta do cliente pelo perfil-navegador (proxy SP)."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import auth, mailer, senha_rotas
from app.config import Config, carregar
from app.db import Banco, agora
from app.marcas import MARCAS, PLANOS, por_host, publica
from app.pn import PN, PNErro
from app import admin  # painel /admin e prompts editáveis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("postaai")
ESTATICO = Path(__file__).resolve().parent.parent / "static"
COOKIE = "postaai_s"
VERSAO_INICIO = str(int(time.time()))
EXT = {".jpg": "foto", ".jpeg": "foto", ".png": "foto", ".webp": "foto", ".mp4": "video", ".mov": "video"}
MAX_MIDIA = 300 * 1024 * 1024
TZ_BR = dt.timezone(dt.timedelta(hours=-3))
ESPERA_REENVIO_S = [300, 900, 1800]


def criar_app(cfg: Config | None = None, pn: PN | None = None, llm=None) -> FastAPI:
    cfg = cfg or carregar()
    Path(cfg.dados).mkdir(parents=True, exist_ok=True)
    pasta_midia = Path(cfg.dados) / "midia"
    pasta_midia.mkdir(exist_ok=True)
    db = Banco(os.path.join(cfg.dados, "postaai.db"))
    admin.preparar(db)
    pn = pn or PN(cfg.pn_url, cfg.pn_token)
    app = FastAPI(title="Posta AI", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.db, app.state.pn = cfg, db, pn

    def chamar_llm(msgs: list[dict]) -> str:
        estilo = admin.texto("posta-legendas")
        if estilo and not any(m.get("role") == "system" for m in msgs):
            msgs = [{"role": "system", "content": estilo}] + msgs
        if llm:
            return llm(msgs)
        r = httpx.post(cfg.llm_base + "/chat/completions", headers={"Authorization": f"Bearer {cfg.llm_key}"}, timeout=120,
                       json={"model": cfg.llm_modelo, "messages": msgs, "temperature": 0.7, "max_tokens": 800})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    if cfg.demo_email:
        u = auth.usuario_por_email(db, cfg.demo_email.lower())
        for m in MARCAS:
            db.exec("INSERT INTO assinaturas(usuario,marca,plano,ativo_ate) VALUES(?,?,?,?) ON CONFLICT(usuario,marca) DO UPDATE SET plano=excluded.plano, ativo_ate=excluded.ativo_ate",
                    (u["id"], m, "turbo", agora() + 3650 * 86400))

    # ------------------------------------------------ helpers
    def usuario(request: Request, obrigatorio: bool = True) -> dict | None:
        u = auth.usuario_da_sessao(db, cfg.segredo_sessao, request.cookies.get(COOKIE))
        if not u and obrigatorio:
            raise HTTPException(401, "entre na sua conta")
        return u

    def marca_de(request: Request) -> str:
        q = request.query_params.get("marca")
        return q if q in MARCAS else por_host(request.headers.get("host", ""))

    def assinatura(u: dict, marca: str) -> dict | None:
        a = db.um("SELECT * FROM assinaturas WHERE usuario=? AND marca=?", (u["id"], marca))
        return a if a and a["ativo_ate"] > agora() else None

    def inicio_mes() -> float:
        h = dt.datetime.now(TZ_BR)
        return dt.datetime(h.year, h.month, 1, tzinfo=TZ_BR).timestamp()

    def planos_publicos(marca: str) -> list[dict]:
        return [{"codigo": k, **v, "checkout": cfg.checkouts.get(f"{marca}:{k}") or "", "lancamento_ate": cfg.lancamento_ate} for k, v in PLANOS.items()]

    def resumo(u: dict, marca: str) -> dict:
        a = assinatura(u, marca)
        pl = PLANOS.get(a["plano"]) if a else None
        return {"email": u["email"], "marca": publica(marca), "assinante": bool(a), "plano": a["plano"] if a else None, "ativo_ate": a["ativo_ate"] if a else 0,
                "limite_contas": pl["contas"] if pl else 0, "limite_posts": pl["posts_mes"] if pl else 0,
                "contas": db.um("SELECT COUNT(*) n FROM contas WHERE usuario=? AND marca=? AND estado!='desconectada'", (u["id"], marca))["n"],
                "posts_mes": db.um("SELECT COUNT(*) n FROM posts WHERE usuario=? AND marca=? AND criado>=? AND estado NOT IN ('cancelado','rascunho')", (u["id"], marca, inicio_mes()))["n"],
                "planos": planos_publicos(marca)}

    def chave_pn(conta_id: int) -> str:
        return f"postaai:{conta_id}"

    def minha_conta(u: dict, cid: int) -> dict:
        k = db.um("SELECT * FROM contas WHERE id=? AND usuario=?", (cid, u["id"]))
        if not k:
            raise HTTPException(404, "conta não encontrada")
        return k

    def vista_login(k: dict, r: dict) -> dict:
        passo = r.get("passo") or {}
        if passo.get("tipo") == "conectado":
            db.exec("UPDATE contas SET estado='conectada', atualizado=?, login_id=NULL WHERE id=?", (agora(), k["id"]))
        elif passo.get("tipo") == "erro":
            db.exec("UPDATE contas SET estado='desconectada', atualizado=?, login_id=NULL WHERE id=?", (agora(), k["id"]))
        return {"conta": k["id"], "passo": passo}

    def erro_pn(e: PNErro):
        raise HTTPException(e.status if 400 <= e.status < 600 else 502, e.mensagem)

    @app.exception_handler(json.JSONDecodeError)
    @app.exception_handler(UnicodeDecodeError)
    async def corpo_invalido(request: Request, exc: Exception):
        return JSONResponse({"detail": "corpo inválido (envie JSON em UTF-8)"}, status_code=400)

    @app.get("/health")
    def health():
        return {"ok": True}

    # ------------------------------------------------ login
    def _login(u: dict) -> JSONResponse:
        token = auth.criar_sessao(db, cfg.segredo_sessao, u["id"])
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, token, max_age=auth.SESSAO_S, httponly=True, secure=not cfg.dev, samesite="lax", path="/")
        return resp

    @app.post("/api/entrar/codigo")
    async def pedir_codigo(request: Request):
        email = auth.normalizar_email((await request.json()).get("email"))
        if not email:
            raise HTTPException(422, "e-mail inválido")
        cod, motivo = auth.novo_codigo(db, cfg.segredo_sessao, email)
        if motivo == "espere":
            raise HTTPException(429, "acabamos de mandar um código; espere alguns segundos")
        out = {"ok": True, "enviado": mailer.codigo(cfg, email, cod)}
        if cfg.dev:
            out["codigo_dev"] = cod
        return out

    @app.post("/api/entrar")
    async def entrar(request: Request):
        b = await request.json()
        email = auth.normalizar_email(b.get("email"))
        if not email:
            raise HTTPException(422, "e-mail inválido")
        r = auth.conferir_codigo(db, cfg.segredo_sessao, email, str(b.get("codigo") or ""))
        if r != "ok":
            raise HTTPException(400, {"invalido": "código errado", "expirado": "código vencido; peça outro", "tentativas": "muitas tentativas; peça outro código"}[r])
        return _login(auth.usuario_por_email(db, email))

    senha_rotas.registrar(app, db, cfg, mailer, _login, usuario)

    @app.post("/api/sair")
    def sair(request: Request):
        auth.encerrar_sessao(db, cfg.segredo_sessao, request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/api/marca")
    def marca(request: Request):
        m = marca_de(request)
        return {"marca": publica(m), "planos": planos_publicos(m), "outras": [publica(k) | {"url": "https://" + MARCAS[k]["hosts"][0]} for k in MARCAS if k != m]}

    @app.get("/api/conta")
    def conta(request: Request):
        return resumo(usuario(request), marca_de(request))

    # ------------------------------------------------ contas (login pelo nosso formulário, digitado no servidor)
    @app.get("/api/contas")
    def contas(request: Request):
        u = usuario(request)
        return {"contas": db.todos("SELECT id, rede, rotulo, estado, criado FROM contas WHERE usuario=? AND marca=? AND estado!='desconectada' ORDER BY criado", (u["id"], marca_de(request)))}

    @app.post("/api/contas")
    async def conectar(request: Request):
        u = usuario(request)
        m = marca_de(request)
        b = await request.json()
        r = resumo(u, m)
        if not r["assinante"]:
            raise HTTPException(402, "escolha um plano para conectar sua conta")
        if r["contas"] >= r["limite_contas"]:
            raise HTTPException(402, f"seu plano permite {r['limite_contas']} conta(s); suba de plano para conectar outra")
        if not b.get("aceite"):
            raise HTTPException(422, "aceite os termos para continuar")
        usuario_rede, senha = str(b.get("usuario") or "").strip()[:120], str(b.get("senha") or "")
        if MARCAS[m]["login"] == "senha" and (not usuario_rede or not senha):
            raise HTTPException(422, "informe usuário e senha")
        cur = db.exec("INSERT INTO contas(usuario,marca,rede,rotulo,estado,criado,atualizado) VALUES(?,?,?,?,?,?,?)",
                      (u["id"], m, MARCAS[m]["pn"], usuario_rede, "conectando", agora(), agora()))
        k = db.um("SELECT * FROM contas WHERE id=?", (cur.lastrowid,))
        try:
            res = pn.login(MARCAS[m]["pn"], chave_pn(k["id"]), usuario_rede, senha)
        except PNErro as e:
            db.exec("UPDATE contas SET estado='desconectada' WHERE id=?", (k["id"],))
            erro_pn(e)
        del senha
        db.exec("UPDATE contas SET login_id=? WHERE id=?", (res["id"], k["id"]))
        return vista_login(k, res)

    @app.get("/api/contas/{cid}/login")
    def login_status(cid: int, request: Request):
        k = minha_conta(usuario(request), cid)
        if not k["login_id"]:
            return {"conta": cid, "passo": {"tipo": "conectado" if k["estado"] == "conectada" else "erro"}}
        try:
            return vista_login(k, pn.login_status(k["login_id"]))
        except PNErro as e:
            erro_pn(e)

    @app.post("/api/contas/{cid}/login")
    async def login_responder(cid: int, request: Request):
        k = minha_conta(usuario(request), cid)
        if not k["login_id"]:
            raise HTTPException(409, "comece a conexão de novo")
        valor = str((await request.json()).get("valor") or "")[:200]
        try:
            return vista_login(k, pn.responder(k["login_id"], valor))
        except PNErro as e:
            erro_pn(e)

    @app.delete("/api/contas/{cid}")
    def desconectar(cid: int, request: Request):
        k = minha_conta(usuario(request), cid)
        try:
            if k["login_id"]:
                pn.cancelar(k["login_id"])
            pn.apagar(chave_pn(cid))
        except PNErro:
            pass
        db.exec("UPDATE contas SET estado='desconectada', login_id=NULL WHERE id=?", (cid,))
        db.exec("UPDATE posts SET estado='cancelado' WHERE conta=? AND estado='agendado'", (cid,))
        return {"ok": True}

    # ------------------------------------------------ mídia e posts
    def pasta_usuario(uid: int) -> Path:
        p = pasta_midia / str(uid)
        p.mkdir(exist_ok=True)
        return p

    @app.post("/api/midias")
    async def subir_midia(request: Request):
        u = usuario(request)
        nome = os.path.basename(request.headers.get("x-arquivo") or "arquivo.jpg")
        ext = os.path.splitext(nome)[1].lower()
        if ext not in EXT:
            raise HTTPException(422, "mande foto (JPG, PNG, WEBP) ou vídeo (MP4, MOV)")
        destino = pasta_usuario(u["id"]) / f"{uuid.uuid4().hex}{ext}"
        total = 0
        with open(destino, "wb") as f:
            async for pedaco in request.stream():
                total += len(pedaco)
                if total > MAX_MIDIA:
                    f.close()
                    destino.unlink(missing_ok=True)
                    raise HTTPException(413, "arquivo maior que 300 MB")
                f.write(pedaco)
        if total == 0:
            destino.unlink(missing_ok=True)
            raise HTTPException(422, "arquivo vazio")
        db.exec("INSERT OR REPLACE INTO midias(nome,usuario,tipo,original,tamanho,criado) VALUES(?,?,?,?,?,?)",
                (destino.name, u["id"], EXT[ext], nome[:200], total, agora()))
        return {"nome": destino.name, "tipo": EXT[ext], "url": f"/api/midias/{destino.name}", "original": nome}

    # ------------------------------------------------ biblioteca, lote e planilha (spec 44)
    @app.get("/api/biblioteca")
    def biblioteca(request: Request):
        u = usuario(request)
        itens = db.todos("SELECT nome, tipo, original, tamanho, criado FROM midias WHERE usuario=? ORDER BY criado DESC LIMIT 500", (u["id"],))
        usados = {a for p in db.todos("SELECT arquivos FROM posts WHERE usuario=? AND estado!='cancelado'", (u["id"],)) for a in json.loads(p["arquivos"])}
        return {"itens": [{**i, "url": f"/api/midias/{i['nome']}", "usado": i["nome"] in usados} for i in itens]}

    @app.delete("/api/biblioteca/{nome}")
    def biblioteca_apagar(nome: str, request: Request):
        u = usuario(request)
        if not db.um("SELECT 1 FROM midias WHERE nome=? AND usuario=?", (nome, u["id"])):
            raise HTTPException(404, "não encontrado")
        ativos = db.todos("SELECT arquivos FROM posts WHERE usuario=? AND estado IN ('agendado','rascunho','publicando')", (u["id"],))
        if any(nome in json.loads(p["arquivos"]) for p in ativos):
            raise HTTPException(409, "esse arquivo está num post agendado; cancele o post antes")
        db.exec("DELETE FROM midias WHERE nome=?", (nome,))
        (pasta_usuario(u["id"]) / nome).unlink(missing_ok=True)
        return {"ok": True}

    def conta_pronta(u: dict, m: str, cid) -> dict:
        if not resumo(u, m)["assinante"]:
            raise HTTPException(402, "escolha um plano para agendar")
        k = minha_conta(u, int(cid or 0))
        if k["estado"] != "conectada" or k["marca"] != m:
            raise HTTPException(409, "conecte a conta antes de agendar")
        return k

    def sobra_do_mes(u: dict, m: str) -> int:
        r = resumo(u, m)
        return max(0, r["limite_posts"] - r["posts_mes"])

    def criar_post(u: dict, m: str, k: dict, tipo: str, arquivos: list[str], legenda: str, quando: float, origem: str) -> int:
        validar_post(m, tipo, arquivos, legenda, u["id"])
        return db.exec("INSERT INTO posts(usuario,marca,conta,tipo,legenda,arquivos,quando,criado,origem) VALUES(?,?,?,?,?,?,?,?,?)",
                       (u["id"], m, k["id"], tipo, legenda, json.dumps(arquivos), quando, agora(), origem)).lastrowid

    @app.post("/api/posts/lote")
    async def agendar_lote(request: Request):
        """Vários arquivos da biblioteca viram uma série: um a cada N horas (padrão 24) a partir do início escolhido."""
        u = usuario(request)
        m = marca_de(request)
        b = await request.json()
        k = conta_pronta(u, m, b.get("conta"))
        arquivos = [str(a) for a in b.get("arquivos") or []][:60]
        if not arquivos:
            raise HTTPException(422, "escolha os arquivos da biblioteca")
        sobra = sobra_do_mes(u, m)
        if len(arquivos) > sobra:
            raise HTTPException(402, f"cabem só {sobra} posts neste mês no seu plano")
        inicio = quando_de(b.get("inicio"))
        passo = max(1.0, min(float(b.get("intervalo_horas") or 24), 24 * 7)) * 3600
        base, tema = str(b.get("legenda") or ""), str(b.get("tema") or "").strip()[:400]
        criados, erros = [], []
        for i, a in enumerate(arquivos):
            leg = base
            if not leg and tema:
                try:
                    leg = chamar_llm([{"role": "user", "content": f"Legenda para o {MARCAS[m]['rede']} (post {i + 1} de {len(arquivos)} de uma série). "
                                                                   f"Tema: {tema}. Gancho na primeira linha, chamada para ação e de 3 a 6 hashtags. "
                                                                   "Responda só com a legenda."}]).strip().strip('"')[:MARCAS[m]["limite_legenda"]]
                except Exception:  # noqa: BLE001
                    leg = ""
            try:
                criados.append(criar_post(u, m, k, EXT.get(os.path.splitext(a)[1].lower(), "foto"), [a], leg, inicio + i * passo, "lote"))
            except HTTPException as e:
                erros.append({"arquivo": a, "erro": e.detail})
        return {"criados": len(criados), "erros": erros, "posts": [vista_post(db.um("SELECT * FROM posts WHERE id=?", (p,))) for p in criados]}

    COLUNAS = ["data", "hora", "tipo", "arquivo", "legenda"]

    @app.get("/api/posts/planilha-modelo")
    def planilha_modelo(request: Request):
        u = usuario(request)
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "posts"
        ws.append(COLUNAS)
        ws.append(["20/12/2026", "19:00", "foto", "pizza-margherita.jpg", "Sexta é dia de pizza! Peça pelo link da bio. #pizza"])
        ws.append(["21/12/2026", "12:30", "video", "bastidores.mp4", "Como nasce a nossa massa"])
        ws.append(["22/12/2026", "18:00", "carrossel", "cardapio1.jpg;cardapio2.jpg", "Cardápio novo: arrasta para o lado"])
        for col, largura in zip("ABCDE", (12, 8, 11, 34, 70)):
            ws.column_dimensions[col].width = largura
        caminho = pasta_usuario(u["id"]) / "modelo-posta-ai.xlsx"
        wb.save(caminho)
        return FileResponse(caminho, filename="modelo-posta-ai.xlsx")

    def linhas_planilha(conteudo: bytes, nome: str) -> list[dict]:
        if nome.lower().endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook
            ws = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True).active
            linhas = [["" if c is None else c for c in r] for r in ws.iter_rows(values_only=True)]
        else:
            import csv
            txt = conteudo.decode("utf-8-sig", errors="replace")
            linhas = list(csv.reader(io.StringIO(txt), delimiter=";" if txt.count(";") > txt.count(",") else ","))
        if not linhas:
            return []
        cab = [str(c).strip().lower() for c in linhas[0]]
        if "data" not in cab or not ({"arquivo", "legenda"} & set(cab)):
            raise HTTPException(422, "a planilha precisa das colunas: " + ", ".join(COLUNAS))
        return [dict(zip(cab, r)) for r in linhas[1:] if any(str(x).strip() for x in r)]

    def quando_linha(data, hora) -> float:
        if isinstance(data, dt.datetime):
            d = data
        else:
            d = None
            for f in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
                try:
                    d = dt.datetime.strptime(str(data).strip()[:10], f)
                    break
                except ValueError:
                    continue
            if d is None:
                raise HTTPException(422, f"data inválida: {data}")
        if isinstance(hora, dt.time):
            d = d.replace(hour=hora.hour, minute=hora.minute)
        elif str(hora or "").strip():
            hh, _, mm = str(hora).strip().partition(":")
            try:
                d = d.replace(hour=int(hh), minute=int(mm or 0))
            except ValueError:
                raise HTTPException(422, f"hora inválida: {hora}")
        return quando_de(d.replace(tzinfo=TZ_BR).isoformat())

    @app.post("/api/posts/planilha")
    async def importar_planilha(request: Request):
        """Cada linha vira um post. O arquivo é casado pelo NOME ORIGINAL na biblioteca (suba as mídias antes)."""
        u = usuario(request)
        m = marca_de(request)
        k = conta_pronta(u, m, request.query_params.get("conta"))
        conteudo = await request.body()
        if len(conteudo) > 5 * 1024 * 1024:
            raise HTTPException(413, "planilha maior que 5 MB")
        linhas = linhas_planilha(conteudo, request.headers.get("x-arquivo") or "planilha.csv")
        sobra = sobra_do_mes(u, m)
        if len(linhas) > sobra:
            raise HTTPException(402, f"a planilha tem {len(linhas)} posts e cabem {sobra} neste mês no seu plano")
        por_nome = {i["original"].lower(): i["nome"] for i in db.todos("SELECT nome, original FROM midias WHERE usuario=? ORDER BY criado", (u["id"],))}
        criados, erros = 0, []
        for n, l in enumerate(linhas, start=2):
            try:
                arqs = []
                for nome in [x.strip() for x in str(l.get("arquivo") or "").split(";") if x.strip()]:
                    if nome.lower() not in por_nome:
                        raise HTTPException(422, f"arquivo '{nome}' não está na biblioteca")
                    arqs.append(por_nome[nome.lower()])
                tipo = str(l.get("tipo") or "").strip().lower()
                if not tipo:
                    tipo = "texto" if not arqs else "carrossel" if len(arqs) > 1 else EXT.get(os.path.splitext(arqs[0])[1], "foto")
                criar_post(u, m, k, tipo, arqs, str(l.get("legenda") or "").strip(), quando_linha(l.get("data"), l.get("hora", "")), "planilha")
                criados += 1
            except HTTPException as e:
                erros.append({"linha": n, "erro": e.detail})
        return {"criados": criados, "erros": erros}

    @app.get("/api/midias/{nome}")
    def ver_midia(nome: str, request: Request):
        u = usuario(request)
        if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|jpeg|png|webp|mp4|mov)", nome):
            raise HTTPException(404, "não encontrado")
        p = pasta_usuario(u["id"]) / nome
        if not p.exists():
            raise HTTPException(404, "não encontrado")
        return FileResponse(p)

    def validar_post(m: str, tipo: str, arquivos: list[str], legenda: str, uid: int) -> None:
        mk = MARCAS[m]
        if tipo not in mk["tipos"]:
            raise HTTPException(422, f"no {mk['rede']} dá para postar: {', '.join(mk['tipos'])}")
        if len(legenda) > mk["limite_legenda"]:
            raise HTTPException(422, f"a legenda passa de {mk['limite_legenda']} caracteres")
        for a in arquivos:
            if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|jpeg|png|webp|mp4|mov)", a) or not (pasta_usuario(uid) / a).exists():
                raise HTTPException(422, "arquivo não encontrado; envie de novo")
        tipos = [EXT[os.path.splitext(a)[1]] for a in arquivos]
        if tipo == "foto" and (len(arquivos) != 1 or tipos[0] != "foto"):
            raise HTTPException(422, "post de foto leva 1 foto")
        if tipo == "video" and (len(arquivos) != 1 or tipos[0] != "video"):
            raise HTTPException(422, "post de vídeo leva 1 vídeo")
        if tipo == "carrossel" and not 2 <= len(arquivos) <= 10:
            raise HTTPException(422, "carrossel leva de 2 a 10 arquivos")
        if tipo == "texto" and not legenda.strip():
            raise HTTPException(422, "escreva o texto do post")

    def quando_de(valor) -> float:
        try:
            d = dt.datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(422, "data e hora inválidas")
        if not d.tzinfo:
            d = d.replace(tzinfo=TZ_BR)
        t = d.timestamp()
        if t < agora() - 60:
            raise HTTPException(422, "escolha um horário no futuro")
        return t

    def vista_post(p: dict) -> dict:
        arqs = json.loads(p["arquivos"])
        return {"id": p["id"], "conta": p["conta"], "tipo": p["tipo"], "legenda": p["legenda"], "arquivos": [f"/api/midias/{a}" for a in arqs],
                "quando": p["quando"], "estado": p["estado"], "link": p["link"], "erro": p["erro"], "tentativas": p["tentativas"], "origem": p["origem"]}

    @app.get("/api/posts")
    def posts(request: Request):
        u = usuario(request)
        return {"posts": [vista_post(p) for p in db.todos("SELECT * FROM posts WHERE usuario=? AND marca=? AND estado!='cancelado' ORDER BY quando DESC LIMIT 300", (u["id"], marca_de(request)))]}

    @app.post("/api/posts")
    async def agendar(request: Request):
        u = usuario(request)
        m = marca_de(request)
        b = await request.json()
        r = resumo(u, m)
        if not r["assinante"]:
            raise HTTPException(402, "escolha um plano para agendar")
        if r["posts_mes"] >= r["limite_posts"]:
            raise HTTPException(402, "você usou os posts do plano neste mês; suba de plano para agendar mais")
        k = minha_conta(u, int(b.get("conta") or 0))
        if k["estado"] != "conectada" or k["marca"] != m:
            raise HTTPException(409, "conecte a conta antes de agendar")
        tipo, arquivos, legenda = str(b.get("tipo") or ""), [str(a) for a in b.get("arquivos") or []], str(b.get("legenda") or "")
        validar_post(m, tipo, arquivos, legenda, u["id"])
        quando = quando_de(b.get("quando"))
        rasc = int(b.get("rascunho") or 0)
        if rasc:
            p = db.um("SELECT * FROM posts WHERE id=? AND usuario=? AND estado='rascunho'", (rasc, u["id"]))
            if not p:
                raise HTTPException(404, "rascunho não encontrado")
            db.exec("UPDATE posts SET conta=?, tipo=?, legenda=?, arquivos=?, quando=?, estado='agendado', criado=? WHERE id=?",
                    (k["id"], tipo, legenda, json.dumps(arquivos), quando, agora(), rasc))
            pid = rasc
        else:
            pid = db.exec("INSERT INTO posts(usuario,marca,conta,tipo,legenda,arquivos,quando,criado) VALUES(?,?,?,?,?,?,?,?)",
                          (u["id"], m, k["id"], tipo, legenda, json.dumps(arquivos), quando, agora())).lastrowid
        return vista_post(db.um("SELECT * FROM posts WHERE id=?", (pid,)))

    @app.post("/api/posts/{pid}/{acao}")
    def post_acao(pid: int, acao: str, request: Request):
        u = usuario(request)
        p = db.um("SELECT * FROM posts WHERE id=? AND usuario=?", (pid, u["id"]))
        if not p:
            raise HTTPException(404, "post não encontrado")
        if acao == "cancelar" and p["estado"] in ("agendado", "rascunho", "falhou"):
            db.exec("UPDATE posts SET estado='cancelado' WHERE id=?", (pid,))
        elif acao == "tentar_de_novo" and p["estado"] == "falhou":
            db.exec("UPDATE posts SET estado='agendado', tentativas=0, proxima=NULL, erro=NULL, quando=? WHERE id=?", (agora(), pid))
        else:
            raise HTTPException(409, "ação não permitida agora")
        return vista_post(db.um("SELECT * FROM posts WHERE id=?", (pid,)))

    @app.post("/api/legenda")
    async def legenda(request: Request):
        u = usuario(request)
        m = marca_de(request)
        b = await request.json()
        tema = str(b.get("tema") or "").strip()[:600]
        if len(tema) < 4:
            raise HTTPException(422, "conte em uma frase sobre o que é o post")
        mk = MARCAS[m]
        prompt = (f"Escreva a legenda de um post para o {mk['rede']} em português do Brasil. Tema: {tema}. Tom: {str(b.get('tom') or 'próximo e direto')[:60]}.\n"
                  f"{'Tom profissional, sem gírias, com uma lição ou dado concreto; no máximo 3 hashtags.' if m == 'linkdn' else 'Gancho forte na primeira linha, chamada para ação no fim e de 3 a 8 hashtags.'}\n"
                  f"Máximo {min(mk['limite_legenda'], 1500)} caracteres. Responda só com a legenda, sem aspas.")
        try:
            t = chamar_llm([{"role": "user", "content": prompt}]).strip().strip('"')
        except Exception:  # noqa: BLE001
            raise HTTPException(502, "a IA não respondeu agora; tente de novo")
        return {"legenda": t[: mk["limite_legenda"]]}

    # ------------------------------------------------ worker: publica na hora marcada, reenvia com espera crescente
    def publicar_um(p: dict) -> None:
        k = db.um("SELECT * FROM contas WHERE id=?", (p["conta"],))
        u = db.um("SELECT email FROM usuarios WHERE id=?", (p["usuario"],))
        if not k or k["estado"] != "conectada":
            db.exec("UPDATE posts SET estado='falhou', erro=? WHERE id=?", ("a conta não está conectada; conecte de novo e toque em tentar de novo", p["id"]))
            return
        caminhos = [str(pasta_usuario(p["usuario"]) / a) for a in json.loads(p["arquivos"])]
        try:
            r = pn.publicar(chave_pn(k["id"]), p["tipo"], p["legenda"], caminhos)
            db.exec("UPDATE posts SET estado='publicado', link=?, publicado=?, erro=NULL WHERE id=?", (r.get("link"), agora(), p["id"]))
            return
        except PNErro as e:
            if e.status == 409:  # sessão caiu
                db.exec("UPDATE contas SET estado='caiu', atualizado=? WHERE id=?", (agora(), k["id"]))
                db.exec("UPDATE posts SET estado='falhou', erro=? WHERE id=?", ("a rede pediu para entrar de novo; reconecte a conta", p["id"]))
                mailer.enviar(cfg, u["email"], f"{MARCAS[p['marca']]['nome']}: reconecte sua conta",
                              "A rede pediu para você entrar de novo. Seus posts agendados esperam a reconexão.",
                              f"<p>A rede pediu para você entrar de novo. <a href='{cfg.base_url}/painel'>Reconectar</a></p>")
                return
            erro = e.mensagem
        except Exception as e:  # noqa: BLE001
            erro = f"falha inesperada ({type(e).__name__})"
        t = p["tentativas"] + 1
        if t < len(ESPERA_REENVIO_S) + 1:
            db.exec("UPDATE posts SET estado='agendado', tentativas=?, proxima=?, erro=? WHERE id=?", (t, agora() + ESPERA_REENVIO_S[t - 1], erro, p["id"]))
        else:
            db.exec("UPDATE posts SET estado='falhou', tentativas=?, erro=? WHERE id=?", (t, erro, p["id"]))
            mailer.enviar(cfg, u["email"], f"{MARCAS[p['marca']]['nome']}: um post não foi publicado",
                          f"Tentamos {t} vezes e não deu: {erro}", f"<p>Tentamos {t} vezes e não deu: {erro}</p><p><a href='{cfg.base_url}/painel'>Ver no painel</a></p>")

    def rodar_fila(limite: int = 5) -> int:
        n = 0
        for p in db.todos("SELECT * FROM posts WHERE estado='agendado' AND quando<=? AND (proxima IS NULL OR proxima<=?) ORDER BY quando LIMIT ?", (agora(), agora(), limite)):
            if db.exec("UPDATE posts SET estado='publicando' WHERE id=? AND estado='agendado'", (p["id"],)).rowcount != 1:
                continue
            publicar_um(p)
            n += 1
        return n

    app.state.rodar_fila = rodar_fila
    if cfg.worker:
        db.exec("UPDATE posts SET estado='agendado' WHERE estado='publicando'")  # reinício no meio de uma publicação

        def laco():
            while True:
                try:
                    rodar_fila()
                except Exception:  # noqa: BLE001
                    log.exception("fila")
                time.sleep(20)

        threading.Thread(target=laco, daemon=True, name="fila-posts").start()

    # ------------------------------------------------ Cakto
    @app.post("/api/cakto")
    async def cakto(request: Request):
        cru = await request.body()
        try:
            b = json.loads(cru)
        except ValueError:
            raise HTTPException(400, "json")
        if not cfg.cakto_segredo or not hmac.compare_digest(str(b.get("secret") or ""), cfg.cakto_segredo):
            raise HTTPException(401, "segredo")
        evento = str(b.get("event") or "")
        dados = b.get("data") or {}
        if isinstance(dados, list):
            dados = dados[0] if dados else {}
        eid = str(dados.get("id") or hashlib.sha256(cru).hexdigest()[:24]) + ":" + evento
        if db.um("SELECT 1 FROM eventos_cakto WHERE id=?", (eid,)):
            return {"ok": True, "repetido": True}
        db.exec("INSERT INTO eventos_cakto(id,recebido,corpo) VALUES(?,?,?)", (eid, agora(), cru.decode("utf-8", "replace")[:20000]))
        email = auth.normalizar_email((dados.get("customer") or {}).get("email"))
        alvo = cfg.planos_por_produto.get(str((dados.get("product") or {}).get("id") or ""))
        if not email or not alvo or ":" not in alvo:
            return {"ok": True, "ignorado": "sem email ou produto desconhecido"}
        marca, plano = alvo.split(":", 1)
        u = auth.usuario_por_email(db, email)
        a = db.um("SELECT * FROM assinaturas WHERE usuario=? AND marca=?", (u["id"], marca))
        if evento in ("purchase_approved", "subscription_renewed", "subscription_created"):
            base = max(agora(), a["ativo_ate"] if a else 0)
            db.exec("INSERT INTO assinaturas(usuario,marca,plano,ativo_ate,pedido) VALUES(?,?,?,?,?) ON CONFLICT(usuario,marca) DO UPDATE SET plano=excluded.plano, ativo_ate=excluded.ativo_ate, pedido=excluded.pedido",
                    (u["id"], marca, plano, base + 32 * 86400, str(dados.get("id") or "")))
            return {"ok": True, "liberado": email, "marca": marca}
        if evento in ("refund", "chargeback", "subscription_canceled", "subscription_cancelled"):
            db.exec("UPDATE assinaturas SET ativo_ate=? WHERE usuario=? AND marca=?", (agora(), u["id"], marca))
            return {"ok": True, "revogado": email}
        return {"ok": True, "ignorado": evento}

    # ------------------------------------------------ admin + importação (posts que vêm do Perfilaí, Cortaí e Anima AI)
    def exigir_admin(request: Request):
        chave = request.headers.get("x-admin-key") or ""
        if not cfg.admin_key or not hmac.compare_digest(chave, cfg.admin_key):
            raise HTTPException(401, "chave de admin")

    @app.post("/api/admin/importar")
    async def importar(request: Request):
        """Cria um RASCUNHO para o cliente (ele escolhe conta e horário no painel). Mídia por URL https."""
        exigir_admin(request)
        b = await request.json()
        email = auth.normalizar_email(b.get("email"))
        m = b.get("marca") if b.get("marca") in MARCAS else None
        url = str(b.get("arquivo_url") or "")
        if not email or not m:
            raise HTTPException(422, "email e marca são obrigatórios")
        u = auth.usuario_por_email(db, email)
        arquivos, tipo = [], "texto"
        if url:
            if not url.startswith("https://"):
                raise HTTPException(422, "arquivo_url precisa ser https")
            ext = os.path.splitext(url.split("?")[0])[1].lower() or ".jpg"
            if ext not in EXT:
                raise HTTPException(422, "formato não aceito")
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
                r.raise_for_status()
                destino = pasta_usuario(u["id"]) / f"{uuid.uuid4().hex}{ext}"
                with open(destino, "wb") as f:
                    for pedaco in r.iter_bytes():
                        f.write(pedaco)
            arquivos, tipo = [destino.name], EXT[ext]
        pid = db.exec("INSERT INTO posts(usuario,marca,conta,tipo,legenda,arquivos,quando,estado,origem,criado) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (u["id"], m, 0, tipo, str(b.get("legenda") or "")[:5000], json.dumps(arquivos), agora(), "rascunho", str(b.get("origem") or "importado")[:30], agora())).lastrowid
        return {"ok": True, "rascunho": pid}

    @app.get("/api/admin/resumo")
    def admin_resumo(request: Request):
        exigir_admin(request)
        ativos = db.todos("SELECT marca, plano, COUNT(*) n FROM assinaturas WHERE ativo_ate>? GROUP BY marca, plano", (agora(),))
        mes = agora() - 30 * 86400
        return {"produto": "postaai", "nome": "Posta AI", "url": cfg.base_url, "assinantes": sum(r["n"] for r in ativos),
                "por_plano": {f"{r['marca']}:{r['plano']}": r["n"] for r in ativos},
                "receita_mensal": round(sum(r["n"] * PLANOS[r["plano"]]["preco"] for r in ativos if r["plano"] in PLANOS), 2),
                "cadastros": db.um("SELECT COUNT(*) n FROM usuarios")["n"],
                "publicados_30d": db.um("SELECT COUNT(*) n FROM posts WHERE estado='publicado' AND publicado>?", (mes,))["n"],
                "falhas_30d": db.um("SELECT COUNT(*) n FROM posts WHERE estado='falhou' AND criado>?", (mes,))["n"],
                "na_fila": db.um("SELECT COUNT(*) n FROM posts WHERE estado IN ('agendado','publicando')")["n"]}

    # ------------------------------------------------ páginas
    def pagina(nome: str, request: Request) -> HTMLResponse:
        m = marca_de(request)
        mk = MARCAS[m]
        html = (ESTATICO / nome).read_text(encoding="utf-8")
        for chave, valor in {"{{NOME}}": mk["nome"], "{{REDE}}": mk["rede"], "{{COR}}": mk["cor"], "{{MARCA_JSON}}": json.dumps(publica(m), ensure_ascii=False)}.items():
            html = html.replace(chave, valor)
        v = os.environ.get("GIT_COMMIT") or VERSAO_INICIO
        return HTMLResponse(html.replace('.css"', f'.css?v={v}"').replace('.js"', f'.js?v={v}"'))

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request):
        return pagina("index.html", request)

    @app.get("/painel", response_class=HTMLResponse)
    def painel(request: Request):
        if not usuario(request, obrigatorio=False):
            return RedirectResponse("/?entrar=1", status_code=303)
        return pagina("painel.html", request)

    @app.get("/termos", response_class=HTMLResponse)
    def termos(request: Request):
        return pagina("termos.html", request)

    app.include_router(admin.rotas(db, cfg.segredo_sessao, """SELECT email, criado, plano, ativo_ate, (ativo_ate > strftime('%s','now')) ativo
        FROM usuarios ORDER BY criado DESC""", seguro=not cfg.dev))

    @app.get("/admin", response_class=HTMLResponse)
    def pagina_admin():
        return FileResponse(ESTATICO / "admin.html")

    app.mount("/s", StaticFiles(directory=ESTATICO), name="estatico")
    return app


app = criar_app() if os.environ.get("POSTAAI_SEM_APP") != "1" else None

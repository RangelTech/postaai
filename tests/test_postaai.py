"""Posta AI com perfil-navegador falso: conectar (2FA), subir mídia, agendar, publicar, reenviar, sessão que cai, Cakto."""
from produtos_core.teste import entrar
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["POSTAAI_SEM_APP"] = "1"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Config  # noqa: E402
from app.main import criar_app  # noqa: E402
from app.pn import PN  # noqa: E402


class PNFalso:
    def __init__(self):
        self.publicados, self.falhar, self.caiu = [], 0, False

    def handler(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        b = json.loads(req.content or b"{}") if req.content else {}
        assert req.headers["authorization"] == "Bearer tk"
        if p == "/logins":
            if b["usuario"] == "2fa":
                return httpx.Response(200, json={"id": "L1", "passo": {"tipo": "codigo_2fa", "campos": [{"id": "codigo"}]}})
            return httpx.Response(200, json={"id": "L0", "passo": {"tipo": "conectado"}})
        if p == "/logins/L1/responder":
            return httpx.Response(200, json={"id": "L1", "passo": {"tipo": "conectado" if b["valor"] == "123456" else "codigo_2fa"}})
        if p.endswith("/publicar"):
            if self.caiu:
                return httpx.Response(409, json={"detail": "A rede derrubou a sessão. Conecte de novo."})
            if self.falhar:
                self.falhar -= 1
                return httpx.Response(502, json={"detail": "a rede não respondeu"})
            self.publicados.append(b)
            return httpx.Response(200, json={"ok": True, "link": f"https://www.instagram.com/p/X{len(self.publicados)}/"})
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def amb(tmp_path):
    f = PNFalso()
    cfg = Config(dados=str(tmp_path), segredo_sessao="s", dev=True, pn_token="tk", cakto_segredo="ck", worker=False,
                 planos_por_produto={"p-insta-start": "insta:start"}, admin_key="adm")
    app = criar_app(cfg, pn=PN("http://pn", "tk", transport=httpx.MockTransport(f.handler)), llm=lambda m: "Legenda pronta #promo")
    c = TestClient(app, base_url="http://posta-insta.rangeltech.net")
    entrar(c, "loja@x.com")
    return c, f, app


def comprar(c):
    assert c.post("/api/cakto", json={"secret": "ck", "event": "purchase_approved", "data": {"id": "1", "customer": {"email": "loja@x.com"}, "product": {"id": "p-insta-start"}}}).json()["liberado"]


def conectar(c, usuario="loja"):
    r = c.post("/api/contas", json={"aceite": True, "usuario": usuario, "senha": "x"}).json()
    return r["conta"], r


def subir(c, nome="foto.jpg", dados=b"\xff\xd8jpeg"):
    return c.post("/api/midias", content=dados, headers={"x-arquivo": nome}).json()


def em(segundos):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + segundos))


def test_conectar_com_2fa_e_limite(amb):
    c, _, _ = amb
    assert c.post("/api/contas", json={"aceite": True, "usuario": "a", "senha": "b"}).status_code == 402
    comprar(c)
    assert c.post("/api/contas", json={"usuario": "a", "senha": "b"}).status_code == 422
    cid, r = conectar(c, "2fa")
    assert r["passo"]["tipo"] == "codigo_2fa"
    assert c.post(f"/api/contas/{cid}/login", json={"valor": "000"}).json()["passo"]["tipo"] == "codigo_2fa"
    assert c.post(f"/api/contas/{cid}/login", json={"valor": "123456"}).json()["passo"]["tipo"] == "conectado"
    assert c.get("/api/contas").json()["contas"][0]["estado"] == "conectada"
    assert c.post("/api/contas", json={"aceite": True, "usuario": "b", "senha": "c"}).status_code == 402  # Start = 1 conta


def test_agendar_publicar_e_link(amb):
    c, f, app = amb
    comprar(c)
    cid, _ = conectar(c)
    m = subir(c)
    assert m["tipo"] == "foto"
    assert c.post("/api/posts", json={"conta": cid, "tipo": "video", "arquivos": [m["nome"]], "quando": em(60)}).status_code == 422
    assert c.post("/api/posts", json={"conta": cid, "tipo": "foto", "arquivos": [m["nome"]], "quando": "2020-01-01T10:00:00"}).status_code == 422
    p = c.post("/api/posts", json={"conta": cid, "tipo": "foto", "legenda": "Oi", "arquivos": [m["nome"]], "quando": em(-30) if False else em(1)}).json()
    assert p["estado"] == "agendado"
    app.state.db.exec("UPDATE posts SET quando=? WHERE id=?", (time.time() - 1, p["id"]))
    assert app.state.rodar_fila() == 1
    pp = c.get("/api/posts").json()["posts"][0]
    assert pp["estado"] == "publicado" and pp["link"].startswith("https://www.instagram.com/p/")
    assert f.publicados[0]["tipo"] == "foto" and f.publicados[0]["legenda"] == "Oi" and f.publicados[0]["arquivos"][0]["base64"]


def test_reenvio_e_falha(amb):
    c, f, app = amb
    comprar(c)
    cid, _ = conectar(c)
    m = subir(c)
    p = c.post("/api/posts", json={"conta": cid, "tipo": "foto", "arquivos": [m["nome"]], "quando": em(1)}).json()
    f.falhar = 10
    for _ in range(4):
        app.state.db.exec("UPDATE posts SET quando=?, proxima=NULL WHERE id=? AND estado='agendado'", (time.time() - 1, p["id"]))
        app.state.rodar_fila()
    pp = c.get("/api/posts").json()["posts"][0]
    assert pp["estado"] == "falhou" and pp["tentativas"] == 4 and "não respondeu" in pp["erro"]
    f.falhar = 0
    assert c.post(f"/api/posts/{p['id']}/tentar_de_novo").json()["estado"] == "agendado"
    app.state.rodar_fila()
    assert c.get("/api/posts").json()["posts"][0]["estado"] == "publicado"


def test_sessao_caiu_marca_conta(amb):
    c, f, app = amb
    comprar(c)
    cid, _ = conectar(c)
    m = subir(c)
    c.post("/api/posts", json={"conta": cid, "tipo": "foto", "arquivos": [m["nome"]], "quando": em(1)})
    app.state.db.exec("UPDATE posts SET quando=?", (time.time() - 1,))
    f.caiu = True
    app.state.rodar_fila()
    assert c.get("/api/contas").json()["contas"][0]["estado"] == "caiu"
    assert "entrar de novo" in c.get("/api/posts").json()["posts"][0]["erro"]


def test_midia_validacao_e_isolamento(amb):
    c, _, app = amb
    assert c.post("/api/midias", content=b"x", headers={"x-arquivo": "a.exe"}).status_code == 422
    m = subir(c)
    assert c.get(m["url"]).status_code == 200
    c2 = TestClient(app, base_url="http://posta-insta.rangeltech.net")
    entrar(c2, "outro@x.com")
    assert c2.get(m["url"]).status_code == 404


def test_legenda_ia_e_importar(amb):
    c, _, _ = amb
    assert c.post("/api/legenda", json={"tema": "promoção de pizza na sexta"}).json()["legenda"] == "Legenda pronta #promo"
    assert c.post("/api/admin/importar", json={"email": "loja@x.com", "marca": "insta"}, headers={"x-admin-key": "errada"}).status_code == 401
    r = c.post("/api/admin/importar", json={"email": "loja@x.com", "marca": "insta", "legenda": "do Perfilaí", "origem": "perfilai"}, headers={"x-admin-key": "adm"}).json()
    assert r["rascunho"]
    assert c.get("/api/posts").json()["posts"][0]["estado"] == "rascunho"


def test_marca_e_tipos(amb):
    c, _, app = amb
    t = TestClient(app, base_url="http://posta-tiktok.rangeltech.net")
    assert t.get("/api/marca").json()["marca"]["tipos"] == ["video"]
    assert "Posta AI TikTok" in t.get("/").text


def test_quando_com_z(amb):
    c, _, _ = amb
    comprar(c)
    cid, _ = conectar(c)
    m = subir(c)
    q = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 3600))
    assert c.post("/api/posts", json={"conta": cid, "tipo": "foto", "arquivos": [m["nome"]], "quando": q}).status_code == 200


def test_biblioteca_lote_e_planilha(amb):
    import io as _io
    from openpyxl import Workbook, load_workbook
    c, f, app = amb
    comprar(c)
    k, _ = conectar(c)
    a = subir(c, "pizza.jpg")
    b = subir(c, "massa.jpg")
    v = subir(c, "bastidores.mp4", b"\x00\x00\x00\x18ftypmp42")
    bib = c.get("/api/biblioteca").json()["itens"]
    assert {i["original"] for i in bib} == {"pizza.jpg", "massa.jpg", "bastidores.mp4"} and not any(i["usado"] for i in bib)
    # lote: 2 arquivos, um por dia, legenda da IA a partir do tema
    r = c.post("/api/posts/lote", json={"conta": k, "arquivos": [a["nome"], b["nome"]], "inicio": em(3600), "tema": "pizza de forno a lenha"}).json()
    assert r["criados"] == 2 and r["erros"] == []
    q = sorted(p["quando"] for p in r["posts"])
    assert round((q[1] - q[0]) / 3600) == 24 and all(p["legenda"] == "Legenda pronta #promo" for p in r["posts"])
    assert c.delete(f"/api/biblioteca/{a['nome']}").status_code == 409  # está num post agendado
    # modelo da planilha baixa e abre
    m = c.get("/api/posts/planilha-modelo")
    assert m.status_code == 200 and load_workbook(_io.BytesIO(m.content)).active["A1"].value == "data"
    # planilha: uma linha boa (vídeo pelo nome original) e uma com arquivo que não existe
    wb = Workbook()
    ws = wb.active
    ws.append(["data", "hora", "tipo", "arquivo", "legenda"])
    ws.append(["31/12/2030", "19:30", "video", "bastidores.mp4", "Bastidores da massa"])
    ws.append(["31/12/2030", "20:00", "foto", "nao-existe.jpg", "x"])
    buf = _io.BytesIO()
    wb.save(buf)
    r = c.post(f"/api/posts/planilha?conta={k}", content=buf.getvalue(), headers={"x-arquivo": "posts.xlsx"}).json()
    assert r["criados"] == 1 and r["erros"][0]["linha"] == 3 and "biblioteca" in r["erros"][0]["erro"]
    # CSV com ponto e vírgula também
    csv = "data;hora;arquivo;legenda\n31/12/2030;21:00;massa.jpg;Massa de 72 horas\n".encode()
    r = c.post(f"/api/posts/planilha?conta={k}", content=csv, headers={"x-arquivo": "posts.csv"}).json()
    assert r["criados"] == 1
    assert len(c.get("/api/posts").json()["posts"]) == 4

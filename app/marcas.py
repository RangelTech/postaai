"""Quatro produtos, um código: Posta AI Face, Insta, TikTok e Linkdn (spec 44 5.5). A marca vem do host."""
from __future__ import annotations

MARCAS = {
    "insta": {"nome": "Posta AI Insta", "rede": "Instagram", "pn": "instagram", "cor": "#e1306c", "hosts": ["posta-insta.rangeltech.net", "posta-ai.rangeltech.net"],
              "tipos": ["foto", "video", "carrossel"], "login": "senha", "limite_legenda": 2200,
              "dica": "Foto, Reels ou carrossel (até 10 fotos)."},
    "face": {"nome": "Posta AI Face", "rede": "Facebook", "pn": "facebook", "cor": "#1877f2", "hosts": ["posta-face.rangeltech.net"],
             "tipos": ["texto", "foto", "video", "carrossel"], "login": "senha", "limite_legenda": 5000,
             "dica": "Texto, foto ou vídeo no seu perfil."},
    "tiktok": {"nome": "Posta AI TikTok", "rede": "TikTok", "pn": "tiktok", "cor": "#00f2ea", "hosts": ["posta-tiktok.rangeltech.net"],
               "tipos": ["video"], "login": "qr", "limite_legenda": 2000,
               "dica": "Vídeo vertical com legenda e hashtags."},
    "linkdn": {"nome": "Posta AI Linkdn", "rede": "LinkedIn", "pn": "linkedin", "cor": "#0a66c2", "hosts": ["posta-linkdn.rangeltech.net"],
               "tipos": ["texto", "foto", "video"], "login": "senha", "limite_legenda": 3000,
               "dica": "Texto profissional, com foto ou vídeo."},
}

PLANOS = {
    "start": {"nome": "Start", "preco": 24.90, "contas": 1, "posts_mes": 30,
              "itens": ["1 conta conectada", "30 posts agendados por mês", "Legenda escrita pela IA", "Reenvio automático se falhar"]},
    "pro": {"nome": "Pro", "preco": 49.90, "contas": 2, "posts_mes": 90,
            "itens": ["2 contas conectadas", "90 posts por mês", "Calendário da semana", "Recebe os posts do Perfilaí, Cortaí e Anima AI"]},
    "turbo": {"nome": "Top", "preco": 97.00, "contas": 5, "posts_mes": 300,
              "itens": ["5 contas conectadas", "300 posts por mês", "Tudo do Pro", "Para quem gerencia redes de clientes"]},
}


def por_host(host: str) -> str:
    h = (host or "").split(":")[0].lower()
    for k, m in MARCAS.items():
        if h in m["hosts"]:
            return k
    return "insta"


def publica(k: str) -> dict:
    m = MARCAS[k]
    return {"codigo": k, "nome": m["nome"], "rede": m["rede"], "cor": m["cor"], "tipos": m["tipos"], "login": m["login"],
            "limite_legenda": m["limite_legenda"], "dica": m["dica"]}

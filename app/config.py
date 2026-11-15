"""Configuração por variável de ambiente (segredos em /opt/platform/secrets/postaai.env na VPS)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    dados: str = "/data"
    base_url: str = "https://posta-ai.rangeltech.net"
    llm_base: str = "https://qwen.rangeltech.net/v1"
    llm_key: str = ""
    llm_modelo: str = "rt-planejar"
    segredo_sessao: str = "dev"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_senha: str = ""
    smtp_from: str = "Posta AI <contato@rangeltech.net>"
    cakto_segredo: str = ""
    checkouts: dict = field(default_factory=dict)
    planos_por_produto: dict = field(default_factory=dict)
    pn_url: str = "http://perfil-navegador:8000"
    pn_token: str = ""
    admin_key: str = ""
    demo_email: str = ""
    demo_senha: str = ""
    lancamento_ate: str = "2026-12-15"
    dev: bool = False
    worker: bool = True


def carregar() -> Config:
    e = os.environ.get
    return Config(
        dados=e("POSTAAI_DADOS", "/data"),
        base_url=e("POSTAAI_BASE_URL", "https://posta-ai.rangeltech.net").rstrip("/"),
        llm_base=e("POSTAAI_LLM_BASE", "https://qwen.rangeltech.net/v1").rstrip("/"),
        llm_key=e("POSTAAI_LLM_KEY", ""),
        llm_modelo=e("POSTAAI_LLM_MODELO", "rt-planejar"),
        segredo_sessao=e("POSTAAI_SEGREDO_SESSAO", "dev"),
        smtp_host=e("SMTP_HOST", ""),
        smtp_port=int(e("SMTP_PORT", "587") or 587),
        smtp_user=e("SMTP_USER", ""),
        smtp_senha=e("SMTP_PASSWORD", ""),
        smtp_from=e("POSTAAI_SMTP_FROM", "Posta AI <contato@rangeltech.net>"),
        cakto_segredo=e("POSTAAI_CAKTO_SEGREDO", ""),
        checkouts=json.loads(e("POSTAAI_CHECKOUTS", "") or "{}"),
        planos_por_produto=json.loads(e("POSTAAI_PLANOS_CAKTO", "") or "{}"),
        pn_url=e("POSTAAI_PN_URL", "http://perfil-navegador:8000").rstrip("/"),
        pn_token=e("POSTAAI_PN_TOKEN", ""),
        admin_key=e("POSTAAI_ADMIN_KEY", ""),
        demo_email=e("POSTAAI_DEMO_EMAIL", ""),
        demo_senha=e("POSTAAI_DEMO_SENHA", ""),
        lancamento_ate=e("POSTAAI_LANCAMENTO_ATE", "2026-12-15"),
        dev=e("POSTAAI_DEV", "") == "1",
        worker=e("POSTAAI_WORKER", "1") == "1",
    )

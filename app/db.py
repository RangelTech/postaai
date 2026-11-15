"""Banco do Posta AI: SQLite num volume (/data). Hora em epoch (s)."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, criado REAL NOT NULL,
  plano TEXT NOT NULL DEFAULT 'teste', ativo_ate REAL NOT NULL DEFAULT 0, pedido TEXT);
CREATE TABLE IF NOT EXISTS codigos (email TEXT PRIMARY KEY, hash TEXT NOT NULL, expira REAL NOT NULL, tentativas INTEGER NOT NULL DEFAULT 0, enviado REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessoes (hash TEXT PRIMARY KEY, usuario INTEGER NOT NULL, expira REAL NOT NULL);
CREATE TABLE IF NOT EXISTS eventos_cakto (id TEXT PRIMARY KEY, recebido REAL NOT NULL, corpo TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assinaturas (usuario INTEGER NOT NULL, marca TEXT NOT NULL, plano TEXT NOT NULL, ativo_ate REAL NOT NULL, pedido TEXT,
  PRIMARY KEY (usuario, marca));

-- conta conectada: a sessão fica no perfil-navegador (conta "postaai:<id>"); aqui só o estado
CREATE TABLE IF NOT EXISTS contas (
  id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL, marca TEXT NOT NULL, rede TEXT NOT NULL,
  rotulo TEXT NOT NULL DEFAULT '', estado TEXT NOT NULL DEFAULT 'conectando',   -- conectando | conectada | caiu | desconectada
  login_id TEXT, criado REAL NOT NULL, atualizado REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS contas_usuario ON contas(usuario, marca);

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL, marca TEXT NOT NULL, conta INTEGER NOT NULL,
  tipo TEXT NOT NULL,                       -- foto | video | carrossel | texto
  legenda TEXT NOT NULL DEFAULT '',
  arquivos TEXT NOT NULL DEFAULT '[]',      -- JSON [nome no disco]
  quando REAL NOT NULL,
  estado TEXT NOT NULL DEFAULT 'agendado',  -- rascunho | agendado | publicando | publicado | falhou | cancelado
  tentativas INTEGER NOT NULL DEFAULT 0, proxima REAL, link TEXT, erro TEXT, origem TEXT NOT NULL DEFAULT 'painel',
  criado REAL NOT NULL, publicado REAL
);
CREATE INDEX IF NOT EXISTS posts_fila ON posts(estado, proxima, quando);
CREATE INDEX IF NOT EXISTS posts_usuario ON posts(usuario, marca, quando);
"""


class Banco:
    def __init__(self, caminho: str):
        self._trava = threading.Lock()
        self.con = sqlite3.connect(caminho, check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(ESQUEMA)

    @contextmanager
    def tx(self):
        with self._trava:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                yield self.con
                self.con.execute("COMMIT")
            except BaseException:
                self.con.execute("ROLLBACK")
                raise

    def um(self, sql: str, args=()):
        with self._trava:
            r = self.con.execute(sql, args).fetchone()
        return dict(r) if r else None

    def todos(self, sql: str, args=()):
        with self._trava:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def exec(self, sql: str, args=()):
        with self._trava:
            return self.con.execute(sql, args)


def agora() -> float:
    return time.time()

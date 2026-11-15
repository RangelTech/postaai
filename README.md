# Posta AI (Face, Insta, TikTok, Linkdn)

Agenda e publica posts na conta do cliente. Um código, quatro marcas pelo host:
`posta-insta`, `posta-face`, `posta-tiktok`, `posta-linkdn` (`.rangeltech.net`; `posta-ai` = Insta).

- **Conexão** pelo formulário nosso: a senha vai para o `perfil-navegador` (rede interna), que entra na rede **pelo proxy SP**
  e guarda só a sessão, cifrada. TikTok conecta por QR. A tela mostra cada passo (código 2FA, código por e-mail, escolha,
  aprovar no celular, QR, captcha por toque na imagem).
- **Agenda:** foto, vídeo (Reels), carrossel ou texto conforme a rede; legenda com IA; calendário por dia; rascunhos.
- **Worker:** publica na hora marcada; se a rede falhar, tenta de novo em 5, 15 e 30 min e avisa por e-mail; sessão que cai
  marca a conta para reconectar.
- **Importação:** `POST /api/admin/importar` (x-admin-key) cria rascunho para o cliente (Perfilaí, Cortaí, Anima AI).
- Login com senha/código/esqueci (módulo comum), Cakto por marca, painel do ecossistema (`/api/admin/resumo`).

Testes: `pip install -r requirements-dev.txt && python -m pytest -q` (perfil-navegador falso).
Deploy: release neste repo, implantação só pelo `vps_rt_infra`.

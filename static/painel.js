// Painel do Posta AI: agenda (novo post, legenda com IA, rascunhos), conta conectada (passos do login) e plano.
;(() => {
  const $ = (q, r = document) => r.querySelector(q)
  const $$ = (q, r = document) => [...r.querySelectorAll(q)]
  const M = window.MARCA
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  async function api(url, op = {}) {
    const r = await fetch(url, { ...op, headers: { 'Content-Type': 'application/json', ...(op.headers || {}) } })
    let j = {}
    try { j = await r.json() } catch {}
    if (r.status === 401) { location.href = '/?entrar=1'; throw new Error('entre de novo') }
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Não deu certo. Tente de novo.')
    return j
  }
  const post = (url, corpo) => api(url, { method: 'POST', body: JSON.stringify(corpo || {}) })
  const NOMES = { foto: 'Foto', video: 'Vídeo', carrossel: 'Carrossel', texto: 'Só texto' }
  const ESTADOS = { rascunho: 'rascunho', agendado: 'agendado', publicando: 'publicando…', publicado: 'publicado', falhou: 'não publicou' }
  let CONTA = null, CONTAS = []

  function abrirAba(nome) {
    $$('[data-aba]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.aba === nome)))
    $$('[data-painel]').forEach((p) => (p.hidden = p.dataset.painel !== nome))
    history.replaceState(null, '', '#' + nome)
    ;({ agenda: carregarPosts, contas: carregarContas, plano: carregarPlano })[nome]?.()
  }
  $$('[data-aba]').forEach((b) => (b.onclick = () => abrirAba(b.dataset.aba)))
  $('#sair').onclick = async () => { await post('/api/sair'); location.href = '/' }
  for (const m of $$('.modal')) m.addEventListener('click', (e) => { if (e.target === m || e.target.closest('[data-fechar]')) { m.hidden = true; clearTimeout(poll) } })

  async function carregarConta() {
    CONTA = await api('/api/conta')
    CONTAS = (await api('/api/contas')).contas
    const av = $('#aviso')
    const conectadas = CONTAS.filter((c) => c.estado === 'conectada')
    if (!CONTA.assinante) { av.hidden = false; av.innerHTML = `<span>Escolha um plano para conectar e agendar.</span><button class="btn btn-pri sm" data-ir="plano">Ver planos</button>` }
    else if (CONTAS.some((c) => c.estado === 'caiu')) { av.hidden = false; av.innerHTML = `<span>A rede pediu para você entrar de novo. Os posts esperam a reconexão.</span><button class="btn btn-pri sm" data-ir="contas">Reconectar</button>` }
    else if (!conectadas.length) { av.hidden = false; av.innerHTML = `<span>Falta conectar sua conta do ${esc(M.rede)}.</span><button class="btn btn-pri sm" data-ir="contas">Conectar</button>` }
    else av.hidden = true
    $$('[data-ir]', av).forEach((b) => (b.onclick = () => abrirAba(b.dataset.ir)))
  }

  // ------------------------------------------------ agenda
  const diaDe = (ts) => new Date(ts * 1000).toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })
  const hora = (ts) => new Date(ts * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  const thumb = (p) => { const a = p.arquivos[0]; if (!a) return '<span class="thumb">texto</span>'; return /\.(mp4|mov)$/i.test(a) ? `<span class="thumb"><video src="${esc(a)}" muted preload="metadata"></video></span>` : `<span class="thumb"><img src="${esc(a)}" alt="" loading="lazy"></span>` }
  async function carregarPosts() {
    await carregarConta()
    const j = await api('/api/posts')
    const rasc = j.posts.filter((p) => p.estado === 'rascunho')
    const resto = j.posts.filter((p) => p.estado !== 'rascunho').sort((a, b) => a.quando - b.quando)
    let html = ''
    if (rasc.length) html += `<div class="dia-tit">Rascunhos (vindos dos outros produtos)</div>` + rasc.map(linha).join('')
    let dia = ''
    for (const p of resto) { const d = diaDe(p.quando); if (d !== dia) { html += `<div class="dia-tit">${esc(d)}</div>`; dia = d } html += linha(p) }
    $('#lista-posts').innerHTML = html || `<p class="vazio">Nenhum post ainda. Toque em "Novo post" para agendar o primeiro.</p>`
    $$('[data-acao]').forEach((b) => (b.onclick = async () => {
      const id = b.dataset.id, a = b.dataset.acao
      if (a === 'agendar') return abrirNovo(j.posts.find((p) => p.id === +id))
      if (a === 'cancelar' && !confirm('Cancelar este post?')) return
      try { await post(`/api/posts/${id}/${a}`); carregarPosts() } catch (err) { alert(err.message) }
    }))
  }
  function linha(p) {
    const acoes = []
    if (p.estado === 'publicado' && p.link) acoes.push(`<a class="btn btn-ghost sm" href="${esc(p.link)}" target="_blank" rel="noopener">Ver na rede</a>`)
    if (p.estado === 'falhou') acoes.push(`<button class="btn btn-pri sm" data-acao="tentar_de_novo" data-id="${p.id}">Tentar de novo</button>`)
    if (p.estado === 'rascunho') acoes.push(`<button class="btn btn-pri sm" data-acao="agendar" data-id="${p.id}">Agendar</button>`)
    if (['agendado', 'rascunho', 'falhou'].includes(p.estado)) acoes.push(`<button class="btn btn-ghost sm" data-acao="cancelar" data-id="${p.id}">Cancelar</button>`)
    return `<div class="post">${thumb(p)}<div><b>${p.estado === 'rascunho' ? esc(p.origem) : hora(p.quando)} · ${esc(NOMES[p.tipo] || p.tipo)}</b> <span class="tag ${esc(p.estado)}">${esc(ESTADOS[p.estado] || p.estado)}</span>
      <p>${esc(p.legenda || '(sem legenda)')}</p>${p.erro && p.estado !== 'publicado' ? `<p style="color:var(--erro)">${esc(p.erro)}${p.estado === 'agendado' ? ' · vamos tentar de novo' : ''}</p>` : ''}</div><div class="acoes">${acoes.join('')}</div></div>`
  }

  function paraLocal(d) { const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}` }
  $('#novo').onclick = () => abrirNovo()
  function abrirNovo(rasc) {
    const conectadas = CONTAS.filter((c) => c.estado === 'conectada')
    if (!conectadas.length) return abrirAba('contas')
    const m = $('#m-post'); m.hidden = false
    let arquivos = (rasc?.arquivos || []).map((u) => u.split('/').pop())
    $('#mp-corpo').innerHTML = `<h3 id="mp-tit">${rasc ? 'Agendar rascunho' : 'Novo post'}</h3><p>${esc(M.dica)}</p>
      <label for="p-conta">Conta</label><select id="p-conta">${conectadas.map((c) => `<option value="${c.id}">${esc(c.rotulo || M.rede)}</option>`).join('')}</select>
      <label for="p-tipo">Formato</label><select id="p-tipo">${M.tipos.map((t) => `<option value="${t}" ${rasc?.tipo === t ? 'selected' : ''}>${NOMES[t]}</option>`).join('')}</select>
      <div id="p-arq-bloco"><label>Arquivos</label><label class="btn btn-sec sm" for="p-arq">Escolher foto ou vídeo<input id="p-arq" type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime" multiple hidden></label><div class="midias" id="p-midias"></div></div>
      <label for="p-leg">Legenda</label><textarea id="p-leg" maxlength="${M.limite_legenda}">${esc(rasc?.legenda || '')}</textarea><div class="contador" id="p-cont"></div>
      <div class="linha"><input id="p-tema" placeholder="Sobre o que é o post? A IA escreve a legenda"><button class="btn btn-sec" id="p-ia" type="button">Escrever</button></div>
      <label for="p-quando">Quando publicar</label><input id="p-quando" type="datetime-local" value="${paraLocal(new Date(Date.now() + 3600e3))}">
      <button class="btn btn-pri" style="width:100%;margin-top:16px" id="p-ok">Agendar</button><div class="msg" id="p-msg" role="status"></div>`
    const msg = (t, tipo = '') => { $('#p-msg').textContent = t; $('#p-msg').className = 'msg ' + tipo }
    const cont = () => ($('#p-cont').textContent = `${$('#p-leg').value.length}/${M.limite_legenda}`)
    $('#p-leg').oninput = cont; cont()
    const desenhar = () => { $('#p-midias').innerHTML = arquivos.map((a) => `<span class="m">${/\.(mp4|mov)$/i.test(a) ? `<video src="/api/midias/${a}" muted></video>` : `<img src="/api/midias/${a}" alt="">`}</span>`).join(''); $('#p-arq-bloco').hidden = $('#p-tipo').value === 'texto' }
    $('#p-tipo').onchange = desenhar; desenhar()
    $('#p-arq').onchange = async (e) => {
      for (const f of e.target.files) {
        msg(`Enviando ${f.name}…`)
        try {
          const r = await fetch('/api/midias', { method: 'POST', headers: { 'x-arquivo': f.name }, body: f })
          const j = await r.json().catch(() => ({}))
          if (!r.ok) throw new Error(j.detail || 'não deu para enviar')
          arquivos.push(j.nome)
        } catch (err) { msg(err.message, 'erro') }
      }
      if ($('#p-tipo').value !== 'carrossel') arquivos = arquivos.slice(-1)
      desenhar(); msg('')
    }
    $('#p-ia').onclick = async (e) => {
      const b = e.currentTarget
      b.disabled = true; msg('A IA está escrevendo…')
      try { $('#p-leg').value = (await post('/api/legenda', { tema: $('#p-tema').value })).legenda; cont(); msg('') } catch (err) { msg(err.message, 'erro') }
      b.disabled = false
    }
    $('#p-ok').onclick = async (e) => {
      const b = e.currentTarget
      b.disabled = true
      try {
        await post('/api/posts', { conta: +$('#p-conta').value, tipo: $('#p-tipo').value, legenda: $('#p-leg').value, arquivos: $('#p-tipo').value === 'texto' ? [] : arquivos,
          quando: new Date($('#p-quando').value).toISOString(), rascunho: rasc?.id || 0 })
        m.hidden = true; carregarPosts()
      } catch (err) { msg(err.message, 'erro'); b.disabled = false }
    }
  }

  // ------------------------------------------------ conta conectada (passos do login)
  const TAG = { conectada: 'ok', caiu: 'erro', conectando: '' }
  async function carregarContas() {
    await carregarConta()
    $('#lista-contas').innerHTML = CONTAS.length ? CONTAS.map((k) => `<div class="conta-linha"><div><b>${esc(k.rotulo || M.rede)}</b> <span class="tag ${TAG[k.estado] || ''}">${esc({ conectada: 'Conectada', caiu: 'Precisa entrar de novo', conectando: 'Conectando' }[k.estado] || k.estado)}</span></div>
      <div class="acoes"><button class="btn btn-ghost sm" data-desc="${k.id}">Desconectar</button></div></div>`).join('') : `<p class="vazio">Nenhuma conta conectada.</p>`
    $$('[data-desc]').forEach((b) => (b.onclick = async () => { if (!confirm('Desconectar? Os posts agendados desta conta serão cancelados.')) return; await api('/api/contas/' + b.dataset.desc, { method: 'DELETE' }); carregarContas() }))
  }
  let poll = null
  $('#nova-conta').onclick = () => {
    $('#m-conta').hidden = false
    const qr = M.login === 'qr'
    $('#mc-corpo').innerHTML = `<h3 id="mc-tit">Conectar ${esc(M.rede)}</h3>
      <p>${qr ? 'Vamos mostrar um QR para você ler com o app do TikTok.' : 'Digitado só aqui: a senha vai direto para a rede, a partir de São Paulo, e não fica guardada.'}</p>
      <form id="mc-form">${qr ? '' : `<label for="c-u">Usuário, e-mail ou telefone</label><input id="c-u" autocomplete="off" required>
      <label for="c-s">Senha</label><input id="c-s" type="password" autocomplete="off" required>`}
      <label class="check"><input type="checkbox" id="c-aceite"> <span>Entendo que a publicação não usa a API oficial e que a rede pode pedir para eu entrar de novo. Li os <a href="/termos" target="_blank">termos</a>.</span></label>
      <button class="btn btn-pri" style="width:100%">Continuar</button></form><div class="msg" id="mc-msg"></div>`
    $('#mc-form').onsubmit = async (e) => {
      e.preventDefault()
      if (!$('#c-aceite').checked) { $('#mc-msg').textContent = 'Marque o aceite para continuar.'; $('#mc-msg').className = 'msg erro'; return }
      e.target.querySelector('button').disabled = true
      $('#mc-msg').textContent = 'Entrando na rede… pode levar até um minuto.'; $('#mc-msg').className = 'msg'
      try { mostrarPasso(await post('/api/contas', { aceite: true, usuario: $('#c-u')?.value || '', senha: $('#c-s')?.value || '' })) }
      catch (err) { $('#mc-msg').textContent = err.message; $('#mc-msg').className = 'msg erro'; e.target.querySelector('button').disabled = false }
    }
  }
  function mostrarPasso(r) {
    clearTimeout(poll)
    const p = r.passo || {}, c = $('#mc-corpo'), id = r.conta
    const responder = async (valor) => { c.querySelector('button')?.setAttribute('disabled', ''); try { mostrarPasso(await post(`/api/contas/${id}/login`, { valor })) } catch (err) { alert(err.message) } }
    const esperar = (s) => (poll = setTimeout(async () => { try { mostrarPasso(await api(`/api/contas/${id}/login`)) } catch {} }, Math.max(2, s || 3) * 1000))
    const erro = p.erro && p.tipo !== 'erro' ? `<div class="msg erro">${esc(p.mensagem || 'Tente de novo.')}</div>` : ''
    if (p.tipo === 'conectado') { c.innerHTML = `<h3 id="mc-tit">Conectada!</h3><p>Agora é só agendar o primeiro post.</p><button class="btn btn-pri" style="width:100%" id="mc-fim">Agendar um post</button>`; $('#mc-fim').onclick = () => { $('#m-conta').hidden = true; abrirAba('agenda'); setTimeout(() => abrirNovo(), 400) }; return }
    if (p.tipo === 'erro') { c.innerHTML = `<h3 id="mc-tit">Não conectou</h3><p>${esc(p.mensagem || 'Tente de novo.')}</p><button class="btn btn-sec" style="width:100%" data-fechar>Fechar</button>`; carregarContas(); return }
    if (p.tipo === 'qr') { c.innerHTML = `<h3 id="mc-tit">Leia o QR</h3><p>${esc(p.mensagem)}</p><img src="${esc(p.imagem)}" alt="QR do TikTok" style="width:100%;max-width:280px;display:block;margin:12px auto;border-radius:12px;background:#fff">`; return esperar(p.espera_s) }
    if (p.tipo === 'aprovar_no_celular') { c.innerHTML = `<h3 id="mc-tit">Confirme no celular</h3><p>${esc(p.mensagem)}</p><p class="dim">Esta tela atualiza sozinha.</p>`; return esperar(p.espera_s) }
    if (p.tipo === 'escolha') { c.innerHTML = `<h3 id="mc-tit">Por onde receber o código?</h3><p>${esc(p.mensagem)}</p>${(p.opcoes || []).map((o) => `<button class="btn btn-sec" style="width:100%;margin-top:8px" data-op="${esc(o)}">${esc(o)}</button>`).join('')}`; $$('[data-op]', c).forEach((b) => (b.onclick = () => responder(b.dataset.op))); return }
    if (p.tipo === 'captcha') {
      c.innerHTML = `<h3 id="mc-tit">Verificação da rede</h3><p>${esc(p.mensagem)}</p><div class="captcha"><img src="${esc(p.imagem)}" alt="Tela da verificação" id="cap"></div>`
      $('#cap').onclick = (e) => { const r2 = e.target.getBoundingClientRect(), k = e.target.naturalWidth / r2.width; responder(`${Math.round((e.clientX - r2.left) * k)},${Math.round((e.clientY - r2.top) * k)}`) }
      return
    }
    if (p.tipo === 'codigo_2fa' || p.tipo === 'codigo_email') {
      c.innerHTML = `<h3 id="mc-tit">${p.tipo === 'codigo_2fa' ? 'Código de verificação' : 'Confirme que é você'}</h3><p>${esc(p.mensagem)}</p>
        <form id="cf"><label for="c-cod">Código</label><input id="c-cod" inputmode="numeric" autocomplete="one-time-code" required><button class="btn btn-pri" style="width:100%;margin-top:16px">Continuar</button></form>${erro}`
      $('#cf').onsubmit = (e) => { e.preventDefault(); responder($('#c-cod').value.trim()) }
      return
    }
    c.innerHTML = `<h3 id="mc-tit">Entrando…</h3><p>Aguarde alguns segundos.</p>`; esperar(3)
  }

  // ------------------------------------------------ plano
  async function carregarPlano() {
    await carregarConta()
    const c = CONTA
    $('#meu-plano').innerHTML = c.assinante ? `<h3>Plano ${esc(c.planos.find((p) => p.codigo === c.plano)?.nome || c.plano)}</h3><p class="dim">Vale até ${new Date(c.ativo_ate * 1000).toLocaleDateString('pt-BR')} · ${c.contas}/${c.limite_contas} conta(s) · ${c.posts_mes}/${c.limite_posts} posts neste mês</p>`
      : `<h3>Sem plano ativo</h3><p class="dim">Escolha um plano para conectar e agendar.</p>`
    $('#lista-planos').innerHTML = c.planos.map((p) => `<div class="plano ${p.codigo === c.plano ? 'destaque' : ''}"><h3>${esc(p.nome)}</h3><div class="preco">R$ ${p.preco.toFixed(2).replace('.', ',')}<small>/mês</small></div>
      <ul>${p.itens.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>${p.codigo === c.plano ? '<button class="btn btn-sec" disabled>Seu plano</button>' : p.checkout ? `<a class="btn btn-pri" href="${esc(p.checkout)}">Assinar</a>` : '<button class="btn btn-sec" disabled>Em breve</button>'}</div>`).join('')
  }

  const ini = (location.hash || '#agenda').slice(1)
  abrirAba(['agenda', 'contas', 'plano'].includes(ini) ? ini : 'agenda')
  setInterval(() => { if (!$('[data-painel=agenda]').hidden && !document.hidden && $('#m-post').hidden) carregarPosts() }, 20000)
})()

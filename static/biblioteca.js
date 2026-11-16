// Biblioteca do Posta AI: sobe vários arquivos de uma vez, agenda em lote (um por dia, legenda pela IA) e importa planilha.
;(() => {
  const $ = (q, r = document) => r.querySelector(q)
  const $$ = (q, r = document) => [...r.querySelectorAll(q)]
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
  const sec = $('[data-painel="biblioteca"]')
  if (!sec) return
  const sel = new Set()
  async function api(url, op = {}) {
    const r = await fetch(url, op)
    let j = {}
    try { j = await r.json() } catch {}
    if (r.status === 401) { location.href = '/?entrar=1'; throw new Error('entre de novo') }
    if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : 'Não deu certo. Tente de novo.')
    return j
  }
  const msg = (t, tipo = '') => { const m = $('#bib-msg'); m.textContent = t; m.className = 'msg ' + tipo }

  async function contas() {
    const j = await api('/api/contas')
    return (j.contas || []).filter((c) => c.estado === 'conectada')
  }

  async function carregar() {
    const { itens } = await api('/api/biblioteca')
    const g = $('#bib-grade')
    g.innerHTML = itens.length ? itens.map((i) => `<label class="bib-item ${sel.has(i.nome) ? 'on' : ''}" data-nome="${esc(i.nome)}">
        ${i.tipo === 'video' ? `<video src="${esc(i.url)}" muted preload="metadata"></video>` : `<img src="${esc(i.url)}" alt="" loading="lazy">`}
        <input type="checkbox" ${sel.has(i.nome) ? 'checked' : ''} aria-label="Selecionar ${esc(i.original)}">
        <span class="bib-nome" title="${esc(i.original)}">${esc(i.original)}</span>${i.usado ? '<span class="bib-tag">agendado</span>' : ''}
        <button type="button" class="bib-x" data-apagar="${esc(i.nome)}" aria-label="Apagar">×</button></label>`).join('')
      : '<p class="vazio">Nenhum arquivo ainda. Envie fotos e vídeos para montar a sua semana de posts.</p>'
    $$('.bib-item input', g).forEach((cb) => (cb.onchange = () => { const n = cb.closest('.bib-item').dataset.nome; cb.checked ? sel.add(n) : sel.delete(n); cb.closest('.bib-item').classList.toggle('on', cb.checked); atualizar() }))
    $$('[data-apagar]', g).forEach((b) => (b.onclick = async (e) => {
      e.preventDefault()
      if (!confirm('Apagar este arquivo da biblioteca?')) return
      try { await api('/api/biblioteca/' + b.dataset.apagar, { method: 'DELETE' }); sel.delete(b.dataset.apagar); carregar() } catch (err) { msg(err.message, 'erro') }
    }))
    atualizar()
  }
  function atualizar() {
    $('#bib-qtd').textContent = sel.size ? `${sel.size} selecionado${sel.size > 1 ? 's' : ''}` : 'Selecione os arquivos para agendar em lote'
    $('#bib-lote').disabled = !sel.size
  }

  $('#bib-arquivos').onchange = async (e) => {
    const fs = [...e.target.files]
    let ok = 0
    for (const [k, f] of fs.entries()) {
      msg(`Enviando ${k + 1} de ${fs.length}: ${f.name}`)
      try { await api('/api/midias', { method: 'POST', headers: { 'x-arquivo': f.name }, body: f }); ok++ } catch (err) { msg(`${f.name}: ${err.message}`, 'erro') }
    }
    e.target.value = ''
    msg(`${ok} arquivo${ok === 1 ? '' : 's'} na biblioteca.`, 'ok')
    carregar()
  }

  $('#bib-lote').onclick = async () => {
    const cs = await contas()
    if (!cs.length) return msg('Conecte a conta antes de agendar.', 'erro')
    const amanha = new Date(Date.now() + 86400000)
    amanha.setHours(19, 0, 0, 0)
    const local = new Date(amanha.getTime() - amanha.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
    const m = $('#m-lote')
    m.hidden = false
    $('#ml-corpo').innerHTML = `<h3>Agendar ${sel.size} post${sel.size > 1 ? 's' : ''} em série</h3>
      <p>Um post por vez, começando no dia e hora escolhidos. A IA escreve a legenda de cada um a partir do tema.</p>
      <label for="ml-conta">Conta</label><select id="ml-conta">${cs.map((c) => `<option value="${c.id}">${esc(c.rotulo || window.MARCA.rede)}</option>`).join('')}</select>
      <div class="dois"><div><label for="ml-inicio">Primeiro post</label><input id="ml-inicio" type="datetime-local" value="${local}"></div>
      <div><label for="ml-int">Intervalo</label><select id="ml-int"><option value="24">1 por dia</option><option value="12">2 por dia</option><option value="48">dia sim, dia não</option><option value="168">1 por semana</option></select></div></div>
      <label for="ml-tema">Tema da série (a IA escreve as legendas)</label><input id="ml-tema" placeholder="Ex.: cardápio de pizzas da semana, tom animado">
      <button class="btn btn-pri" style="width:100%;margin-top:16px" id="ml-ir">Agendar</button><div class="msg" id="ml-msg"></div>`
    $('#ml-ir').onclick = async () => {
      const b = $('#ml-ir'); b.disabled = true; b.textContent = 'Agendando e escrevendo as legendas…'
      try {
        const r = await api('/api/posts/lote', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
          conta: +$('#ml-conta').value, arquivos: [...sel], inicio: $('#ml-inicio').value, intervalo_horas: +$('#ml-int').value, tema: $('#ml-tema').value }) })
        m.hidden = true
        sel.clear()
        msg(`${r.criados} post${r.criados === 1 ? '' : 's'} agendado${r.criados === 1 ? '' : 's'}.${r.erros.length ? ' ' + r.erros.length + ' com problema: ' + r.erros.map((x) => x.erro).join('; ') : ''}`, r.erros.length ? 'erro' : 'ok')
        carregar()
      } catch (err) { $('#ml-msg').textContent = err.message; $('#ml-msg').className = 'msg erro'; b.disabled = false; b.textContent = 'Agendar' }
    }
  }

  $('#bib-planilha').onchange = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    const cs = await contas()
    if (!cs.length) { e.target.value = ''; return msg('Conecte a conta antes de importar.', 'erro') }
    msg('Lendo a planilha…')
    try {
      const r = await api(`/api/posts/planilha?conta=${cs[0].id}`, { method: 'POST', headers: { 'x-arquivo': f.name }, body: f })
      msg(`${r.criados} post${r.criados === 1 ? '' : 's'} agendado${r.criados === 1 ? '' : 's'} pela planilha.${r.erros.length ? ' Linhas com problema: ' + r.erros.map((x) => `${x.linha} (${x.erro})`).join('; ') : ''}`, r.erros.length ? 'erro' : 'ok')
      carregar()
    } catch (err) { msg(err.message, 'erro') }
    e.target.value = ''
  }

  const aba = $('[data-aba="biblioteca"]')
  if (aba) aba.addEventListener('click', carregar)
  if (location.hash === '#biblioteca') carregar()
})()

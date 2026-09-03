/* Cascata da secao 5.2 — S0 VAZIO, S1 ADM_OK, S2 APOLICE_OK, S3 FATURA_OK, S4 SEGURADOS_OK,
   S5 EMITINDO, S6 CONCLUIDO. RF-01: mudar um campo limpa e desabilita os posteriores.
   RF-02: Imprime so em S4. RF-14: todos marcados ao carregar. RF-17/RN-17: a chave viaja
   como dado (data-*), o texto e apenas apresentacao. */
(() => {
  const $ = (id) => document.getElementById(id);
  const el = {
    adm: $("administradora"), vig: $("vigencia"), apolice: $("apolice"), fatura: $("fatura"),
    produto: $("produto"), fazTudo: $("faz_tudo"), locacao: $("locacao"),
    busca: $("busca"), limpar: $("limpar"),
    listaPainel: $("lista-painel"), todos: $("todos"), contador: $("contador"),
    segurados: $("segurados"), erroLista: $("erro-lista"),
    emissaoPainel: $("emissao-painel"), pasta: $("pasta"), procurar: $("procurar"), imprimePremio: $("imprime_premio"),
    individuais: $("individuais"), soXml: $("so_xml"), imprime: $("imprime"), progresso: $("progresso"),
    relPainel: $("relatorio-painel"), relResumo: $("relatorio-resumo"), rel: $("relatorio"), relErro: $("relatorio-erro"),
  };
  let segurados = [];

  const api = async (url, opts) => {
    const r = await fetch(url, opts);
    const dados = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(dados.erro || `HTTP ${r.status}`);
    if (dados && dados.erro) throw new Error(dados.erro);
    return dados;
  };
  const opcoes = (select, itens, rotulo, valor, vazio) => {
    select.innerHTML = "";
    const o = document.createElement("option"); o.value = ""; o.textContent = vazio; select.appendChild(o);
    for (const it of itens) {
      const op = document.createElement("option");
      op.value = valor(it); op.textContent = rotulo(it);
      if (it.apolice !== undefined) { op.dataset.apolice = it.apolice; op.dataset.seq = it.seq; }
      select.appendChild(op);
    }
  };
  const mostrarErro = (onde, msg) => { onde.textContent = msg; onde.hidden = !msg; };
  const erroData = $("erro-data");

  // ------------------------------------------------------------ datas dd/mm/aaaa
  // A tela e brasileira (RN-14). ISO (aaaa-mm-dd) so existe na chamada da API (RD-06).
  function mascararData(input) {
    const d = input.value.replace(/\D/g, "").slice(0, 8);
    input.value = d.length > 4 ? `${d.slice(0, 2)}/${d.slice(2, 4)}/${d.slice(4)}`
                : d.length > 2 ? `${d.slice(0, 2)}/${d.slice(2)}` : d;
  }
  function dataParaIso(texto) {
    // "" -> null; invalida -> lanca Error com a mensagem para o operador
    const t = (texto || "").trim();
    if (!t) return null;
    const m = t.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (!m) throw new Error(`Data "${t}" incompleta: use dd/mm/aaaa`);
    const [dia, mes, ano] = [Number(m[1]), Number(m[2]), Number(m[3])];
    const dt = new Date(Date.UTC(ano, mes - 1, dia));
    if (dt.getUTCFullYear() !== ano || dt.getUTCMonth() !== mes - 1 || dt.getUTCDate() !== dia) {
      throw new Error(`Data "${t}" inválida`);
    }
    return `${m[3]}-${m[2]}-${m[1]}`;
  }
  function vigenciaIso() {
    try { const iso = dataParaIso(el.vig.value); mostrarErro(erroData, ""); return iso; }
    catch (e) { mostrarErro(erroData, e.message); throw e; }
  }

  // ---------------------------------------------------------------- estados
  function irPara(estado) {
    // RF-01: cada estado desabilita e limpa tudo o que vem depois
    if (estado <= 0) { opcoes(el.apolice, [], null, null, "—"); el.apolice.disabled = true; }
    if (estado <= 1) { opcoes(el.fatura, [], null, null, "—"); el.fatura.disabled = true; el.produto.value = ""; el.fazTudo.checked = false; el.fazTudo.disabled = true; el.locacao.checked = false; }
    if (estado <= 2) { el.busca.disabled = true; }
    if (estado <= 3) {
      segurados = []; el.segurados.innerHTML = ""; el.contador.textContent = "Seg.:0";
      el.listaPainel.hidden = true; el.emissaoPainel.hidden = true; el.imprime.disabled = true;
      mostrarErro(el.erroLista, "");
    }
    if (estado <= 4) { el.relPainel.hidden = true; }
    if (estado === 1) el.apolice.disabled = false;
    if (estado === 2) el.fatura.disabled = false;
    if (estado === 3) el.busca.disabled = false;
    if (estado === 4) { el.listaPainel.hidden = false; el.emissaoPainel.hidden = false; atualizarContador(); }
  }

  // ------------------------------------------------------------ carregamentos
  async function carregarAdministradoras() {
    const adms = await api("/api/incendio/administradoras");
    opcoes(el.adm, adms, (a) => a.nome, (a) => a.codigo, "— selecione —");  // RF-03
  }
  // Evita recarregar (e invalidar a cascata — RF-01) quando administradora e vigencia nao mudaram:
  // o evento `change` da data dispara de novo ao perder o foco mesmo apos o Enter.
  let carregado = { adm: null, vig: null };
  async function carregarApolices() {
    const chave = { adm: el.adm.value, vig: el.vig.value.trim() };
    if (chave.adm === carregado.adm && chave.vig === carregado.vig) return;
    carregado = chave;
    irPara(0);
    if (!el.adm.value) return;  // RF-15
    const iso = vigenciaIso();
    const q = new URLSearchParams({ administradora: el.adm.value });
    if (iso) q.set("inicio_vig", iso);
    const refs = await api(`/api/incendio/apolices?${q}`);
    opcoes(el.apolice, refs, (r) => r.rotulo, (r) => `${r.apolice}|${r.seq}`, "—");  // RN-08 / RN-17
    irPara(1);
  }
  async function carregarFaturas() {
    irPara(1);
    const op = el.apolice.selectedOptions[0];
    if (!el.apolice.value || !op) return;
    const iso = vigenciaIso();
    const q = new URLSearchParams({ administradora: el.adm.value, apolice: op.dataset.apolice, seq: op.dataset.seq });
    if (iso) q.set("inicio_vig", iso);
    const faturas = await api(`/api/incendio/faturas?${q}`);
    opcoes(el.fatura, faturas, (f) => String(f), (f) => String(f), "—");
    irPara(2);
  }
  function escolherFatura() { irPara(2); if (el.fatura.value) irPara(3); }

  function lote() {
    const op = el.apolice.selectedOptions[0];
    return { administradora: el.adm.value, apolice: op.dataset.apolice, seq: Number(op.dataset.seq), fatura: Number(el.fatura.value) };
  }

  async function buscarSegurados() {
    irPara(3);
    el.busca.disabled = true;
    try {
      const d = await api(`/api/incendio/segurados?${new URLSearchParams(lote())}`);
      segurados = d.segurados;
      el.produto.value = d.produto ? `${segurados[0].produto} - ${d.produto}` : "";  // RF-13
      el.fazTudo.checked = d.faz_tudo_lar; el.fazTudo.disabled = false;  // ADR-06: pre-marcado, editavel
      el.fazTudo.dataset.derivado = String(d.faz_tudo_lar);
      el.locacao.checked = d.locacao;  // RF-13: so derivado
      el.segurados.innerHTML = "";
      segurados.forEach((s, i) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td><input type="checkbox" class="sel" data-i="${i}" checked></td>
          <td>${esc(s.certificado)}</td><td>${s.portal ?? 0}</td><td>${esc(s.documento)}</td>
          <td>${esc(s.nome)}</td><td>${esc(s.endereco)}</td><td>${esc(s.unidade)}</td>
          <td>${s.avisos.map((a) => `<span class="tag">${a}</span>`).join("")}</td>`;
        el.segurados.appendChild(tr);
      });
      el.todos.checked = true;  // RF-14
      irPara(4);
      if (!segurados.length) mostrarErro(el.erroLista, "Nenhum segurado para esta fatura.");
    } catch (e) {
      mostrarErro(el.erroLista, e.message); el.listaPainel.hidden = false;
    } finally { el.busca.disabled = false; }
  }

  function selecionados() { return [...el.segurados.querySelectorAll(".sel:checked")].map((c) => segurados[c.dataset.i]); }
  function atualizarContador() {
    const n = selecionados().length;
    el.contador.textContent = `Seg.:${n}`;  // RF-04
    el.imprime.disabled = n === 0;  // RF-02
  }

  async function imprimir() {
    const sel = selecionados();
    if (!sel.length) return;
    el.imprime.disabled = true; el.progresso.hidden = false; el.relPainel.hidden = false;
    el.rel.innerHTML = ""; mostrarErro(el.relErro, ""); el.relResumo.textContent = "Emitindo…";
    try {
      const corpo = {
        ...lote(), pasta: el.pasta.value,
        selecionados: sel.length === segurados.length ? null : sel.map((s) => s.chave),
        imprime_premio: el.imprimePremio.checked, individuais: el.individuais.checked, so_xml: el.soXml.checked,
        faz_tudo_lar: el.fazTudo.checked,  // ADR-06: escolha do operador (pre-marcada pela RN-18)
      };
      const r = await api("/api/incendio/emitir", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
      el.relResumo.textContent = `${r.emitidos.length} emitidos, ${r.falhas.length} falhas — pasta ${r.pasta}` +
        (r.consolidado_pdf ? ` — consolidado: ${r.consolidado_pdf}` : "");
      for (const e of r.emitidos) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>OK</td><td>${esc(e.chave.certificado)}</td><td>${esc(e.pdf || e.json)}${e.colisao ? " (sufixo)" : ""}</td>
          <td>${e.avisos.map((a) => `<span class="tag">${a}</span>`).join("")}</td>`;
        el.rel.appendChild(tr);
      }
      for (const f of r.falhas) {
        const tr = document.createElement("tr"); tr.className = "falha";
        tr.innerHTML = `<td>FALHA</td><td>${esc(f.chave ? f.chave.certificado : "—")}</td><td></td><td>[${f.tipo}] ${esc(f.motivo)}</td>`;
        el.rel.appendChild(tr);
      }
    } catch (e) {
      el.relResumo.textContent = ""; mostrarErro(el.relErro, e.message);
    } finally { el.progresso.hidden = true; atualizarContador(); }
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ------------------------------------------------------------------ eventos
  const recarregar = () => carregarApolices().catch((e) => { if (!erroData.textContent) mostrarErro(el.erroLista, e.message); });
  el.adm.addEventListener("change", recarregar);
  el.vig.addEventListener("input", () => mascararData(el.vig));
  el.vig.addEventListener("change", recarregar);   // ao sair do campo ou Enter
  el.vig.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); recarregar(); } });
  el.apolice.addEventListener("change", () => carregarFaturas().catch((e) => mostrarErro(el.erroLista, e.message)));
  el.fatura.addEventListener("change", escolherFatura);
  el.busca.addEventListener("click", buscarSegurados);
  el.todos.addEventListener("change", () => { el.segurados.querySelectorAll(".sel").forEach((c) => (c.checked = el.todos.checked)); atualizarContador(); });
  el.segurados.addEventListener("change", atualizarContador);
  el.imprime.addEventListener("click", imprimir);
  el.procurar.addEventListener("click", async () => {
    el.procurar.disabled = true;
    try {
      const r = await api("/api/escolher-pasta", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ inicial: el.pasta.value }) });
      if (r.pasta) el.pasta.value = r.pasta;  // null = cancelou
    } catch (e) { mostrarErro(el.relErro, `Não foi possível abrir a janela de pastas: ${e.message}`); el.relPainel.hidden = false; }
    finally { el.procurar.disabled = false; }
  });
  el.limpar.addEventListener("click", () => { el.adm.value = ""; el.vig.value = ""; carregado = { adm: null, vig: null }; mostrarErro(erroData, ""); irPara(0); });

  carregarAdministradoras().catch((e) => { mostrarErro(el.erroLista, `Falha ao carregar administradoras: ${e.message}`); el.listaPainel.hidden = false; });
  irPara(0);
})();

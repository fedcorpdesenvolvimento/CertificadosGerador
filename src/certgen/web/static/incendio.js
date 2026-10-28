/* Cascata da secao 5.2 — S0 VAZIO, S1 ADM_OK, S2 APOLICE_OK, S3 FATURA_OK, S4 SEGURADOS_OK,
   S5 EMITINDO, S6 CONCLUIDO. RF-01: mudar um campo limpa e desabilita os posteriores.
   RF-02: Imprime so em S4. RF-14: todos marcados ao carregar. RF-17/RN-17: a chave viaja
   como dado (data-*), o texto e apenas apresentacao. */
(() => {
  // versao do servidor que entregou esta pagina; vai em cada pedido de emissao (409 se divergir)
  const VERSAO_TELA = (document.currentScript && document.currentScript.dataset.versao) || "";
  const $ = (id) => document.getElementById(id);
  const el = {
    adm: $("administradora"), vig: $("vigencia"), emissao: $("emissao"), apolice: $("apolice"), fatura: $("fatura"),
    produto: $("produto"), fazTudo: $("faz_tudo"), locacao: $("locacao"),
    busca: $("busca"), limpar: $("limpar"),
    listaPainel: $("lista-painel"), todos: $("todos"), contador: $("contador"),
    segurados: $("segurados"), erroLista: $("erro-lista"),
    emissaoPainel: $("emissao-painel"), pasta: $("pasta"), procurar: $("procurar"), imprimePremio: $("imprime_premio"),
    individuais: $("individuais"), jsonUnico: $("json_unico"), soXml: $("so_xml"), uploadAws: $("upload_aws"),
    imprime: $("imprime"), progresso: $("progresso"),
    relPainel: $("relatorio-painel"), relResumo: $("relatorio-resumo"), rel: $("relatorio"), relErro: $("relatorio-erro"),
    baixarTudo: $("baixar_tudo"),
    fNome: $("f_nome"), fCpf: $("f_cpf"), fCnpj: $("f_cnpj"), fEndereco: $("f_endereco"), fCondominio: $("f_condominio"), fLimpar: $("f_limpar"),
  };
  let segurados = [];
  let arquivosDoRelatorio = [];

  // ADR-08: sessao.js acrescenta o header CSRF e manda para /login quando a sessao caiu
  const api = (url, opts) => window.certgen.api(url, opts);
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
  function emissaoIso() {  // RN-05a — faturas.data_fat
    try { const iso = dataParaIso(el.emissao.value); mostrarErro(erroData, ""); return iso; }
    catch (e) { mostrarErro(erroData, e.message); throw e; }
  }
  function filtrosData(q) {
    const vig = vigenciaIso(); if (vig) q.set("inicio_vig", vig);
    const emi = emissaoIso(); if (emi) q.set("data_fat", emi);
    return q;
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
  let carregado = { adm: null, vig: null, emi: null };
  async function carregarApolices() {
    const chave = { adm: el.adm.value, vig: el.vig.value.trim(), emi: el.emissao.value.trim() };
    if (chave.adm === carregado.adm && chave.vig === carregado.vig && chave.emi === carregado.emi) return;
    carregado = chave;
    irPara(0);
    if (!el.adm.value) return;  // RF-15
    const q = filtrosData(new URLSearchParams({ administradora: el.adm.value }));
    const refs = await api(`/api/incendio/apolices?${q}`);
    opcoes(el.apolice, refs, (r) => r.rotulo, (r) => `${r.apolice}|${r.seq}`, "—");  // RN-08 / RN-17
    irPara(1);
  }
  async function carregarFaturas() {
    irPara(1);
    const op = el.apolice.selectedOptions[0];
    if (!el.apolice.value || !op) return;
    const q = filtrosData(new URLSearchParams({ administradora: el.adm.value, apolice: op.dataset.apolice, seq: op.dataset.seq }));
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
          <td>${esc(s.nome)}</td><td>${esc(s.endereco)}</td><td>${esc(s.unidade)}</td><td>${esc(s.vigencia)}</td>
          <td>${esc(s.condominio || "")}</td>
          <td>${s.avisos.map((a) => `<span class="tag">${a}</span>`).join("")}</td>`;
        el.segurados.appendChild(tr);
      });
      el.todos.checked = true;  // RF-14
      limparFiltros(false);
      irPara(4);
      if (!segurados.length) mostrarErro(el.erroLista, "Nenhum segurado para esta fatura.");
    } catch (e) {
      mostrarErro(el.erroLista, e.message); el.listaPainel.hidden = false;
    } finally { el.busca.disabled = false; }
  }

  // RF-05c: so as linhas VISIVEIS (que passaram pelos filtros) e marcadas entram na emissao
  function selecionados() {
    return [...el.segurados.querySelectorAll("tr:not([hidden]) .sel:checked")].map((c) => segurados[c.dataset.i]);
  }

  // ---------------------------------------------------------------- filtros (RF-05c)
  const semAcento = (t) => String(t ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
  const digitos = (t) => String(t ?? "").replace(/\D/g, "");
  function mascararDocumento(input, cnpj) {
    const d = digitos(input.value).slice(0, cnpj ? 14 : 11);
    input.value = cnpj
      ? d.replace(/^(\d{2})(\d)/, "$1.$2").replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3").replace(/\.(\d{3})(\d)/, ".$1/$2").replace(/(\d{4})(\d)/, "$1-$2")
      : d.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
  }
  function aplicarFiltros() {
    const nome = semAcento(el.fNome.value.trim());
    const cpf = digitos(el.fCpf.value), cnpj = digitos(el.fCnpj.value);
    const endereco = semAcento(el.fEndereco.value.trim());
    const condominio = semAcento(el.fCondominio.value.trim());
    const linhas = el.segurados.querySelectorAll("tr");
    linhas.forEach((tr) => {
      const s = segurados[tr.querySelector(".sel").dataset.i];
      const doc = digitos(s.documento);
      const passa = (!nome || semAcento(s.nome).includes(nome))
        && (!cpf || (doc.length === 11 && doc.includes(cpf)))
        && (!cnpj || (doc.length === 14 && doc.includes(cnpj)))
        && (!endereco || semAcento(`${s.endereco} ${s.unidade}`).includes(endereco))
        && (!condominio || semAcento(s.condominio).includes(condominio));
      tr.hidden = !passa;
    });
    atualizarContador();
  }
  function limparFiltros(reaplicar = true) {
    for (const i of [el.fNome, el.fCpf, el.fCnpj, el.fEndereco, el.fCondominio]) i.value = "";
    if (reaplicar) aplicarFiltros();
  }
  function atualizarContador() {
    const n = selecionados().length;
    const visiveis = el.segurados.querySelectorAll("tr:not([hidden])").length;
    el.contador.textContent = visiveis === segurados.length ? `Seg.:${n}` : `Seg.:${n} (${visiveis} de ${segurados.length} no filtro)`;  // RF-04
    el.imprime.disabled = n === 0;  // RF-02
  }

  async function imprimir() {
    const sel = selecionados();
    if (!sel.length) return;
    el.imprime.disabled = true; el.progresso.hidden = false; el.relPainel.hidden = false;
    el.rel.innerHTML = ""; mostrarErro(el.relErro, ""); el.relResumo.textContent = "Emitindo…";
    arquivosDoRelatorio = []; el.baixarTudo.hidden = true;
    try {
      const corpo = {
        ...lote(), pasta: el.pasta.value,
        selecionados: sel.length === segurados.length ? null : sel.map((s) => s.chave),
        imprime_premio: el.imprimePremio.checked, individuais: el.individuais.checked, so_xml: el.soXml.checked,
        json_unico: el.jsonUnico.checked,  // RD-26
        faz_tudo_lar: el.fazTudo.checked,  // ADR-06: escolha do operador (pre-marcada pela RN-18)
        upload_aws: el.uploadAws.checked && !el.uploadAws.disabled,  // RF-21
        versao_tela: VERSAO_TELA,
      };
      const r = await api("/api/incendio/emitir", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });
      el.relResumo.textContent = `${r.emitidos.length} emitidos, ${r.falhas.length} falhas — pasta ${r.pasta}` +
        (corpo.upload_aws ? ` — ${r.publicados ?? 0} publicados no S3` : "") +  // RF-21
        (r.consolidado_pdf ? ` — consolidado: ${r.consolidado_pdf}` : "") +
        (r.json_unico ? ` — JSON único: ${r.json_unico}` : "");
      for (const e of r.emitidos) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>OK</td><td>${esc(e.chave.certificado)}</td><td>${esc(e.vigencia)}</td><td>${esc(e.pdf || e.json || "(no JSON único)")}${e.colisao ? " (sufixo)" : ""}</td>
          <td>${linksBaixar([e.pdf, e.json])}</td>
          <td>${e.link ? `<a href="${esc(e.link_temporario || e.link)}" target="_blank" rel="noopener" title="${e.link_temporario ? "Link assinado, válido por 15 minutos (ADR-09)" : ""}">${esc(e.link)}</a>` : ""}</td>
          <td>${e.avisos.map((a) => `<span class="tag">${a}</span>`).join("")}</td>`;
        el.rel.appendChild(tr);
      }
      for (const extra of [r.consolidado_pdf, r.consolidado_json, r.json_unico]) if (extra) arquivosDoRelatorio.push(extra);
      if (r.consolidado_pdf || r.consolidado_json || r.json_unico) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>OK</td><td>lote</td><td></td><td>${esc([r.consolidado_pdf, r.consolidado_json, r.json_unico].filter(Boolean).join(" ; "))}</td>
          <td>${linksBaixar([r.consolidado_pdf, r.consolidado_json, r.json_unico])}</td><td></td><td></td>`;
        el.rel.appendChild(tr);
      }
      el.baixarTudo.hidden = arquivosDoRelatorio.length === 0;
      for (const f of r.falhas) {
        const tr = document.createElement("tr"); tr.className = "falha";
        tr.innerHTML = `<td>FALHA</td><td>${esc(f.chave ? f.chave.certificado : "—")}</td><td></td><td></td><td></td><td></td><td>[${f.tipo}] ${esc(f.motivo)}</td>`;
        el.rel.appendChild(tr);
      }
    } catch (e) {
      el.relResumo.textContent = ""; mostrarErro(el.relErro, e.message);
    } finally { el.progresso.hidden = true; atualizarContador(); }
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // RF-06a: links "Baixar" (o servidor so entrega arquivos da pasta de saida dele)
  function linksBaixar(caminhos) {
    return caminhos.filter(Boolean).map((c) => {
      arquivosDoRelatorio.push(c);
      const ext = c.toLowerCase().endsWith(".pdf") ? "PDF" : "JSON";
      return `<a href="/api/incendio/arquivo?${new URLSearchParams({ caminho: c })}" download title="Salvar na sua máquina">${ext}</a>`;
    }).join(" ");
  }
  async function baixarTudo() {
    if (!arquivosDoRelatorio.length) return;
    el.baixarTudo.disabled = true;
    try {
      const l = lote();
      const r = await fetch("/api/incendio/zip", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
        body: JSON.stringify({ arquivos: arquivosDoRelatorio, nome: `certificados_${l.administradora}_${l.fatura}` }),
      });
      if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.erro || `HTTP ${r.status}`); }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `certificados_${l.administradora}_${l.fatura}.zip`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) { mostrarErro(el.relErro, `Não foi possível baixar o .zip: ${e.message}`); }
    finally { el.baixarTudo.disabled = false; }
  }

  // ------------------------------------------------------------------ eventos
  const recarregar = () => carregarApolices().catch((e) => { if (!erroData.textContent) mostrarErro(el.erroLista, e.message); });
  el.adm.addEventListener("change", recarregar);
  el.vig.addEventListener("input", () => mascararData(el.vig));
  el.vig.addEventListener("change", recarregar);   // ao sair do campo ou Enter
  el.vig.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); recarregar(); } });
  el.emissao.addEventListener("input", () => mascararData(el.emissao));
  el.emissao.addEventListener("change", recarregar);
  el.emissao.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); recarregar(); } });
  el.apolice.addEventListener("change", () => carregarFaturas().catch((e) => mostrarErro(el.erroLista, e.message)));
  el.fatura.addEventListener("change", escolherFatura);
  el.busca.addEventListener("click", buscarSegurados);
  el.todos.addEventListener("change", () => { el.segurados.querySelectorAll("tr:not([hidden]) .sel").forEach((c) => (c.checked = el.todos.checked)); atualizarContador(); });
  el.segurados.addEventListener("change", atualizarContador);
  el.imprime.addEventListener("click", imprimir);
  el.baixarTudo.addEventListener("click", baixarTudo);
  // RF-05c: filtros da lista
  for (const i of [el.fNome, el.fEndereco, el.fCondominio]) i.addEventListener("input", aplicarFiltros);
  el.fCpf.addEventListener("input", () => { mascararDocumento(el.fCpf, false); aplicarFiltros(); });
  el.fCnpj.addEventListener("input", () => { mascararDocumento(el.fCnpj, true); aplicarFiltros(); });
  el.fLimpar.addEventListener("click", () => limparFiltros());
  // RF-21: Upload AWS so com PDF (nao 'So XML'); vale em qualquer modo, inclusive consolidado
  const ajustarUpload = () => { el.uploadAws.disabled = el.soXml.checked; };
  el.soXml.addEventListener("change", ajustarUpload);
  ajustarUpload();
  el.procurar?.addEventListener("click", async () => {
    el.procurar.disabled = true;
    try {
      const r = await api("/api/escolher-pasta", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ inicial: el.pasta.value }) });
      if (r.pasta) el.pasta.value = r.pasta;  // null = cancelou
    } catch (e) { mostrarErro(el.relErro, `Não foi possível abrir a janela de pastas: ${e.message}`); el.relPainel.hidden = false; }
    finally { el.procurar.disabled = false; }
  });
  el.limpar.addEventListener("click", () => { el.adm.value = ""; el.vig.value = ""; el.emissao.value = ""; carregado = { adm: null, vig: null, emi: null }; mostrarErro(erroData, ""); irPara(0); });

  carregarAdministradoras().catch((e) => { mostrarErro(el.erroLista, `Falha ao carregar administradoras: ${e.message}`); el.listaPainel.hidden = false; });
  irPara(0);
})();

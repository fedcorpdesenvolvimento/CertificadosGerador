/* ADR-09 — chaves da API do portal (so ADMIN). Mesmo desenho de usuarios.js:
   a chave e mostrada uma vez; o servidor guarda so o hash. */
(() => {
  const $ = (id) => document.getElementById(id);
  const api = window.certgen.api;
  const erro = (id, msg) => { const el = $(id); el.textContent = msg || ""; el.hidden = !msg; };
  const fmtData = (iso) => iso ? new Date(iso).toLocaleString("pt-BR") : "—";
  let chaves = [];
  let administradoras = [];

  const preencherSelect = (sel, marcadas) => {
    sel.innerHTML = "";
    for (const a of administradoras) {
      const o = document.createElement("option");
      o.value = a.codigo; o.textContent = `${a.codigo} — ${a.nome}`;
      o.selected = marcadas.includes(a.codigo);
      sel.append(o);
    }
  };
  const selecionadas = (sel) => Array.from(sel.selectedOptions).map((o) => o.value);
  const linhas = (texto) => texto.split(/\r?\n/).map((t) => t.trim()).filter(Boolean);
  const ligarTodas = (chk, sel) => { const f = () => { sel.disabled = chk.checked; }; chk.addEventListener("change", f); f(); };

  const td = (texto) => { const c = document.createElement("td"); c.textContent = texto; return c; };
  const botao = (texto, classe, acao) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "botao mini " + (classe || "");
    b.textContent = texto; b.addEventListener("click", acao); return b;
  };

  const desenhar = () => {
    const corpo = $("tabela-chaves").querySelector("tbody");
    corpo.innerHTML = "";
    for (const c of chaves) {
      const tr = document.createElement("tr");
      if (!c.ativa) tr.className = "inativo";
      tr.append(td(c.nome), td(c.prefixo + "…"),
                td(c.todas ? "todas" : c.administradoras.join(", ")),
                td(c.ips.length ? c.ips.join(", ") : "qualquer"),
                td(c.ativa ? "Ativa" : `Revogada em ${fmtData(c.revogada_em)}`),
                td(c.ultimo_uso ? `${fmtData(c.ultimo_uso)} (${c.ultimo_ip || "?"})` : "nunca"));
      const acoes = document.createElement("td");
      if (c.ativa) {
        acoes.append(botao("Editar", "", () => editar(c)));
        acoes.append(botao("Revogar", "secundario", () => revogar(c)));
      }
      tr.append(acoes);
      corpo.append(tr);
    }
  };

  const carregar = async () => {
    try { chaves = await api("/api/chaves"); erro("erro-lista", ""); desenhar(); }
    catch (e) { erro("erro-lista", e.message); }
  };

  const carregarAdministradoras = async () => {
    try {
      administradoras = await api("/api/incendio/administradoras");
      preencherSelect($("nova_adms"), []);
    } catch (e) { erro("erro-nova", "Administradoras indisponíveis: " + e.message); }
  };

  ligarTodas($("nova_todas"), $("nova_adms"));
  $("f-nova").addEventListener("submit", async (e) => {
    e.preventDefault();
    const corpo = {
      nome: $("nova_nome").value.trim(), todas: $("nova_todas").checked,
      administradoras: selecionadas($("nova_adms")), ips: linhas($("nova_ips").value),
    };
    try {
      const r = await api("/api/chaves", { method: "POST", body: corpo });
      erro("erro-nova", "");
      $("cg-nome").textContent = r.nome; $("cg-chave").textContent = r.chave; $("chave-gerada").hidden = false;
      $("nova_nome").value = ""; $("nova_ips").value = ""; $("nova_todas").checked = false;
      preencherSelect($("nova_adms"), []); $("nova_adms").disabled = false;
      await carregar();
    } catch (err) { erro("erro-nova", err.message); }
  });

  let editando = null;
  ligarTodas($("ed_todas"), $("ed_adms"));
  const editar = (c) => {
    editando = c;
    $("ed_nome").value = c.nome; $("ed_todas").checked = c.todas;
    preencherSelect($("ed_adms"), c.administradoras); $("ed_adms").disabled = c.todas;
    $("ed_ips").value = c.ips.join("\n");
    erro("erro-editar", ""); $("dlg-editar").showModal();
  };
  $("ed_cancelar").addEventListener("click", () => $("dlg-editar").close());
  $("f-editar").addEventListener("submit", async (e) => {
    e.preventDefault();
    const corpo = {
      nome: $("ed_nome").value.trim(), todas: $("ed_todas").checked,
      administradoras: selecionadas($("ed_adms")), ips: linhas($("ed_ips").value),
    };
    try {
      await api(`/api/chaves/${editando.id}`, { method: "PUT", body: corpo });
      $("dlg-editar").close(); await carregar();
    } catch (err) { erro("erro-editar", err.message); }
  });

  const revogar = async (c) => {
    if (!confirm(`Revogar a chave de ${c.nome}? O portal deixa de acessar na hora e não há como desfazer.`)) return;
    try { await api(`/api/chaves/${c.id}/revogar`, { method: "POST" }); await carregar(); }
    catch (err) { erro("erro-lista", err.message); }
  };

  carregarAdministradoras().then(carregar);
})();

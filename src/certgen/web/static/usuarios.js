/* ADR-08 — cadastro de usuarios (so ADMIN). Modelo: views/admin.js do Sinistros,
   sem e-mail: a senha temporaria e mostrada uma vez ao administrador. */
(() => {
  const $ = (id) => document.getElementById(id);
  const api = window.certgen.api;
  const EU = Number(document.currentScript.dataset.eu);
  const erro = (id, msg) => { const el = $(id); el.textContent = msg || ""; el.hidden = !msg; };
  const fmtData = (iso) => iso ? new Date(iso).toLocaleString("pt-BR") : "—";
  let usuarios = [];

  const mostrarSenha = (email, senha) => {
    $("sg-email").textContent = email; $("sg-senha").textContent = senha;
    $("senha-gerada").hidden = false;
  };

  const td = (texto) => { const c = document.createElement("td"); c.textContent = texto; return c; };
  const botao = (texto, classe, acao) => {
    const b = document.createElement("button"); b.type = "button"; b.className = "botao mini " + (classe || "");
    b.textContent = texto; b.addEventListener("click", acao); return b;
  };

  const desenhar = () => {
    const corpo = $("tabela-usuarios").querySelector("tbody");
    corpo.innerHTML = "";
    for (const u of usuarios) {
      const tr = document.createElement("tr");
      if (!u.ativo) tr.className = "inativo";
      tr.append(td(u.nome), td(u.email), td(u.perfil_nome),
                td(u.ativo ? (u.trocar_senha ? "Ativo (senha temporária)" : "Ativo") : "Desativado"),
                td(fmtData(u.ultimo_login)));
      const acoes = document.createElement("td");
      acoes.append(botao("Editar", "", () => editar(u)));
      if (u.id !== EU) {
        acoes.append(botao(u.ativo ? "Desativar" : "Reativar", "secundario", () => ativar(u)));
        acoes.append(botao("Nova senha", "secundario", () => resetar(u)));
      }
      tr.append(acoes);
      corpo.append(tr);
    }
  };

  const carregar = async () => {
    try { usuarios = await api("/api/usuarios"); erro("erro-lista", ""); desenhar(); }
    catch (e) { erro("erro-lista", e.message); }
  };

  $("f-novo").addEventListener("submit", async (e) => {
    e.preventDefault();
    const corpo = { nome: $("novo_nome").value.trim(), email: $("novo_email").value.trim(), perfil: $("novo_perfil").value };
    try {
      const r = await api("/api/usuarios", { method: "POST", body: corpo });
      erro("erro-novo", ""); mostrarSenha(r.email, r.senha_temporaria);
      $("novo_nome").value = ""; $("novo_email").value = "";
      await carregar();
    } catch (err) { erro("erro-novo", err.message); }
  });

  let editando = null;
  const editar = (u) => {
    editando = u;
    $("ed_nome").value = u.nome; $("ed_email").value = u.email; $("ed_perfil").value = u.perfil;
    erro("erro-editar", ""); $("dlg-editar").showModal();
  };
  $("ed_cancelar").addEventListener("click", () => $("dlg-editar").close());
  $("f-editar").addEventListener("submit", async (e) => {
    e.preventDefault();
    const corpo = { nome: $("ed_nome").value.trim(), email: $("ed_email").value.trim(), perfil: $("ed_perfil").value };
    try {
      await api(`/api/usuarios/${editando.id}`, { method: "PUT", body: corpo });
      $("dlg-editar").close(); await carregar();
    } catch (err) { erro("erro-editar", err.message); }
  });

  const ativar = async (u) => {
    const acao = u.ativo ? "Desativar" : "Reativar";
    if (!confirm(`${acao} ${u.nome}?`)) return;
    try { await api(`/api/usuarios/${u.id}/ativo`, { method: "POST", body: { ativo: !u.ativo } }); await carregar(); }
    catch (err) { erro("erro-lista", err.message); }
  };

  const resetar = async (u) => {
    if (!confirm(`Gerar nova senha temporária para ${u.nome}? As sessões atuais serão encerradas.`)) return;
    try {
      const r = await api(`/api/usuarios/${u.id}/resetar-senha`, { method: "POST" });
      mostrarSenha(u.email, r.senha_temporaria); await carregar();
    } catch (err) { erro("erro-lista", err.message); }
  };

  carregar();
})();

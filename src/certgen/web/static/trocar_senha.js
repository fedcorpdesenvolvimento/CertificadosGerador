/* ADR-08 — troca de senha (obrigatoria quando a senha e temporaria). */
(() => {
  const $ = (id) => document.getElementById(id);
  const erro = (msg) => { const el = $("erro-senha"); el.textContent = msg || ""; el.hidden = !msg; };

  $("f-senha").addEventListener("submit", async (e) => {
    e.preventDefault();
    const atual = $("senha_atual").value, nova = $("nova").value, conf = $("confirma").value;
    if (!atual || !nova) return erro("Preencha a senha atual e a nova.");
    if (nova.length < 8) return erro("A senha deve ter no mínimo 8 caracteres.");
    if (!/[A-Za-zÀ-ÿ]/.test(nova) || !/\d/.test(nova)) return erro("A senha deve conter letras e números.");
    if (nova !== conf) return erro("As senhas não conferem.");
    erro("");
    try {
      await window.certgen.api("/api/auth/trocar-senha", { method: "POST", body: { senha_atual: atual, nova_senha: nova } });
      window.location.href = "/";
    } catch (err) { erro(err.message); }
  });
})();

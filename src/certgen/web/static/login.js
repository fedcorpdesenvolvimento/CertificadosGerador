/* ADR-08 — pagina de login (modelo public/js/login.js do Sinistros). */
(() => {
  const $ = (id) => document.getElementById(id);
  const erro = (msg) => { const el = $("erro-login"); el.textContent = msg || ""; el.hidden = !msg; };

  document.querySelectorAll("button.olho[data-olho]").forEach((b) => {
    b.addEventListener("click", () => {
      const alvo = $(b.dataset.olho);
      if (alvo) alvo.type = alvo.type === "password" ? "text" : "password";
    });
  });

  // destino apos o login: so caminhos internos (nunca outro site)
  const destino = () => {
    const next = new URLSearchParams(window.location.search).get("next") || "/";
    return next.startsWith("/") && !next.startsWith("//") ? next : "/";
  };

  $("f-login").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("email").value.trim();
    const senha = $("senha").value;
    if (!email || !senha) return erro("Informe e-mail e senha.");
    const btn = e.submitter; if (btn) btn.disabled = true;
    erro("");
    try {
      const r = await fetch("/api/auth/login", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
        body: JSON.stringify({ email, senha }),
      });
      const dados = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(dados.erro || (dados.detail && String(dados.detail)) || `HTTP ${r.status}`);
      window.location.href = dados.trocar_senha ? "/trocar-senha" : destino();
    } catch (err) {
      erro(err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  });
})();

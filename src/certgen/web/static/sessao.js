/* ADR-08 — sessao da tela: chamada padrao a API (header CSRF + 401 -> /login),
   botao Sair (logout) e olho de mostrar/ocultar senha. Carregado por base.html. */
(() => {
  window.certgen = window.certgen || {};

  // Toda chamada que altera dados leva X-Requested-With: fetch (CSRF, como no Sinistros).
  window.certgen.api = async (url, opts = {}) => {
    const headers = Object.assign({ "X-Requested-With": "fetch" }, opts.headers || {});
    if (opts.body && typeof opts.body !== "string") {
      opts = Object.assign({}, opts, { body: JSON.stringify(opts.body) });
      headers["Content-Type"] = "application/json";
    }
    const r = await fetch(url, Object.assign({ credentials: "same-origin" }, opts, { headers }));
    if (r.status === 401 && !url.startsWith("/api/auth/login")) {
      window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
      throw new Error("Sessão expirada.");
    }
    const dados = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(dados.erro || (dados.detail && String(dados.detail)) || `HTTP ${r.status}`);
    if (dados && dados.erro) throw new Error(dados.erro);
    return dados;
  };

  window.certgen.olhos = (raiz) => {
    (raiz || document).querySelectorAll("button.olho[data-olho]").forEach((b) => {
      b.addEventListener("click", () => {
        const alvo = document.getElementById(b.dataset.olho);
        if (alvo) alvo.type = alvo.type === "password" ? "text" : "password";
      });
    });
  };
  window.certgen.olhos(document);

  document.getElementById("logout")?.addEventListener("click", async () => {
    try { await window.certgen.api("/api/auth/logout", { method: "POST" }); } catch (e) { /* sessao ja caiu */ }
    window.location.href = "/login";
  });
})();

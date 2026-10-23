/* Botao "Encerrar sistema" do menu: so aparece para o navegador da maquina do servidor
   (RNF-10a). Era um script inline em menu.html; saiu de la por causa da CSP (ADR-08). */
document.getElementById("sair")?.addEventListener("click", async () => {
  if (!confirm("Encerrar o Gerador de Certificados?")) return;
  try { await window.certgen.api("/api/encerrar", { method: "POST" }); } catch (e) { /* servidor ja caiu */ }
  document.getElementById("encerrado").hidden = false;
  document.querySelector(".cartoes").hidden = true;
  window.close();  // funciona quando a janela foi aberta pelo proprio sistema (certgen web)
});

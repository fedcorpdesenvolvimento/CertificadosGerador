# Textos legais extraídos dos PDFs de referência (GAP-09)

Extraídos em 03/09/2026 com `pypdf` (`page.extract_text()`), sem edição. A ordem
das linhas segue a ordem dos objetos no PDF, não a ordem visual; os rótulos da
tabela superior aparecem agrupados e separados dos valores.

| Arquivo | Template (`7.3`) | Blocos presentes |
|---|---|---|
| `0_33016330725_0004_13008_380819.txt` | `incendio_ruptura_faz_tudo` (`frxReportCntRupturaFT`) | Incêndio/Raio/Explosão/Perda de Aluguel (redação A), Assistência 24h, **Faz Tudo Lar**, rodapé |
| `0_05554363733__15008_381066.txt` | `incendio` (`frxReportIncendio`) | Incêndio/Raio/Explosão/Perda de Aluguel (redações A **e** B, sobrepostas — DEF-18), Assistência 24h, rodapé, link das condições gerais |
| `0_14529138704__15008_381066.txt` | idem | idem (mesma fatura, outro segurado) |

Faltam PDFs dos templates `incendio_faz_tudo_24h`, `locacao_simples` e
`locacao_faz_tudo`.

**Estes textos têm efeito jurídico.** Devem ser conferidos por quem responde pela
conformidade antes de irem ao template (`certificado.html.j2`). Erros de digitação
do legado foram preservados aqui de propósito: `dentruindo-o`, `extremamemnte`,
`recepientes`, `Assitência`, `DESINTETIZAÇÃO`. A decisão de corrigir ou preservar
está em aberto (GAP-09).

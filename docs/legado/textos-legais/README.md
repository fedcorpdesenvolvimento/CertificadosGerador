# Textos legais extraídos dos PDFs de referência (GAP-09)

Extraídos em 03/09/2026 com `pypdf` (`page.extract_text()`), sem edição. A ordem
das linhas segue a ordem dos objetos no PDF, não a ordem visual; os rótulos da
tabela superior aparecem agrupados e separados dos valores.

| Arquivo | Template (`7.3`) | Blocos presentes |
|---|---|---|
| `0_33016330725_0004_13008_380819.txt` | `incendio_ruptura_faz_tudo` (`frxReportCntRupturaFT`) | Incêndio/Raio/Explosão/Perda de Aluguel (redação A), Assistência 24h, **Faz Tudo Lar**, rodapé |
| `0_05554363733__15008_381066.txt` | `incendio` (`frxReportIncendio`) | Incêndio/Raio/Explosão/Perda de Aluguel (redações A **e** B, sobrepostas — DEF-18), Assistência 24h, rodapé, link das condições gerais |
| `0_14529138704__15008_381066.txt` | idem | idem (mesma fatura, outro segurado) |

**ADR-06 (03/09/2026):** o layout do sistema novo é **exclusivamente** o do
`0_33016330725_0004_13008_380819.pdf`, com o bloco Faz Tudo Lar opcional. Os
outros templates do legado não serão reproduzidos; os textos deste PDF são os
do template. Os arquivos `15008` ficam apenas como referência de dados.

**Estes textos têm efeito jurídico.** Devem ser conferidos por quem responde pela
conformidade antes de irem ao template (`certificado.html.j2`). Erros de digitação
do legado foram preservados aqui de propósito: `dentruindo-o`, `extremamemnte`,
`recepientes`, `Assitência`, `DESINTETIZAÇÃO`. A decisão de corrigir ou preservar
está em aberto (GAP-09).


**04/09/2026:** os blocos *Assistência Residencial Emergencial 24h* e *Assistência Faz Tudo Lar* do template **não usam mais** os textos destes PDFs; o negócio forneceu textos novos, que estão em `src/certgen/render/templates/blocos/`. Os textos de Incêndio/Raio/Explosão/Perda de Aluguel, Ruptura e RC continuam vindo do PDF de referência.

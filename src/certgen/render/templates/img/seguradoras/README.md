# Logotipos das seguradoras (RN-28)

Um arquivo por logotipo, referenciado pelo campo `logo` de
`src/certgen/config/seguradoras.toml`. Sem o arquivo, a caixa do certificado sai
vazia e o JSON recebe o aviso `LOGO_SEGURADORA_AUSENTE`.

| Arquivo | Seguradoras que o usam | Situação |
|---|---|---|
| `bradesco.png` | Bradesco (`0000000109`), Alfa (`0000000104`) | entregue pelo negócio em 04/09/2026 (1440 × 546) |
| `hdi.png` | HDI (`0000000108`), Sompo (`0000000003`) | entregue pelo negócio em 04/09/2026 (300 × 218) |
| `porto.png` | Porto Seguro (`0000000006`) | entregue pelo negócio em 04/09/2026 (160 × 205, vertical) |

Para trocar um logotipo, basta substituir o arquivo mantendo o nome, ou apontar
um nome novo em `seguradoras.toml`.

Formato recomendado: PNG com fundo transparente, proporção aproximada 2,3:1
(por exemplo 700 × 300 px). A caixa no certificado tem 28 × 12 mm; a imagem é
ajustada proporcionalmente dentro dela.

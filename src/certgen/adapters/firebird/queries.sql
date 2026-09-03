-- RD-17 — fonte unica das consultas. Blocos nomeados, carregados por nome.
-- Filtros opcionais sao compostos em Python no marcador /*FILTROS*/ (RN-07),
-- sempre com bind parameters posicionais `?` (RN-06; o driver fdb usa qmark).
-- Toda consulta a segurados_inc filtra status_seg <> 'C' e cpf_cnpj <> '' (RD-02, RD-19).

-- name: administradoras
-- QRY-01 / RD-03 / RD-07
SELECT pes.pessoa, pes.nome, pes.abrev, pes.possui_portal
FROM pessoas pes
WHERE pes.status <> 'C'
ORDER BY pes.nome

-- name: apolices
-- QRY-03. Filtros: ss.administradora = ? (obrigatorio, RF-15); ss.inicio_vig = ? (opcional)
SELECT ss.apolice, ss.seq, MIN(ss.inicio_vig) AS inicio_vig
FROM segurados_inc ss
WHERE ss.status_seg <> 'C'
  AND ss.cpf_cnpj <> ''
  /*FILTROS*/
GROUP BY ss.apolice, ss.seq
ORDER BY ss.apolice, ss.seq

-- name: faturas
-- QRY-04. Filtros: administradora, apolice, seq (obrigatorios); inicio_vig (opcional)
SELECT ss.fatura
FROM segurados_inc ss
WHERE ss.status_seg <> 'C'
  AND ss.cpf_cnpj <> ''
  /*FILTROS*/
GROUP BY ss.fatura
ORDER BY 1

-- name: certificado_base
-- A consulta canonica (secao 6.0). QRY-05, QRY-09 e QRY-10 sao ela + filtros.
-- RD-04/RD-08: projeta cod_seguradora, abrev e cod_cat.
-- RN-02: COALESCE em cob_incendio (DEF-05).
-- RN-20: COALESCE(pes.abrev,'') no cod_0800.
-- GAP-17: JOIN com segurados_inc_cob_aux pela PK (endosso, certificado).
-- GAP-16: linha_branca nao e projetada.
-- RN-26: apolices.sucursal (rotulo SUC.) pela FK (apolice, seq, administradora, cod_seguradora).
SELECT pes.nome                                                 AS nome_adm,
       pes.abrev                                                 AS abrev_adm,
       ss.administradora, ss.apolice, ss.seq, ss.fatura,
       ss.endosso, ss.cod_seguradora,
       ss.nome                                                   AS beneficiario,
       ss.codigo_pedido_port,
       ss.cpf_cnpj                                               AS documento_seg,
       ss.inicio_vig, ss.final_vig,
       ss.endereco, ss.unidade, ss.cep, ss.uf, ss.cidade, ss.bairro,
       ss.nome_cond,
       aps.apolice_seguradora, aps.proc_susep,
       apo.sucursal,
       ss.certificado,
       ss.inc_conteudo, ss.inc_predio, ss.aluguel,
       (COALESCE(ss.inc_conteudo, 0) + COALESCE(ss.inc_predio, 0)) AS cob_incendio,
       ss.premio,
       en.codigo_assist_mondial, en.cod_cat,
       ss.certificado || ' ' || COALESCE(pes.abrev, '')          AS cod_0800,
       sicb.quebra_vidro, sicb.rc, sicb.danos_eletricos,
       sicb.resp_civil, sicb.rup_encanamento,
       sicb.rup_enc_ter, sicb.acidente_pessoal
FROM segurados_inc ss
LEFT JOIN pessoas               pes  ON pes.pessoa = ss.administradora
LEFT JOIN apolice_seguradora    aps  ON aps.apolice = ss.apolice
                                    AND aps.cod_seguradora = ss.cod_seguradora
LEFT JOIN endossos              en   ON en.endosso = ss.endosso
LEFT JOIN apolices              apo  ON apo.apolice = ss.apolice            -- RN-26: FK_SEGURADOS_APOLICES
                                    AND apo.seq = ss.seq
                                    AND apo.administradora = ss.administradora
                                    AND apo.cod_seguradora = ss.cod_seguradora
LEFT JOIN segurados_inc_cob_aux sicb ON sicb.endosso = ss.endosso
                                    AND sicb.certificado = ss.certificado
WHERE ss.status_seg <> 'C'
  AND ss.cpf_cnpj <> ''
  /*FILTROS*/
ORDER BY ss.administradora, ss.apolice, ss.seq, ss.fatura,
         ss.endereco, ss.unidade, ss.cpf_cnpj

-- name: endosso_por_fatura
-- QRY-11 / RN-16: o numero da fatura e o sequencial do endosso.
SELECT en.endosso, en.cod_cat, en.codigo_assist_mondial
FROM endossos en
WHERE en.sequencial = ?

-- name: faturamento
-- QRY-07 — driver do fluxo em massa (Fase 6). Filtros opcionais: dt_ini_vig, data_fat,
-- apolice (ou lista RN-22), administradora, fatura.
SELECT fat.administradora, fat.apolice, fat.seq, fat.fatura, fat.seguradora,
       endo.codigo_assist_mondial, endo.cob_especiais, pes.possui_portal
FROM faturas fat
LEFT JOIN endossos endo ON endo.sequencial = fat.fatura
LEFT JOIN pessoas  pes  ON pes.pessoa      = fat.administradora
WHERE fat.status = 'A'
  /*FILTROS*/
ORDER BY fat.administradora, fat.apolice, fat.seq, fat.fatura

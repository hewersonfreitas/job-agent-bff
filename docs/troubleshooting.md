# Diagnóstico

| Sintoma | Verificação segura |
|---|---|
| BFF não inicia | Conferir presença/modo/owner/caminho absoluto de arquivos e origem HTTPS; não imprimir segredos |
| Cookie não enviado | HTTPS confiável, Host igual à origem, Path=/, mesma origem; não remover Secure |
| 401 login | Senha explicitamente provisionada; hash Argon2id gerado pelo comando do projeto |
| 429 | Aguardar janela; tentativas são persistentes e proxy compartilha peer; não desabilitar proteção |
| 403 navegador | Origin exata, Fetch Metadata, token CSRF recente, headers privados ausentes |
| 401 ATS | Certificado real e bearer independente ATS, ambos corretos |
| 403 ATS | Policy habilitada, fingerprint/validade/revogação, operador, scope, autoridade DNS |
| 404 recurso | Recurso ausente ou fora do grant; não concluir que existe por outra resposta |
| 409 | Atualizar revisão/estado, revisar decisões; não repetir requisição automaticamente |
| 422 upload | Corpo bruto, extensão/MIME/assinatura, basename seguro; sem multipart |
| 502 | Resposta divergente do contrato v0.8 ou provider; verificar versões sem logar payload |
| 503 | Conferir DNS, CA/SAN/EKU/validade, arquivos privados, SQLite/audit/espaço, timeouts |
| Health verde, ATS falha | Health local não comprova política/recurso/bearer/cliente mTLS; usar smoke sintético |
| Permission denied em secret | Compose bind conserva owner/mode; escolher UID não-root compatível; nunca chmod 644 |
| Rotação não refletida | Bind mount pode fixar inode; recriar serviço após troca controlada |
| Sessão some ao restart | Verificar BFF_DATABASE e volume persistente, mesmo hash/UID e janela de expiração |

Executar `python -m scripts.check_contract --upstream /caminho/job-agent` para conferir
snapshot, e `python -m scripts.check_sensitive` antes de commit. Com Python 3.12 e
`pip install -e '.[dev]'`, executar Ruff e Pytest. Para testes TLS reais, instalar
requirements do backend, configurar ATS_BACKEND_DIRECTORY e resolução ats-service
para 127.0.0.1 **apenas no ambiente sintético**. Os certificados são descartáveis.

O caminho preferido sem alterar DNS do host usa a imagem de validação e
`--add-host ats-service:127.0.0.1`; ver README. Não falsificar Host no cliente real.
O smoke Compose usa DNS Docker real, projeto único e novos diretórios temporários;
só para os próprios containers/redes. Não remove volumes existentes.

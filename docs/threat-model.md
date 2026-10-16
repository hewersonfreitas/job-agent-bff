# Modelo de ameaças

Ativos: senha/hash do operador, sessões, CSRF, bearer/certificado ATS, currículo,
documentos exportados e auditoria. Fronteiras: browser/Nginx, Nginx/BFF, BFF/ATS,
volumes privados e arquivos de configuração do operador.

| Ameaça | Controle | Risco residual |
|---|---|---|
| Brute force | Argon2id 64 MiB/3/4, rate limit SQLite por peer e global | DoS ao operador por bloqueio temporário; Nginx deve limitar conexões |
| Roubo/fixação de sessão | 256 bits, hash no servidor, rotação/login/logout/expiração/limite | XSS pode executar ações enquanto a sessão está ativa |
| CSRF/login-CSRF | Origin exata, Fetch Metadata, JSON, token sincronizado | XSS mesma origem exige prevenção no frontend |
| SSRF/proxy genérico | 13 rotas, IDs/query/media estritos, destino constante, sem redirects | BFF comprometido pode usar grants ATS |
| Identidade de serviço falsa | mTLS real + fingerprint/policy/bearer/operator, nenhum header copiado | Proteção do host e PKI é responsabilidade operacional |
| Leitura indevida de recurso | Sessão/scope BFF + grants de recurso ATS | Workspace de operador único; não há ownership multiusuário |
| Upload abusivo | Limite incremental, assinatura e ZIP metadata/schema | Parsing completo/limites de worker dependem do backend |
| Traversal/download | IDs estritos, sem path/URL arbitrário, filename reconstruído | Documentos continuam pessoais; proteger endpoints/volume |
| Vazamento em erros/logs/cache | Sanitização, no-store, logs sem payload/access log privado | Proxies externos devem também evitar logs e cache privados |
| Replay/conflito de escrita | expected_revision + 409 upstream, sem retry | Escrita pode concluir antes de timeout/falha de auditoria |
| Vazamento de banco | Modo 0600, volume privado, IDs hash | SQLite não é criptografado; backups requerem controle/criptografia |
| Negação de serviço | Limites de tamanho/conexão/timeouts/login | Aplicar também limites Nginx/conexões; não é WAF nem proteção distribuída |

TLS do navegador termina no proxy HTTPS confiável. BFF HTTP interno não tem porta
publicada; somente Nginx deve compartilhar bff-edge. ATS só compartilha ats-private.
Não ligar containers não confiáveis nessas redes. Não expor /healthz por necessidade
além da verificação local. Backups dos bancos possuem dados privados.

Headers de cliente duplicados sensíveis são negados. Nenhum X-Forwarded-* é usado
para autenticação, IP de rate limit, seleção de upstream ou derivação TLS. O proxy
deve preservar Host e não aceitar acesso externo à rede interna. A origem configurada
é HTTPS obrigatória. Nenhuma senha real ou certificado de produção é gerado por testes.

# Arquitetura e decisões

BFF 0.1 é um serviço FastAPI separado, para um único operador. O frontend continua
estático. Browser HTTPS → Nginx /workspace → BFF → https://ats-service:8766 por mTLS.
O SQLite do BFF guarda hashes de sessões e CSRF, hash da credencial que originou a
sessão, limites de login e auditoria. O SQLite/documentos ATS pertencem ao backend.
Não existe isolamento multiusuário: todos os recursos pertencem ao mesmo workspace.

O contrato foi lido no backend publicado na `main` (PR #7), commit
`b28f3280a90dcebd625956f6bda41ff1b4d92cb3`. O OpenAPI privado v0.8 é preservado em
`contracts/ats-v0.8.json`, com SHA-256 e verificação contra checkout upstream.
As respostas ATS do OpenAPI original têm schemas vazios; os modelos estritos do BFF
foram derivados do router, repositório e geradores reais desse commit. Objetos de
proveniência de evidências e eventos conservam dicionários livres previstos pelo
backend; não são usados como caminhos nem headers. Regras semânticas de evidência,
estado e referências permanecem no ATS. Não há cópia de matching nem geração.

Cada rota registrada tem método/caminho finito e scope do OpenAPI. IDs são inteiros
positivos ASCII de até 18 dígitos. Query desconhecida, duplicada ou inválida é negada.
O BFF verifica sessão e scope; a política ATS verifica fingerprint, operador e
recursos, inclusive resume/job de versões. Grants de recurso são mantidos no ATS,
sem cache no BFF. Configuração local pode restringir scopes ainda mais.

Cookies são sempre Secure, HttpOnly, SameSite=Lax, Path=/ e sem Domain. Login exige
Origin HTTPS exata e Fetch Metadata compatível, inclusive antes da autenticação.
Sessões têm 256 bits aleatórios, rotação por login, expiração absoluta/inatividade,
limite de concorrência e revogação persistente. Nenhum modo HTTP inseguro é fornecido.
Token CSRF sincronizado é rotacionado por GET /auth/csrf, somente para sessão válida.
Ele fica em memória da tela; buscar novamente invalida o anterior, inclusive em
outra aba. Mutações autenticadas exigem X-CSRF-Token e Origin. Login é protegido
contra login-CSRF por Origin estrita/JSON/Fetch Metadata, sem sessão prévia.

HTTPX usa CA explícita, certificado/chave de cliente, DNS/SNI/Host reais e sem
trust_env, redirects ou retries. Timeout: connect/pool 5s, write 30s, read 120s;
limites: 10 conexões, 5 keep-alive. Nenhum header do navegador é repassado.
Segredo ATS é relido a cada operação; senha/hash por autenticação/verificação de
sessão. Substituir o hash revoga sessões associadas ao anterior. TLS exige restart.

Uploads usam corpo bruto de até 5 MiB (limite do backend), assinatura PDF/estrutura
ZIP DOCX e schema JSON. Parsing completo e sanitização de documentos continuam no
subprocesso ATS. Arquivos não são persistidos no BFF. Downloads e JSON são lidos
com limite de 32 MiB para validar status, MIME e schema antes de entregar dados.
Esse buffering limitado foi escolhido porque o backend já gera resposta integral;
não há arquivo temporário nem streaming parcial seguido de erro silencioso.
Nomes de download são reconstruídos com ID validado; headers upstream não são
copiados. Respostas privadas, inclusive erros, têm no-store.

Auditoria SQLite registra template/método, IDs numéricos, resultado, status, duração
e timestamp. O operador é o único configurado; não se grava endereço IP bruto.
Falha de auditoria retorna 503, inclusive após operação cujo resultado pode ser
incerto. Nunca repetir escrita automaticamente: recarregar estado e revisão.
Access log Uvicorn/Nginx de workspace é desabilitado para evitar URLs privadas.
Rotação/retenção/backup do journal são responsabilidade operacional (ver operations).

OIDC futuro: substituir verificação local por Authorization Code + PKCE, state,
nonce, issuer/audience/assinatura e allowlist do operador. Preservar sessões opacas,
CSRF e fronteira ATS. Multiusuário depende primeiro de ownership no backend.

## Administração de descoberta

Rotas explícitas em `/workspace/admin` permitem ao operador administrar fontes e
consultar/executar coletas. Elas não usam o transporte ATS nem seus certificados,
token, operador delegado ou grants. O BFF exige sessão mais `discovery:admin` e
CSRF em cada escrita, então carrega um bearer administrativo separado de um arquivo
privado e encaminha somente operações codificadas no servidor. Respostas e erros
são validados e sanitizados; não existe proxy para caminhos arbitrários.

API e BFF compartilham a rede Docker `admin-private`, marcada internal. O BFF usa
`http://api:8765` com seu Host real; a API aceita esse hostname somente se o bearer
for válido e Origin/Fetch Metadata estiverem ausentes. A rede só dá conectividade,
não identidade. O token de 256 bits é a prova de serviço e fica em secret read-only
montado em ambos os containers. A API também permanece publicada apenas no loopback
do host. O Nginx não encaminha `/api/admin/*`; as rotas administrativas só entram
pelo prefixo autenticado `/workspace/admin`.

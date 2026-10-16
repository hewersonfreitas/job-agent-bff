# Integração Nginx e dependências frontend v0.4

O frontend `job-agent-web` foi inspecionado em `feat/advanced-job-explorer`:
README, ADR 001, nginx.conf, compose.yaml, Dockerfile, src/services/api.js e
src/styles/app.css. Nenhum arquivo desse repositório foi alterado neste PR.
A ADR propunha OIDC como preferência; o escopo explícito desta versão escolhe login
local de operador único, mantendo a futura substituição por OIDC documentada.

## Patch preciso para PR posterior

1. No compose.yaml do frontend, adicionar `bff-edge` à lista networks de web e
   declarar a rede externa cujo name seja `<backend-project>_bff-edge`.
   Não adicionar ats-private. Manter a rede pública existente para `api:8765`.
2. No Dockerfile web, copiar `workspace.nginx.conf` como snippet no diretório
   `/etc/nginx/snippets/`; montar o certificado/chave HTTPS em runtime, fora da
   imagem. No server, configurar `listen 8443 ssl`, ssl_certificate e
   ssl_certificate_key correspondentes à origem configurada no BFF.
3. Em nginx.conf remover o antigo bloco genérico `location /api/` e incluir o
   conteúdo exato de `deploy/workspace.nginx.conf` dentro do server HTTPS. O snippet
   inclui nova allowlist de leitura pública e nega todos os outros caminhos /api.
   Não criar proxy direto para ATS. Manter `/` estático e `/healthz` do frontend.
4. Publicar somente a porta HTTPS do web conforme a política de rede local.
   Executar nginx -t e os testes de regressão do frontend.

A allowlist pública preserva as leituras atualmente documentadas. Escritas públicas
PATCH /jobs/{id}/status e /social/posts/{id}/classification ficam negadas nesse
perfil seguro até possuírem contrato de autenticação próprio. A versão existente
local do frontend não é alterada. Administração de fontes está fora do escopo.
Bloquear todo o restante impede exposição de /resumes, /admin e variantes através
do proxy genérico, inclusive normalização de paths antes da seleção do location.

## Serviço HTTP ATS v0.4

Criar src/services/workspace.js separado de services/api.js (o cliente atual prefixa
/api e compartilha GETs). Prefixar /workspace e usar credentials:'same-origin'.

Fluxo: GET /auth/session → apresentar login explícito se authenticated=false →
POST /auth/login com JSON {password} → GET /auth/csrf → manter csrf_token em memória
→ operações POST/PATCH com X-CSRF-Token → POST /auth/logout sem corpo e limpar todos
os dados privados em memória. Buscar CSRF novamente invalida o token de outra aba;
403 exige sincronizar sessão/token e nova decisão do operador, sem replay de escrita.
O navegador fornece Origin/Fetch Metadata; o cliente JS não tenta forjá-los.

Não salvar senha, tokens, currículo ou respostas ATS em localStorage/sessionStorage,
URL, service worker ou caches compartilhados. Download via fetch autenticado + Blob
com revogação do object URL após uso. Não inserir token em URL. 401 limpa estado e
pede login; 409 recarrega versão/revisão; 503/timeout exibe resultado possivelmente
incerto e oferece consultar estado. Não fazer retry automático de POST/PATCH.

Reutilizar tokens e componentes existentes: .card, .field, .btn, .alert/.error,
.badge, .data-table e dialog acessível. Renderizar textos privados com x-text,
nunca x-html. Manter estados de carga/erro, revisão e consentimento explícitos.
A UI precisa de acesso às vagas públicas para selecionar job_id; o BFF não adiciona
busca ou matching. Somente liberar o módulo ATS após configurar HTTPS, operador,
policy/scopes/certificados e validar a integração real de ponta a ponta.

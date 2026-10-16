# Validação BFF v0.1

Ambiente local: host Python 3.14; testes executados em container Python 3.12.
Runtime BFF: FastAPI 0.143.3, Pydantic 2.14.1, HTTPX 0.28.1, Uvicorn 0.54.0.
Backend real v0.8 commit b28f3280a90dcebd625956f6bda41ff1b4d92cb3, com seu
Uvicorn 0.34.2 isolado em outro virtualenv/container conforme adaptador TLS.

Executado:

- Pytest: **98 passed**. Autenticação válida/inválida, rate limit persistente,
  expiração absoluta/inatividade, sessão após restart, limite de sessões, logout,
  revogação, troca de senha e session fixation.
- CSRF ausente/inválido, Origin/cross-site/same-site, headers de identidade e
  headers duplicados, métodos incorretos, body/query/IDs inválidos, anonimato.
- TLS real: cliente válido, ausente, CA estrangeira, expirado, fingerprint
  desconhecido, CA servidor incorreta, hostname incompatível, bearer/operator
  inválidos, serviço desabilitado, certificado revogado, scope e recurso negados.
- Backend real: 13 operações, JSON import, perfil, análise, personalização, diff,
  revisão, aprovação, relatórios, listagem, export PDF/DOCX e reimport binário;
  conflito 409 e erros operacionais sem retry; respostas estritas e sanitizadas.
- Ruff check e format --check aprovados.
- Snapshot SHA-256 e 13 operações comparados ao OpenAPI do checkout v0.8.
- Verificação de arquivos sensíveis e git diff --check aprovados.
- Build de produção BFF e ATS aprovados; pacote instalado carrega os contratos
  também fora do diretório /app. BFF roda non-root, imagem sem secrets de runtime.
- Smoke Compose com navegador HTTPS e Nginx reais: certificado servidor validado,
  cookie Secure transportado, /workspace encaminhado e rotas privadas/admin
  negadas sob /api (incluindo paths codificados). DNS Docker real: mTLS, ciclo ATS completo, roundtrip PDF/DOCX,
  healthchecks, redes internas, nenhuma porta publicada de ATS/BFF, sessão após
  restart e revogação após logout; logs sem senha/hash/bearer sintéticos.

Certificados, senha, perfil e arquivos dos testes são exclusivamente sintéticos.
Os projetos Compose têm nomes únicos e diretórios novos; limpeza não remove
volumes preexistentes. Nenhuma aplicação/candidatura automática é executada.

Limitações operacionais: credenciais reais e PKI devem ser provisionadas pelo
operador; não foram inventadas. A UI ATS e o deployment HTTPS real do frontend
exigem o PR posterior documentado. O smoke usa API pública sintética, pois não
altera discovery/matching nem o repositório web. O TestClient em Starlette atual
emite aviso de depreciação de HTTPX; não afeta os testes ou o cliente ATS HTTPX.
Git local não possui credencial HTTPS; publicação usa o conector GitHub autorizado.

CI remoto: após provisionar `ATS_BACKEND_READ_TOKEN` com Contents: read em
hewersonfreitas/job-agent, o checkout privado no commit fixado funciona. Ruff,
scanner de segredos, contrato, 98 testes, três builds Docker e smoke mTLS passaram
nos eventos push e pull_request após corrigir o healthcheck do serviço sintético.
O token não persiste no checkout; nenhum código privado foi copiado para o BFF.

O `public-stub` reutiliza a imagem BFF, cujo HEALTHCHECK verifica a porta 8081.
Como o stub serve na porta 8765, o override antigo desativava esse healthcheck.
Isso deixava o container sem healthcheck e fazia `compose up --wait` falhar no CI.
O override agora define um teste TCP na porta correta; o Nginx aguarda
`service_healthy`. As validações HTTPS, mTLS e de segurança permanecem completas.

O smoke imprime a versão do Compose (local: 5.5.1) e verifica o resultado dos
quatro overlays via `docker compose config --format json`: ATS, BFF, public-stub
e Web devem ter testes habilitados e nenhuma porta publicada. Após o startup,
`docker inspect` deve confirmar os mesmos comandos de healthcheck e estado
healthy nos quatro containers. Os logs mostram somente versão, serviço e estado,
sem imprimir configuração completa, caminhos de credenciais ou material privado.
Essas verificações explícitas não dependem de como cada versão do Compose trata
serviços sem healthcheck durante `--wait`.

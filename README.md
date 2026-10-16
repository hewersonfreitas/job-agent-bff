# Job Agent BFF v0.1

Autenticação segura para um único operador e gateway controlado para a API privada
ATS do Job Agent v0.8. Frontend continua estático; matching e documentos continuam
no backend. Nenhuma credencial privada chega ao navegador.

```text
Browser HTTPS → Nginx /workspace → BFF (sessão SQLite + CSRF)
                                      ↓ mTLS + ATS bearer + operador
                                https://ats-service:8766
```

Python 3.12, FastAPI, HTTPX, Argon2id e SQLite. Cookie
`__Host-job-agent-session` Secure/HttpOnly/SameSite=Lax, sessões opacas revogáveis,
Origin/Fetch Metadata, allowlist de 13 operações, scopes e grants do backend.
Não há senha padrão, cadastro público nem modo autenticado por HTTP.

- [Arquitetura e fonte dos contratos](docs/architecture.md)
- [Endpoints de sessão e ATS](docs/endpoints.md)
- [Docker, operador, HTTPS, mTLS, rotação e revogação](docs/operations.md)
- [Modelo de ameaças](docs/threat-model.md)
- [Patch Nginx e dependências frontend ATS v0.4](docs/nginx-frontend.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Validação executada](docs/validation.md)

Provisionar operador e materiais criptográficos explicitamente antes de iniciar.
`.env.example` contém somente caminhos e configuração sem segredos. O overlay
`compose.yaml` é aplicado após os dois Compose existentes do backend, conforme
o guia operacional. Não publica portas ATS/BFF e não exige copiar certificados.
Não altera os outros repositórios nem remove controles locais existentes.

Validação local em Python 3.12:

```sh
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m scripts.check_sensitive
.venv/bin/python -m scripts.check_contract --upstream /absolute/path/job-agent
.venv/bin/pytest -q
```

O teste real TLS requer checkout backend v0.8, suas dependências, OpenSSL e DNS
sintético. A CI os configura e executa também Compose. Alternativa isolada:

```sh
docker build -t job-agent-bff:v0.1 .
docker build -f deploy/Dockerfile.validation -t job-agent-bff:validation .
docker build -t job-agent-ats:v0.8 /absolute/path/job-agent
docker run --rm --user "$(id -u):$(id -g)" --add-host ats-service:127.0.0.1 \
  -e ATS_BACKEND_DIRECTORY=/upstream -e HOME=/tmp \
  -v "$PWD:/app" -v /absolute/path/job-agent:/upstream:ro \
  job-agent-bff:validation python -m pytest -q -p no:cacheprovider
python -m scripts.docker_smoke --backend /absolute/path/job-agent
```

Testes usam apenas currículos e certificados sintéticos, nunca dados pessoais.
O último comando usa apenas biblioteca padrão Python no host e Docker.
A UI ATS completa, OIDC e ownership multiusuário ficam para versões futuras.

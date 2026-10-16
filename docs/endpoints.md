# API do navegador

Mesma origem HTTPS. Erros: `{ "detail": "mensagem sanitizada" }`. Sem CORS.
Toda resposta /workspace usa Cache-Control: no-store. Campos desconhecidos são
negados em entradas com schema. Headers Authorization/X-ATS-*/identidade TLS
assertada são rejeitados. X-Forwarded-* não estabelece identidade no BFF.

| Método | Caminho | Corpo / resposta |
|---|---|---|
| POST | /workspace/auth/login | JSON `{password}` → `{authenticated:true,operator_id}` + cookie |
| GET | /workspace/auth/session | `{authenticated,operator_id}`; anônimo false/null |
| GET | /workspace/auth/csrf | sessão obrigatória → `{csrf_token}` novo |
| POST | /workspace/auth/logout | sem corpo, X-CSRF-Token → 204; revoga cookie no servidor |
| GET | /healthz | `{ok:true}`; prontidão do SQLite, sem dados/segredos |

Login exige Content-Type application/json e Origin exata, sem credencial padrão.
401: login/sessão inválidos; 403: política/CSRF/origem; 429: limite de login.
Limites persistem após restart: 5 tentativas/IP/300s e 25 globais/300s por padrão;
contam também sucessos para evitar churn. IP é o peer de transporte (atrás do Nginx
é o proxy), nunca X-Forwarded-For. Proteção conservadora para um único operador.

Prefixo ATS: `/workspace/ats`. Sufixos abaixo são exatamente os da API privada.
Todos exigem sessão e scope; POST/PATCH exigem CSRF, Origin e mídia correta.

| Método | Sufixo | Entrada | Scope |
|---|---|---|---|
| POST | /resumes/import | PDF/DOCX/JSON bruto, X-Filename opcional | ats:import |
| GET | /resumes | limit 1..200, offset >=0 | ats:read |
| GET | /resumes/{resume_id} | ID positivo | ats:read |
| GET | /resumes/{resume_id}/profile | ID positivo | ats:read |
| PATCH | /resumes/{resume_id}/profile | ProfileReview | ats:profile:write |
| POST | /jobs/{job_id}/requirements/analyze | sem corpo | ats:analyze |
| POST | /jobs/{job_id}/resumes/tailor | TailorInput | ats:tailor |
| GET | /jobs/{job_id}/resumes | limit, offset | ats:read |
| GET | /resumes/versions/{version_id}/diff | ID positivo | ats:read |
| PATCH | /resumes/versions/{version_id}/review | VersionReview | ats:review |
| POST | /resumes/versions/{version_id}/approve | Approval | ats:approve |
| GET | /resumes/versions/{version_id}/ats-report | ID positivo | ats:read |
| GET | /resumes/versions/{version_id}/export | format=pdf ou docx | ats:export |

Schemas completos: `contracts/ats-v0.8.json#/components/schemas`.
ProfileReview: expected_revision, profile, confirm_all/confirm_ids, notes.
TailorInput: resume_id, language (pt-BR/en), provider
(deterministic/claude_code/codex), consent_external_processing, template.
VersionReview: expected_revision, decisions [{id,decision:accepted/rejected}],
reject_version, notes. Approval: expected_revision, acknowledge_gaps,
supersede_version_id opcional, notes. Os defaults são os do upstream.
Import JSON aceita ProfessionalProfile direto ou `{profile,filename}`.
PDF/DOCX não aceitam multipart. Nome deve ser basename ASCII seguro com extensão
correspondente; JSON wrapper também valida filename. Backend continua responsável
pela validade semântica dos documentos e perfis.

Respostas mantêm os campos upstream (inclusive extração textual privada autorizada),
sem caminhos internos de artefatos. Download tem MIME PDF/DOCX, Content-Disposition
attachment e X-Resume-State quando válido. Nunca contém token em URL.
409 é preservado: recarregar versão/perfil e decidir novamente. 502 indica resposta
incompatível ou falha do provider; 503 indica indisponibilidade. Após timeout/503,
a escrita pode ter ocorrido; não repetir automaticamente.

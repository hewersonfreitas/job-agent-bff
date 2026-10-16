# Operação, provisionamento e Docker

Requer Docker Compose v2+, backend com contrato v0.8 do commit documentado em
architecture.md e frontend estático. Não é necessário repetir operações Git para
iniciar: após obter os repositórios, basta configurar arquivos e executar Compose.
O overlay usa a infraestrutura ATS existente e não altera os outros repositórios.

## Provisionar o operador

Escolha um diretório privado absoluto fora do Git, servido pelo mesmo UID não-root
que executará o BFF. Diretório 0700, arquivos 0600. O operador executa explicitamente:

```sh
python -m bff.operator provision --output /absolute/private/operator.argon2
```

O comando pede duas vezes a senha (14..1024 caracteres), sem eco e sem argumento
contendo a senha. Gera apenas hash Argon2id (64 MiB, 3 iterações, paralelismo 4).
Não existe senha padrão, cadastro, API de provisionamento ou credencial real gerada
pelos testes. Também é possível rodar o comando interativamente na imagem Docker
com o diretório privado montado, usando o UID proprietário dos arquivos.

Copie `.env.example` para `.env` e configure **caminhos**, origem e operador. Nunca
coloque senha ou bearer no .env. O hash não deve entrar no Git. `BFF_OPERATOR_ID`
deve ser exatamente o `operator_id` da política do ATS, não uma identidade escolhida
pelo navegador. Nenhuma credencial ADMIN/SOCIAL/RESUME da API local substitui ATS.

## Provisionar mTLS

O operador/PKI emite certificado servidor com SAN DNS `ats-service` e EKU serverAuth,
certificado cliente com EKU clientAuth e chaves privadas separadas. Configure CA
servidor confiável no BFF e CA cliente confiável no ATS. Confira cadeia, validade e
fingerprint SHA-256 do cliente; registre-o no policy.json do backend com serviço
habilitado, validade e scopes reais. O contrato ATS e exemplo de política completo
estão em `job-agent/docs/ats-service-auth.md`. Não gerar PKI real automaticamente.

Configure ATS_POLICY_DIRECTORY, ATS_TOKEN_FILE, ATS_SERVER_CERT_FILE,
ATS_SERVER_KEY_FILE, ATS_CLIENT_CA_FILE e os BFF_*_FILE no .env. BFF_TOKEN_FILE em
execução direta aponta ao **mesmo arquivo** que ATS_TOKEN_FILE. No Compose ambos
consomem o secret ats_token. As CAs e certificados são montados diretamente dos
caminhos absolutos provisionados; não há cópia manual entre repositórios.

Compose local mantém UID/mode dos bind mounts de secrets. `BFF_RUNTIME_USER` deve
ser não-root e ter leitura dos arquivos privados. O padrão da imagem é 10001:10001;
se optar por outro UID, prepare **somente o novo volume BFF** com esse proprietário.
Não modificar ownership de volumes ATS existentes. ATS e API precisam ter UID
compatível com os dados existentes, conforme guia upstream. A imagem upstream ATS
atual roda root; para uma implantação endurecida configure um override `user` com
UID não-root compatível com os volumes/segredos existentes. O smoke usa UID não-root
para ATS e BFF com diretórios sintéticos novos.

## Inicializar

A partir do diretório BFF, usando caminhos absolutos configurados no `.env`:

```sh
docker compose --env-file .env --project-directory /absolute/path/job-agent \
  -f /absolute/path/job-agent/compose.yaml \
  -f /absolute/path/job-agent/compose.ats.yaml \
  -f /absolute/path/job-agent-bff/compose.yaml config --quiet
docker compose --env-file .env --project-directory /absolute/path/job-agent \
  -f /absolute/path/job-agent/compose.yaml \
  -f /absolute/path/job-agent/compose.ats.yaml \
  -f /absolute/path/job-agent-bff/compose.yaml up -d --build --wait ats-service bff
```

Use o **mesmo project name do backend existente** se integrar com sua implantação;
não crie outra instância concorrente escrevendo nos mesmos arquivos. A resolução de
paths relativos é a do backend (primeiro Compose/--project-directory), portanto
seus data/resumes permanecem nos locais atuais. BFF_DIRECTORY é absoluto.
Nenhum ports no ATS/BFF. Health do BFF verifica SQLite; ATS health é prontidão local,
não comprovação de mTLS ponta a ponta. O smoke separado valida essa comunicação e o snippet Nginx com HTTPS sintético.
Volumes ATS existentes são preservados; bff-sessions é novo volume persistente.

Nginx deve compartilhar apenas a rede `<backend-project>_bff-edge` com o BFF. ATS
fica em ats-private internal. Não anexar Nginx à rede ATS. Veja nginx-frontend.md.
BFF-edge também é internal; o frontend mantém sua rede pública existente para
servir HTTPS e consultar a API pública. Não publicar diretamente 8081/8766.

## HTTPS local

Use certificado confiável para o hostname local do navegador (ex.: localhost),
emitido por sua CA local, e configure um server Nginx `listen 8443 ssl`, certificado
e chave montados read-only fora do Git. BFF_ORIGIN deve coincidir exatamente com
`https://localhost:8443`. Confie na CA no navegador; não desabilite verificação TLS.
O certificado do navegador é independente do certificado servidor ATS. Não use
HTTP para login, não remova Secure e não falsifique Host para o ATS.
O arquivo deploy/workspace.nginx.conf é incluído nesse server HTTPS.

## Rotação e revogação

- Sessões: `python -m bff.operator revoke-sessions` no ambiente com BFF_* configurado,
  acessando o volume persistente. Logout revoga somente a sessão corrente.
- Senha: provisionar hash em novo arquivo, substituí-lo atomicamente pelo operador;
  sessões vinculadas ao hash anterior são recusadas. Bind mount pode fixar inode:
  recriar o BFF se necessário. Não usar provision sobre arquivo existente.
- Bearer ATS: atualizar secret do backend e BFF em janela controlada; são o mesmo
  arquivo provisionado. Mismatch falha fechado. Recriar se bind mount pinou inode.
- Certificado cliente: adicionar novo fingerprint ao policy, atualizar mount/recriar
  BFF, verificar fluxo, revogar antigo. ATS verifica revogação em cada request.
- CA/certificado servidor: atualizar materiais e recriar ATS/BFF para novos contexts.

Backups de SQLite devem usar API de backup SQLite ou parada controlada, proteger
modos e criptografar no armazenamento. A auditoria cresce sem retenção automática;
defina retenção com backup/rotação offline e monitore espaço. Nunca apagar banco
ativo para resolver bloqueio. Falha de auditoria é 503 e pode acompanhar escrita
concluída: consultar estado/revisão antes de qualquer nova tentativa.

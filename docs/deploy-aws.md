# Setup AWS com Terraform e deploy automático

O [pipeline do GitLab](../.gitlab-ci.yml) usa o [Terraform](../infra/terraform/)
para criar ou atualizar a infraestrutura e publicar a aplicação quando o espelhamento
do GitHub atualiza a `main` protegida do projeto
[`2026-2/2jk-4jk/hangy/hangy-backend`](https://tools.ages.pucrs.br/2026-2/2jk-4jk/hangy/hangy-backend).
Merge requests executam somente as validações. O deploy exige o projeto e o
servidor da AGES; forks, tags e outras branches não publicam.

Todo o desenvolvimento e os merges acontecem no GitHub. O workflow
[Mirror to AGES GitLab](../.github/workflows/mirror-to-gitlab.yml) espelha `main`,
`develop` e tags com force push: as referências correspondentes no GitLab são
sobrescritas pelo conteúdo do GitHub. O GitLab é o repositório de entrega e executa
o deploy após receber a atualização da `main`; não é necessário outro merge lá.
Atualizações de `develop` e tags não publicam na AWS.

## Recursos criados

| Recurso | Configuração inicial |
| --- | --- |
| Região | **us-east-2**, Leste dos EUA (Ohio), para todos os recursos regionais |
| EC2 | Uma **t4g.medium**, Linux ARM64, tenancy compartilhada, monitoramento detalhado desabilitado |
| Disco EC2 | Volume raiz gp3 criptografado de **8 GB**, para o sistema operacional, Docker, imagens e logs; dados da aplicação persistidos no RDS |
| Elastic IP | IP público fixo da API |
| RDS | PostgreSQL 17, uma **db.t4g.micro**, Single-AZ, **50 GB gp2**, sem autoscaling de armazenamento |
| Rede | VPC própria, uma sub-rede pública para a EC2 e duas privadas para o RDS |
| Banco | Criptografia, TLS obrigatório, backups por 7 dias e proteção contra exclusão |
| ECR | Imagens privadas com tags imutáveis e scan no push |
| S3 | Bucket privado para objetos Standard, criptografia SSE-S3, ACLs desabilitadas e TLS obrigatório |
| State Terraform | Bucket S3 separado, privado, criptografado, versionado e com lock de execução |
| Secrets Manager | Credenciais do banco e JWT geradas automaticamente, configurações da API |
| IAM/OIDC | Role da EC2 e role do GitLab limitada à `main` do projeto informado |
| SSM | Preparação automática da EC2 e execução dos deploys |

O RDS aceita conexões na porta 5432 somente do security group da EC2. As sub-redes
privadas não têm rota para a internet. A EC2 usa o Internet Gateway para acessar
ECR, Secrets Manager, SSM e os repositórios de pacotes. Não há NAT Gateway ou
load balancer neste setup. A administração ocorre pelo Session Manager, sem SSH.

O bootstrap instala Docker, AWS CLI, `jq` e demais ferramentas na EC2. O Terraform
aguarda a associação SSM concluir com sucesso antes de terminar o setup. A AMI
escolhida na criação é preservada nos próximos applies; atualizar a AMI exige
substituição intencional da instância.

## 1. Preparar o projeto e o runner do GitLab

Em **Settings → Repository → Protected branches / Branch rules**, proteja a
`main`, habilite **Allowed to force push** e permita push à identidade usada pelo
token de espelhamento em **Allowed to push and merge**. A branch deve continuar
protegida: o job de deploy exige `CI_COMMIT_REF_PROTECTED == "true"`.
Se `develop` ou tags também estiverem protegidas, permita ao espelhamento
atualizar essas referências. Faça as alterações de código e merges no GitHub.

No GitHub, mantenha a variável `GITLAB_USERNAME` e o secret `GITLAB_TOKEN` usados
pelo espelhamento. O token precisa de acesso de escrita ao repositório GitLab
e a identidade precisa ter permissão para atualizar a `main` protegida.
As credenciais AWS ficam nas variáveis CI/CD do GitLab.

O pipeline precisa de um runner Linux com **executor Docker**, tag
**`hangy-docker`**, acesso ao projeto e modo **privileged** para Docker-in-Docker.
Ele deve aceitar jobs de merge requests e da `main` protegida. Se um runner
existente usa outra tag e atende aos requisitos, altere `default.tags` no YAML.
Um runner com executor shell não atende a esta configuração de `image/services`.

O runner pode ser AMD64 ou ARM64: o build gera `linux/arm64` para a EC2 e instala
emulação QEMU quando necessário. Precisa alcançar GitLab, Docker Hub, PyPI,
HashiCorp e as APIs AWS pela internet, e ter espaço para build, imagens e cache.
O serviço Docker-in-Docker usa a porta 2375 sem TLS dentro da rede isolada do job;
essa porta não deve ser publicada no host do runner.

O runner precisa existir antes do primeiro pipeline; ele não é instalado na EC2
da aplicação pelo Terraform. Consulte **Settings → CI/CD → Runners** ou a equipe
da AGES. Sem um runner compatível, os jobs ficam pendentes ou falham ao usar Docker.

O pipeline usa o token predefinido `CI_JOB_JWT_V2`, disponível para integração
OIDC a partir do GitLab 14.7, para funcionar na instância que não reconhece
`id_tokens` (introduzido no GitLab 15.7). Não cadastre esse token nas variáveis
CI/CD: ele é emitido pelo GitLab para cada job. Se estiver ausente, o deploy
falha antes de criar recursos.

O GitLab precisa expor publicamente seu discovery OIDC e suas chaves em
`https://tools.ages.pucrs.br`. A AWS usa esses endpoints para validar o token,
cuja audiência fixa é `https://tools.ages.pucrs.br`. O Terraform configura essa
audiência no provedor e na role, limitada ao caminho completo do projeto e à
`main`. Ao reutilizar um provedor externo ao state, o script adiciona a audiência
se necessário, preservando as demais.

`CI_JOB_JWT_V2` foi removido no GitLab 17.0. Antes de atualizar para essa versão,
migre o job para `id_tokens` e ajuste a audiência do provedor e da role juntos.

## 2. Configurar variáveis CI/CD no GitLab

Em **Settings → CI/CD → Variables**, crie as variáveis abaixo como **Protected**,
com **Environment scope: production**. Marque credenciais como **Masked**
e desabilite expansão de referências. Use o tipo **Variable**, não **File**.
Assim, as credenciais ficam disponíveis somente ao job de produção.

| Variável obrigatória | Valor |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | Access key de uma identidade IAM autorizada a provisionar a infraestrutura |
| `AWS_SECRET_ACCESS_KEY` | Secret access key correspondente |
| `FRONTEND_BASE_URL` | URL HTTP(S) do frontend, por exemplo `https://hangy.example` |

A identidade AWS precisa de permissões para gerenciar VPC, EC2/EBS/EIP, RDS,
ECR, S3, Secrets Manager, IAM/OIDC e documentos/associações SSM, incluindo
`iam:PassRole`, `iam:ListOpenIDConnectProviders`, `iam:GetOpenIDConnectProvider`
e `iam:AddClientIDToOpenIDConnectProvider` para reutilizar um provedor existente.
A role de deploy criada pelo
Terraform tem permissões menores e não serve como credencial de provisionamento.
A credencial inicial é o único acesso AWS que precisa existir antes do pipeline.

Variáveis opcionais, também com escopo `production`:

| Variável | Padrão / formato |
| --- | --- |
| `AWS_SESSION_TOKEN` | Necessário somente se as credenciais AWS forem temporárias; atualize quando expirarem |
| `AWS_REGION` | `us-east-2` (Ohio), conforme a estimativa |
| `CORS_ORIGINS` | Lista JSON de origens autorizadas, por exemplo `["https://hangy.example", "http://localhost:8081"]`. Se omitida ou vazia, usa `FRONTEND_BASE_URL` sem a barra final |
| `API_ALLOWED_CIDRS` | `["0.0.0.0/0"]`; lista JSON de origens IPv4 autorizadas na porta 8000 |
| `TF_STATE_KEY` | `<CI_PROJECT_PATH>/production.tfstate`; informe a chave anterior se a infraestrutura já foi criada pelo GitHub |

O caminho do projeto é obtido automaticamente do GitLab. Senha do PostgreSQL,
chave JWT e `DATABASE_URL` são gerados pelo Terraform e guardados no Secrets
Manager. Não é necessário cadastrá-los nas variáveis do GitLab.

`FRONTEND_BASE_URL` é o endereço do frontend usado para gerar `web_url` nos
compartilhamentos: `<FRONTEND_BASE_URL>/e/<id>` ou
`<FRONTEND_BASE_URL>/invite/<token>`. A resposta também inclui `url`, com o link
do aplicativo `hangy://event/<id>` ou `hangy://invite/<token>`.
O endereço público da API é separado e aparece no log do deploy; é esse
endereço que o frontend usa para fazer requisições ao backend.

## 3. Executar o deploy

Após configurar o runner e as variáveis, faça merge na `main` do GitHub.
O workflow de espelhamento envia o commit para a `main` do GitLab, cujo pipeline
executa o deploy. Acompanhe o espelhamento no GitHub Actions e o deploy no GitLab
em **Build / CI/CD → Pipelines**. Para repetir o deploy do commit atual,
use **Retry** no job `deploy` do pipeline da `main`. O pipeline executa:

1. Lint, formatação, testes da API e migrações em um PostgreSQL de teste.
2. Validação e testes do Terraform e do bootstrap, sem acesso à AWS.
3. Criação ou reutilização do bucket S3 dedicado ao estado do Terraform.
4. `terraform plan` e `terraform apply` para criar ou atualizar a infraestrutura.
5. Leitura dos IDs dos recursos criados e autenticação OIDC com a role de deploy.
6. Build e smoke test da imagem `linux/arm64`, publicação no ECR e deploy na EC2.
7. Migrações no RDS e health check da aplicação.

**O apply é automático nos pushes da `main`**, sem etapa manual de aprovação.
Isso inclui mudanças feitas nos arquivos Terraform. O primeiro deploy leva mais
tempo porque cria o RDS e prepara a EC2; os seguintes reutilizam a infraestrutura.
O provedor OIDC do GitLab é criado se necessário ou reutilizado se já existir na
conta. Um provedor criado por este state permanece gerenciado por ele.

A URL da API aparece no log do job `deploy`. O endpoint inicial
é HTTP na porta 8000; domínio e HTTPS não são configurados neste módulo.

Os jobs `test` e `validate-infra` verificam merge requests sem provisionar recursos
e precisam passar antes do deploy. No GitHub, as verificações de PR continuam.
O job de deploy usa `resource_group: aws-production` para serializar todo o fluxo
e rejeita um commit que já não seja o mais recente da `main` ao iniciar.

## Estado persistente da infraestrutura

O pipeline prepara o bucket `hangy-tfstate-<ACCOUNT_ID>-<AWS_REGION>` antes do
`terraform init`. Esse bucket é separado do bucket S3 de arquivos da aplicação
e usa criptografia SSE-S3, versionamento, bloqueio de acesso público e TLS
obrigatório. O backend habilita `use_lockfile` para impedir alterações concorrentes.

O state fica em `<CI_PROJECT_PATH>/production.tfstate` e permite que cada execução
atualize os mesmos recursos. Ele contém credenciais do banco e a chave JWT, por
isso a identidade de provisionamento precisa de acesso restrito a esse bucket.
O plano salvo é removido do runner depois do apply e não é publicado como artifact.
O bucket de state é preparado pelo script de bootstrap, fora do state da aplicação,
e não é excluído pelo Terraform dessa aplicação.

Mantenha a conta, região, nome do repositório e chave do state estáveis. Alterá-los
sem migrar o state faz o pipeline procurar outra instalação. Se já executou o
setup manual anterior, migre o state local para esse backend com
`terraform init -migrate-state` antes de ativar o primeiro deploy automático;
não inicie com um state vazio sobre os recursos já existentes.

Se já houve um deploy pelo GitHub, configure `TF_STATE_KEY` com a chave antiga
`<OWNER>/<REPO>/production.tfstate` antes do primeiro deploy GitLab. Mantenha a
conta, região e prefixo dos recursos. A configuração troca a integração IAM/OIDC
do GitHub pela do GitLab; a EC2, o RDS e os dados continuam no mesmo state.
Remova as credenciais de provisionamento dos Secrets do GitHub após a migração.

Para diagnóstico local, use `terraform init -backend=false`, `terraform validate`
e `terraform test`. Para administrar recursos reais localmente, inicialize o
backend com o mesmo bucket, região e chave usados pelo pipeline. Versione
`.terraform.lock.hcl`; não versione states, planos, `.tfvars` ou credenciais.


Ao atualizar providers, gere também os checksums para o Linux AMD64 usado no CI:

```sh
terraform -chdir=infra/terraform providers lock -platform=linux_amd64 -platform=windows_amd64
```

Versione o `.terraform.lock.hcl` atualizado. O CI usa `-lockfile=readonly`, então
os checksums da plataforma do runner precisam estar registrados antes da execução.
Se usar um runner Linux ARM64, inclua também `-platform=linux_arm64` no comando.

## Atualizações e recuperação

- Mude `FRONTEND_BASE_URL` ou `CORS_ORIGINS` nas variáveis CI/CD do GitLab e repita o deploy
  para atualizar a infraestrutura e a configuração do contêiner. O Terraform
  é a fonte das configurações; mudanças manuais no Secrets Manager podem ser
  sobrescritas pelo próximo apply.
- Os deploys são serializados no GitLab e por um lock na EC2. Cancelar uma execução
  no GitLab não necessariamente interrompe o comando SSM. Confira o Command ID
  registrado no log antes de repetir.
- As migrações rodam enquanto a API anterior ainda atende. Elas devem ser
  compatíveis com a versão anterior. Nenhum seed de desenvolvimento é executado.
- Há uma breve indisponibilidade durante a troca de contêiner. Se o health check
  falhar, o script tenta restaurar o contêiner anterior. **O banco não sofre
  downgrade automático.** `/health` verifica a API; a migração testa a conexão
  com o banco antes da troca.
- Para diagnóstico, use **Systems Manager → Run Command → Command ID**, Session
  Manager e `sudo docker logs --tail 100 hangy-api`. Logs remotos não são copiados
  para o GitLab, pois podem conter detalhes internos da aplicação.
- Se houver interrupção abrupta, pode restar `hangy-api-previous`. Inspecione
  `sudo docker ps -a` e recupere ou remova esse contêiner conforme o estado da API
  antes do próximo deploy.
- Logs Docker têm rotação de 3 arquivos de 10 MB. Imagens antigas permanecem no
  ECR e no disco da EC2; estabeleça retenção conforme a frequência de deploys.
- RDS e o segredo têm `prevent_destroy`; o RDS também possui proteção de exclusão
  na AWS. Para desativar a instalação, remova essas proteções de forma intencional
  após preservar os dados. O RDS solicita snapshot final ao ser excluído. O ECR
  não é excluído enquanto contiver imagens (`force_delete = false`).

Referências: [state e dados sensíveis no Terraform](https://developer.hashicorp.com/terraform/language/manage-sensitive-data),
[backend S3](https://developer.hashicorp.com/terraform/language/backend/s3),
[Docker no GitLab CI](https://docs.gitlab.com/ci/docker/using_docker_build/),
[branches protegidas e force push](https://docs.gitlab.com/user/project/repository/branches/protected/),
[OIDC do GitLab na AWS](https://docs.gitlab.com/ci/cloud_services/aws/)
e [SSM Run Command](https://docs.aws.amazon.com/systems-manager/latest/userguide/walkthrough-cli.html).

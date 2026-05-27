# Atualização automática - JMS Coletor Waybill

Este projeto foi preparado no modelo:

- `Verificacao_IDs_JT_Express.exe`: app principal
- `Atualizador.exe`: atualizador separado
- `version.json`: versão instalada
- `update_config.json`: configuração do repositório GitHub
- `build_release.bat`: gera o ZIP pronto para subir no GitHub Releases

## Como funciona

1. O usuário clica em **Verificar atualização** dentro do app.
2. O app consulta a última Release do GitHub.
3. Se houver versão nova, o botão **Atualizar sistema** é liberado.
4. Ao clicar em **Atualizar sistema**, o app abre `Atualizador.exe` em uma pasta temporária.
5. O app principal fecha.
6. O atualizador baixa o ZIP da última Release.
7. O atualizador substitui o EXE antigo e os arquivos da aplicação.
8. O atualizador preserva:
   - `config.json`
   - `update_config.json`
   - `chrome_jms_profile/`
   - `exports/`
9. O app novo é aberto.
10. Aparece a mensagem **Atualização concluída**.

## 1. Configurar o GitHub

Crie um repositório no GitHub.

Exemplo:

```text
jms-coletor-waybill
```

Depois edite o arquivo:

```text
update_config.json
```

Troque:

```json
{
  "owner": "SEU_USUARIO_OU_ORGANIZACAO",
  "repo": "SEU_REPOSITORIO",
  "asset_contains": "Verificacao_IDs_JT_Express",
  "allow_prerelease": false,
  "github_token": ""
}
```

Por exemplo:

```json
{
  "owner": "eduardorsouza004",
  "repo": "jms-coletor-waybill",
  "asset_contains": "Verificacao_IDs_JT_Express",
  "allow_prerelease": false,
  "github_token": ""
}
```

Se o repositório for privado, será necessário usar token no `github_token`.
Para evitar risco, o mais simples é usar um repositório público apenas para os ZIPs de release.

## 2. Gerar uma release

Rode:

```bat
build_release.bat
```

Digite a versão, por exemplo:

```text
1.0.0
```

Ele vai gerar:

```text
release\Verificacao_IDs_JT_Express-v1.0.0.zip
```

Esse é o arquivo que deve ser anexado na Release do GitHub.

## 3. Criar Release no GitHub

No repositório:

1. Clique em **Releases**.
2. Clique em **Draft a new release**.
3. Em tag, coloque:

```text
v1.0.0
```

4. Em título, coloque:

```text
v1.0.0
```

5. Anexe o arquivo:

```text
Verificacao_IDs_JT_Express-v1.0.0.zip
```

6. Clique em **Publish release**.

## 4. Instalar na outra máquina

Na outra máquina, baixe o ZIP da primeira release.

Extraia em uma pasta, por exemplo:

```text
C:\JMS_Coletor_Waybill
```

Abra:

```text
Verificacao_IDs_JT_Express.exe
```

## 5. Atualizar depois

Quando você alterar o código:

1. Rode `build_release.bat`.
2. Digite uma versão maior, exemplo:

```text
1.0.1
```

3. Suba no GitHub uma nova Release:

```text
v1.0.1
```

4. Anexe:

```text
Verificacao_IDs_JT_Express-v1.0.1.zip
```

5. Na outra máquina, abra o app e clique:

```text
Verificar atualização
Atualizar sistema
```

## Observações importantes

- O app principal não substitui ele mesmo.
- Por isso ele abre o `Atualizador.exe` separado.
- O `Atualizador.exe` é copiado para uma pasta temporária antes de rodar.
- Isso permite substituir também o `Atualizador.exe` antigo dentro da pasta do app.
- Não suba `config.json`, `chrome_jms_profile`, `exports`, `build`, `dist` ou `release` no GitHub.

## Correção do erro base_library.zip em uso

Se aparecer erro dizendo que `_internal\base_library.zip` está sendo usado por outro processo, use o `build_release.bat` atualizado deste pacote. Ele fecha processos antigos, aguarda o Windows/antivírus liberar os arquivos, copia o build para uma pasta temporária `release_staging` e só depois compacta o ZIP da release.

Se ainda assim falhar, faça antes de rodar o build:

1. Feche o `Verificacao_IDs_JT_Express.exe`.
2. Feche o `Atualizador.exe` se estiver aberto.
3. Feche janelas do Explorer abertas dentro da pasta `dist`.
4. Feche Chrome/Selenium se ficaram abertos.
5. Rode `build_release.bat` como Administrador.

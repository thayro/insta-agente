<p align="center">
  <img src="banner-insta-agente.png" alt="Insta-Agente banner" width="100%" />
</p>

<h1 align="center">Insta-Agente</h1>
<p align="center"><strong>StudioLab · IA local para criação, aprovação e publicação no Instagram</strong></p>

<p align="center">
  Aplicação local para gerar conteúdo com IA, organizar posts, validar pelo Telegram e publicar no Instagram a partir de um painel web simples.
</p>

---

## Visão geral

O **Insta-Agente** é um workspace local voltado para criação e operação de conteúdo para Instagram. O projeto combina **Ollama** para geração textual, **ComfyUI** para imagens, **Flask** para a interface web, **Telegram** para revisão/aprovação e **Instagram** para publicação.

A proposta é centralizar o fluxo em um único painel:

1. gerar ideias e legendas com IA;
2. montar artes e posts;
3. revisar e aprovar via Telegram;
4. publicar no Instagram;
5. manter uma biblioteca local com histórico dos conteúdos.

> Projeto pensado para **uso local**, com integrações configuradas na própria máquina.

---

## Principais recursos

- **Geração de conteúdo com IA local** via Ollama
- **Criação de imagens** com suporte a ComfyUI
- **Painel web em Flask** para controlar o fluxo
- **Biblioteca de posts** com histórico local
- **Modo manual** para subir imagens prontas e publicar
- **Aprovação via Telegram** antes da postagem
- **Publicação no Instagram** por conta configurada
- **Troca de conta do Instagram** com validação segura
- **Seleção de modelo Ollama** e checkpoint do ComfyUI
- **Isolamento de contexto por conta** para histórico editorial

---

## Como funciona o fluxo

```text
Ideia/briefing → geração com IA → criação do card/post → revisão → aprovação no Telegram → publicação no Instagram
```

O fluxo também pode funcionar em modo manual:

```text
Upload de imagens + legenda → revisão → aprovação → publicação
```

---

## Stack do projeto

- **Backend:** Python 3.13 + Flask
- **IA local (texto):** Ollama
- **IA de imagem:** ComfyUI
- **Composição de imagens:** Pillow
- **Integrações:** Telegram + Instagram
- **Frontend:** HTML, CSS e JavaScript
- **Ambiente-alvo atual:** Windows

---

## Estrutura do repositório

```text
.
├── app.py                           # App Flask, APIs e fluxo principal
├── gerar_card.py                    # Geração do conteúdo e composição dos cards
├── comfyui_client.py                # Cliente para integração com ComfyUI
├── integracoes.py                   # Telegram e Instagram
├── templates/                       # Interface HTML
├── static/                          # CSS e JavaScript do painel
├── data/
│   ├── config_integracoes.example.json
│   └── studiolab_settings.example.json
├── instalar_portal.bat              # Instalação do ambiente local
├── iniciar_portal.bat               # Inicialização do portal
└── requirements_portal.txt          # Dependências Python
```

---

## Requisitos

Antes de iniciar, tenha instalado:

- **Windows**
- **Python 3.13**
- **Git**
- **Ollama** com ao menos um modelo baixado
- **ComfyUI** instalado localmente (opcional, mas recomendado)
- conexão com a internet para Telegram e Instagram

Serviços esperados pelo projeto:

- **Ollama:** `http://127.0.0.1:11434`
- **ComfyUI:** `http://127.0.0.1:8188`
- **Portal Flask:** `http://127.0.0.1:5005`

---

## Instalação

### 1) Clone o repositório

```bash
git clone https://github.com/thayro/insta-agente.git
cd insta-agente
```

### 2) Instale o ambiente

No Windows, execute:

```bat
instalar_portal.bat
```

Esse script cria o ambiente virtual `.venv_portal` e instala as dependências de `requirements_portal.txt`.

### 3) Inicie o portal

```bat
iniciar_portal.bat
```

### 4) Acesse no navegador

```text
http://127.0.0.1:5005/
```

---

## Configuração

O projeto usa arquivos locais na pasta `data/`.

### Exemplos incluídos no repositório

- `data/config_integracoes.example.json`
- `data/studiolab_settings.example.json`

### Arquivos reais gerados localmente

- `data/config_integracoes.json`
- `data/instagram_session.json`
- `data/studiolab_settings.json`

> Os arquivos reais **não devem ser versionados**.

### Exemplo de integrações

```json
{
  "telegram": {
    "enabled": false,
    "bot_token": "",
    "chat_id": "",
    "allowed_user_ids": [],
    "auto_send_review": true
  },
  "instagram": {
    "enabled": false,
    "username": "",
    "password": "",
    "auto_publish_on_approval": false
  }
}
```

---

## Segurança

Este repositório é **público**, então atenção especial com dados sensíveis.

### Nunca publique

- `data/config_integracoes.json`
- `data/instagram_session.json`
- senhas
- tokens
- sessões autenticadas
- logs privados
- posts sensíveis
- `.venv_portal/`

O `.gitignore` já foi preparado para evitar commits acidentais desses itens.

Se você publicou o projeto anteriormente com segredos reais, o ideal é:

1. revogar tokens do Telegram;
2. trocar a senha do Instagram;
3. invalidar sessões antigas;
4. revisar o histórico do repositório antes de divulgar amplamente.

---

## Observações importantes

- O projeto foi estruturado para **rodar localmente**.
- Não é recomendado expor o Flask diretamente na internet sem autenticação, autorização e revisão de segurança.
- A automação com Instagram depende de comportamento responsável para reduzir risco de bloqueios.
- O ComfyUI é opcional em fluxos que não precisam de geração visual por IA.

---

## Situação atual do projeto

Atualmente o projeto entrega:

- geração local de ideias e posts;
- integração com modelos do Ollama;
- suporte a geração visual por ComfyUI;
- biblioteca local de conteúdos;
- publicação manual ou assistida;
- revisão via Telegram;
- publicação em conta configurada do Instagram.

---

## Roadmap sugerido

Possíveis próximas evoluções:

- suporte a múltiplas contas com perfis separados;
- templates fixos e dinâmicos;
- dashboard com métricas e status das publicações;
- agendamento nativo de posts;
- exportação de relatórios;
- melhorias na experiência de onboarding;
- empacotamento simplificado para instalação.

---

## Contribuição

Contribuições são bem-vindas para melhorias de interface, automação, integração com IA local e segurança do fluxo.

Se for contribuir:

1. faça um fork;
2. crie uma branch;
3. implemente sua melhoria;
4. abra um pull request.

---

## Licença

Este projeto ainda não possui uma licença definida no repositório.

Se desejar abrir contribuições públicas de forma mais clara, vale adicionar uma licença como **MIT** ou **Apache-2.0**.

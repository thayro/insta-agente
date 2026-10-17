# Insta-Agente / StudioLab

Aplicação local para criar cards para redes sociais com Ollama, Pillow e, opcionalmente, ComfyUI; gerenciamento de posts via Flask, revisão pelo Telegram e publicação no Instagram via Instagrapi.

## Requisitos

- Windows, Python 3.13, Git
- Ollama instalado e pelo menos um modelo baixado
- ComfyUI instalado separadamente para geração de fundos com IA (opcional para fluxos que não dependam dele)
- Checkpoint compatível instalado no ComfyUI, caso use esse recurso
- Acesso à Internet para integrar Telegram e Instagram

## Instalação (Windows)

1. Clone o repositório e entre na pasta do projeto.
2. Execute `instalar_portal.bat` para criar `.venv_portal` e instalar `requirements_portal.txt`.
3. Configure o Ollama e o ComfyUI na sua máquina. O inicializador tenta encontrar os executáveis/instalação existente; valide os caminhos locais no `.bat`.
4. Execute `iniciar_portal.bat`.
5. Acesse `http://127.0.0.1:5005/` e configure os modelos e integrações pelo painel.

O Ollama é esperado localmente em `127.0.0.1:11434`, o ComfyUI em `127.0.0.1:8188` e o portal Flask em `127.0.0.1:5005`.

## Estrutura

- `app.py`: Flask / APIs / histórico e tarefas de criação
- `gerar_card.py`: criação de conteúdo e composição dos cards
- `comfyui_client.py`: cliente e geração via ComfyUI
- `integracoes.py`: Telegram e Instagram
- `templates/`, `static/`: interface web
- `instalar_portal.bat`, `iniciar_portal.bat`: instalação e inicialização no Windows
- `data/*.example.json`: exemplos sem dados privados

## Segurança

**Nunca publique** `data/config_integracoes.json`, `data/instagram_session.json`, tokens, senhas, logs, posts privados ou `.venv_portal/`.

As configurações reais são geradas localmente quando necessário; os arquivos `.example.json` são apenas exemplos. A aplicação foi pensada para uso **local**. Não exponha o Flask na Internet sem autenticação, autorização, proteção CSRF e revisão das rotas de publicação/configuração.

Caso a cópia original tenha sido disponibilizada publicamente, revogue os tokens de Telegram, troque a senha do Instagram e invalide sessões antigas antes de reutilizar as integrações.

## Publicar no GitHub

```bash
git init
git add .
git status
git commit -m "Initial commit: Insta-Agente StudioLab"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main
```

Crie o repositório vazio no GitHub antes do `git remote add origin`. Verifique `git status` e `git diff --cached --name-only` para garantir que nada privado será publicado.

## Observações

- Requer teste no Windows com os serviços locais; a análise estática não substitui um teste de instalação/execução.
- `instalar_portal.bat` foi ajustado para **não** modificar o Python global com a dependência de outro software (IQ Option).
- Evite publicar o ZIP original, pois ele contém sessões e credenciais reais.

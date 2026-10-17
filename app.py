from __future__ import annotations

import io
import os
import sys


def _configurar_utf8_windows():
    """Forca UTF-8 no Windows e evita UnicodeEncodeError/charmap em logs redirecionados."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8:replace")
    for nome in ("stdout", "stderr"):
        stream = getattr(sys, nome, None)
        if stream is None:
            continue
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
                continue
            except Exception:
                pass
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            try:
                setattr(sys, nome, io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True))
            except Exception:
                pass


_configurar_utf8_windows()

from datetime import datetime, timedelta
from pathlib import Path
import json
import logging
import threading
import time
import uuid
import webbrowser

from flask import Flask, jsonify, render_template, request, send_from_directory
from PIL import Image, ImageOps
import ollama

from comfyui_client import listar_checkpoints, obter_system_stats, servidor_disponivel
from gerar_card import (
    BASE_DIR,
    CHECKPOINT_PADRAO,
    MODELO,
    POSTS_DIR,
    SITE_OFICIAL,
    TEMPLATES,
    gerar_post_completo,
)
from integracoes import IntegracoesService

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024


class _PollingAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        mensagem = record.getMessage()
        if '"GET /api/status HTTP/' in mensagem:
            return False
        if '"GET /api/posts/' in mensagem and '/status HTTP/' in mensagem:
            return False
        return True


def _configurar_logs_http():
    logger = logging.getLogger("werkzeug")
    if not any(isinstance(f, _PollingAccessFilter) for f in logger.filters):
        logger.addFilter(_PollingAccessFilter())

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
GENERATION_LOCK = threading.Lock()
ACTIVE_JOB_ID: str | None = None

INTEGRACOES = IntegracoesService(BASE_DIR, POSTS_DIR, "")


def _current_context_id() -> str:
    """Usa a conta do Instagram atual como namespace editorial do histórico."""
    try:
        cfg = INTEGRACOES.public_config()
        username = str((cfg.get("instagram") or {}).get("username") or "").strip().lstrip("@").lower()
        return username
    except Exception:
        return ""

def _active_client_label() -> str:
    try:
        cfg = INTEGRACOES.public_config()
        username = str((cfg.get("instagram") or {}).get("username") or "").strip().lstrip("@")
        if username:
            return f"@{username}"
    except Exception:
        pass
    return "Nenhum Instagram ativo"

SETTINGS_PATH = BASE_DIR / "data" / "studiolab_settings.json"
SETTINGS_LOCK = threading.Lock()


def _ollama_models() -> list[str]:
    resposta = ollama.list()
    models = getattr(resposta, "models", None)
    if models is None and isinstance(resposta, dict):
        models = resposta.get("models", [])

    nomes: list[str] = []
    for model in models or []:
        nome = getattr(model, "model", None) or getattr(model, "name", None)
        if not nome and isinstance(model, dict):
            nome = model.get("model") or model.get("name")
        if nome:
            nome = str(nome)
            if nome not in nomes:
                nomes.append(nome)
    return nomes


def _load_settings() -> dict:
    with SETTINGS_LOCK:
        try:
            dados = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                return dados
        except Exception:
            pass
    return {}


def _save_settings(values: dict) -> dict:
    with SETTINGS_LOCK:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        atual = {}
        try:
            atual = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if not isinstance(atual, dict):
                atual = {}
        except Exception:
            atual = {}
        atual.update(values)
        SETTINGS_PATH.write_text(json.dumps(atual, indent=2, ensure_ascii=False), encoding="utf-8")
        return atual


def _selected_model(models: list[str] | None = None) -> str:
    modelos = models if models is not None else []
    salvo = str(_load_settings().get("ollama_model", "")).strip()
    if salvo and (not modelos or salvo in modelos):
        return salvo
    if MODELO in modelos:
        return MODELO
    if modelos:
        return modelos[0]
    return salvo or MODELO


def _selected_checkpoint(checkpoints: list[str] | None = None) -> str:
    cps = checkpoints if checkpoints is not None else []
    salvo = str(_load_settings().get("comfyui_checkpoint", "")).strip()
    if salvo and (not cps or salvo in cps):
        return salvo
    if CHECKPOINT_PADRAO in cps:
        return CHECKPOINT_PADRAO
    if cps:
        return cps[0]
    return salvo or CHECKPOINT_PADRAO


def _set_job(job_id: str, **values):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(values)
            JOBS[job_id]["updated_at"] = datetime.now().isoformat(timespec="seconds")


def _criar_pasta_post_manual() -> Path:
    """Cria pasta YYYY-MM-DD/HHMMSS compatível com o post_ref existente."""
    agora = datetime.now()
    for deslocamento in range(0, 120):
        momento = agora + timedelta(seconds=deslocamento)
        pasta = POSTS_DIR / momento.strftime("%Y-%m-%d") / momento.strftime("%H%M%S")
        try:
            pasta.mkdir(parents=True, exist_ok=False)
            return pasta
        except FileExistsError:
            continue
    raise RuntimeError("Não foi possível reservar uma pasta para o post manual.")


def _titulo_manual(caption: str, titulo: str = "") -> str:
    titulo = str(titulo or "").strip()
    if titulo:
        return titulo[:90]
    primeira = next((linha.strip() for linha in str(caption or "").splitlines() if linha.strip()), "")
    if primeira:
        return primeira[:90]
    return "Post manual"


def _salvar_imagens_manuais(arquivos, pasta_post: Path) -> list[str]:
    nomes: list[str] = []
    for indice, arquivo in enumerate(arquivos, start=1):
        try:
            imagem = Image.open(arquivo.stream)
            imagem = ImageOps.exif_transpose(imagem).convert("RGB")
            # Proteção para uploads muito grandes sem alterar a proporção.
            if max(imagem.size) > 4096:
                imagem.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            nome = f"media_{indice:02d}.jpg"
            imagem.save(pasta_post / nome, format="JPEG", quality=95, optimize=True)
            nomes.append(nome)
            if indice == 1:
                imagem.save(pasta_post / "card.png", format="PNG", optimize=True)
        except Exception as exc:
            raise ValueError(f"A imagem {indice} não pôde ser processada: {exc}") from exc
    return nomes


def _path_to_post_url(path_value: str | None) -> str | None:
    if not path_value:
        return None
    try:
        rel = Path(path_value).resolve().relative_to(POSTS_DIR.resolve())
    except Exception:
        return None
    return "/posts/" + rel.as_posix()


def _ollama_status() -> dict:
    try:
        nomes = _ollama_models()
        selecionado = _selected_model(nomes)
        modelo_ok = selecionado in nomes
        return {
            "ok": True,
            "model_ok": modelo_ok,
            "model": selecionado,
            "models": nomes,
            "count": len(nomes),
        }
    except Exception as exc:
        selecionado = _selected_model([])
        return {
            "ok": False,
            "model_ok": False,
            "model": selecionado,
            "models": [],
            "count": 0,
            "error": str(exc),
        }


def _comfyui_status() -> dict:
    if not servidor_disponivel():
        return {"ok": False, "checkpoints": [], "device": "indisponível", "selected_checkpoint": _selected_checkpoint([])}

    checkpoints = []
    device = "desconhecido"
    memory = None
    try:
        checkpoints = listar_checkpoints()
    except Exception:
        pass
    try:
        stats = obter_system_stats()
        devices = stats.get("devices", []) if isinstance(stats, dict) else []
        if devices:
            dev = devices[0]
            device = dev.get("name") or dev.get("type") or "desconhecido"
            vram = dev.get("vram_total")
            if isinstance(vram, (int, float)) and vram > 0:
                memory = round(vram / (1024**3), 1)
    except Exception:
        pass

    return {
        "ok": True,
        "checkpoints": checkpoints,
        "checkpoint_ok": bool(checkpoints),
        "preferred_checkpoint": _selected_checkpoint(checkpoints),
        "selected_checkpoint": _selected_checkpoint(checkpoints),
        "device": device,
        "memory_gb": memory,
        "count": len(checkpoints),
    }


def _post_publication_view(data: dict) -> dict:
    pub = data.get("publicacao")
    if not isinstance(pub, dict):
        pub = {}
    return {
        "status": pub.get("status") or "rascunho",
        "updated_at": pub.get("atualizado_em"),
        "sent_at": pub.get("telegram_enviado_em"),
        "approved_at": pub.get("aprovado_em"),
        "rejected_at": pub.get("rejeitado_em"),
        "published_at": pub.get("publicado_em"),
        "validated_by": pub.get("validado_por"),
        "instagram_url": pub.get("instagram_url"),
        "error": pub.get("erro"),
    }


def _historico(limit: int = 12) -> list[dict]:
    if not POSTS_DIR.exists():
        return []

    arquivos = sorted(
        POSTS_DIR.rglob("post.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]

    itens = []
    for arquivo in arquivos:
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except Exception:
            continue

        pasta = arquivo.parent
        card = pasta / "card.png"
        fundo = pasta / "fundo.png"
        rel = pasta.resolve().relative_to(POSTS_DIR.resolve()).as_posix()
        post_ref = INTEGRACOES.post_ref(pasta)
        itens.append(
            {
                "id": rel.replace("/", "-"),
                "post_ref": post_ref,
                "created_at": dados.get("criado_em"),
                "topic": dados.get("topico"),
                "badge": dados.get("selo_visual"),
                "title": dados.get("titulo"),
                "body": dados.get("corpo"),
                "highlight": dados.get("destaque"),
                "caption": dados.get("legenda_instagram"),
                "template": dados.get("template_usado"),
                "icon": dados.get("icone_usado"),
                "checkpoint": dados.get("checkpoint_usado"),
                "model": dados.get("modelo_ia") or ("manual" if dados.get("origem") == "manual_upload" else MODELO),
                "source": dados.get("origem") or "ia",
                "media_count": len((dados.get("arquivos") or {}).get("midias") or []),
                "context_id": dados.get("contexto_id") or "",
                "client": dados.get("cliente") or dados.get("marca_visual") or "",
                "instagram": dados.get("instagram") or (("@" + str(dados.get("contexto_id") or "").lstrip("@")) if dados.get("contexto_id") else ""),
                "brand": dados.get("marca_visual") or "",
                "briefing_used": bool(dados.get("briefing_usado")),
                "publication": _post_publication_view(dados),
                "card_url": f"/posts/{rel}/card.png" if card.exists() else None,
                "background_url": f"/posts/{rel}/fundo.png" if fundo.exists() else None,
            }
        )
    return itens


def _worker(job_id: str, options: dict):
    global ACTIVE_JOB_ID

    def progress(percent: int, stage: str, message: str):
        _set_job(
            job_id,
            status="running",
            progress=percent,
            stage=stage,
            message=message,
        )

    try:
        with GENERATION_LOCK:
            resultado = gerar_post_completo(
                orientacao=options.get("orientation", ""),
                template_preferido=options.get("template", "auto"),
                usar_comfyui=bool(options.get("use_comfyui", True)),
                modelo_ia=options.get("model") or _selected_model(),
                checkpoint_preferido=options.get("checkpoint") or _selected_checkpoint(),
                contexto_id=options.get("context_id") or _current_context_id(),
                progress_callback=progress,
            )

        pasta_post = Path(resultado["pasta_post"])
        _set_job(
            job_id,
            status="running",
            progress=100,
            stage="VALIDAÇÃO",
            message="Preparando fluxo de aprovação",
        )
        publication = INTEGRACOES.after_post_generated(pasta_post)

        conteudo = resultado["conteudo"]
        _set_job(
            job_id,
            status="done",
            progress=100,
            stage="CONCLUÍDO",
            message="Post pronto",
            result={
                "post_ref": INTEGRACOES.post_ref(pasta_post),
                "topic": conteudo.get("topico"),
                "badge": conteudo.get("selo_visual"),
                "title": conteudo.get("titulo"),
                "body": conteudo.get("corpo"),
                "highlight": conteudo.get("destaque"),
                "caption": conteudo.get("legenda_instagram"),
                "image_prompt": conteudo.get("prompt_imagem"),
                "final_image_prompt": resultado.get("prompt_visual_final"),
                "template": resultado.get("template_usado"),
                "icon": resultado.get("icone_usado"),
                "checkpoint": resultado.get("checkpoint_usado"),
                "model": resultado.get("modelo_ia") or options.get("model") or _selected_model(),
                "context_id": conteudo.get("contexto_id") or options.get("context_id") or "",
                "client": conteudo.get("marca_visual") or (("@" + str(conteudo.get("contexto_id") or options.get("context_id") or "").lstrip("@")) if (conteudo.get("contexto_id") or options.get("context_id")) else "StudioLab"),
                "instagram": (("@" + str(conteudo.get("contexto_id") or options.get("context_id") or "").lstrip("@")) if (conteudo.get("contexto_id") or options.get("context_id")) else ""),
                "briefing_used": bool(conteudo.get("briefing_usado")),
                "brand": conteudo.get("marca_visual"),
                "comfyui_warning": resultado.get("comfyui_erro"),
                "publication": {
                    "status": publication.get("status") or "rascunho",
                    "instagram_url": publication.get("instagram_url"),
                    "error": publication.get("erro"),
                    "validated_by": publication.get("validado_por"),
                },
                "card_url": _path_to_post_url(resultado.get("card_path")),
                "background_url": _path_to_post_url(resultado.get("fundo_path")),
            },
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="error",
            stage="ERRO",
            message=str(exc),
            error=str(exc),
        )
    finally:
        with JOBS_LOCK:
            if ACTIVE_JOB_ID == job_id:
                ACTIVE_JOB_ID = None


@app.get("/")
def index():
    return render_template(
        "index.html",
        site=_active_client_label(),
        active_client=_active_client_label(),
        model=_selected_model(),
        checkpoint=_selected_checkpoint(),
        templates=TEMPLATES,
    )


@app.get("/api/status")
def api_status():
    with JOBS_LOCK:
        active_job = ACTIVE_JOB_ID
    integrations = INTEGRACOES.public_config()
    return jsonify(
        {
            "ollama": _ollama_status(),
            "comfyui": _comfyui_status(),
            "integrations": integrations,
            "active_job": active_job,
            "site": _active_client_label(),
            "client_active": _active_client_label(),
            "context": {"id": _current_context_id()},
        }
    )


@app.get("/api/ollama/models")
def api_ollama_models():
    try:
        modelos = _ollama_models()
        selecionado = _selected_model(modelos)
        return jsonify({"models": modelos, "selected": selecionado, "count": len(modelos)})
    except Exception as exc:
        return jsonify({"models": [], "selected": _selected_model([]), "count": 0, "error": str(exc)}), 503


@app.post("/api/settings/model")
def api_settings_model():
    payload = request.get_json(silent=True) or {}
    model = str(payload.get("model", "")).strip()
    if not model:
        return jsonify({"error": "Informe o modelo."}), 400
    try:
        modelos = _ollama_models()
    except Exception as exc:
        return jsonify({"error": f"Não foi possível consultar o Ollama: {exc}"}), 503
    if model not in modelos:
        return jsonify({"error": "O modelo selecionado não está instalado no Ollama."}), 400
    _save_settings({"ollama_model": model})
    return jsonify({"ok": True, "model": model, "models": modelos})


@app.get("/api/comfyui/checkpoints")
def api_comfyui_checkpoints():
    try:
        checkpoints = listar_checkpoints()
        selecionado = _selected_checkpoint(checkpoints)
        return jsonify({"checkpoints": checkpoints, "selected": selecionado, "count": len(checkpoints)})
    except Exception as exc:
        return jsonify({"checkpoints": [], "selected": _selected_checkpoint([]), "count": 0, "error": str(exc)}), 503


@app.post("/api/settings/checkpoint")
def api_settings_checkpoint():
    payload = request.get_json(silent=True) or {}
    checkpoint = str(payload.get("checkpoint", "")).strip()
    if not checkpoint:
        return jsonify({"error": "Informe o checkpoint."}), 400
    try:
        checkpoints = listar_checkpoints()
    except Exception as exc:
        return jsonify({"error": f"Não foi possível consultar o ComfyUI: {exc}"}), 503
    if checkpoint not in checkpoints:
        return jsonify({"error": "O checkpoint selecionado não está disponível no ComfyUI."}), 400
    _save_settings({"comfyui_checkpoint": checkpoint})
    return jsonify({"ok": True, "checkpoint": checkpoint, "checkpoints": checkpoints})


@app.get("/api/history")
def api_history():
    try:
        limit = max(1, min(30, int(request.args.get("limit", 12))))
    except ValueError:
        limit = 12
    return jsonify({"items": _historico(limit)})


@app.post("/api/manual-post")
def api_manual_post():
    caption = str(request.form.get("caption", "")).strip()
    titulo = str(request.form.get("title", "")).strip()
    imagens = [f for f in request.files.getlist("images") if f and f.filename]

    if not imagens:
        return jsonify({"error": "Selecione pelo menos uma imagem."}), 400
    if len(imagens) > 10:
        return jsonify({"error": "Envie no máximo 10 imagens por publicação."}), 400
    if not caption:
        return jsonify({"error": "Informe a descrição/legenda do post."}), 400
    if len(caption) > 2200:
        return jsonify({"error": "A legenda pode ter no máximo 2200 caracteres."}), 400

    pasta_post = None
    try:
        pasta_post = _criar_pasta_post_manual()
        midias = _salvar_imagens_manuais(imagens, pasta_post)
        titulo_final = _titulo_manual(caption, titulo)
        resumo = caption.replace("\r", " ").replace("\n", " ").strip()
        if len(resumo) > 240:
            resumo = resumo[:237].rstrip() + "..."

        contexto_id = _current_context_id()
        instagram = f"@{contexto_id}" if contexto_id else ""
        cliente = instagram or "StudioLab"
        dados = {
            "criado_em": datetime.now().isoformat(timespec="seconds"),
            "cliente": cliente,
            "instagram": instagram,
            "site_oficial": "",
            "contexto_id": contexto_id,
            "briefing_usado": "",
            "marca_visual": cliente,
            "rodape_visual": instagram,
            "origem": "manual_upload",
            "modelo_ia": None,
            "topico": "Post manual",
            "selo_visual": "UPLOAD MANUAL",
            "titulo": titulo_final,
            "corpo": resumo,
            "destaque": "",
            "legenda_instagram": caption,
            "prompt_imagem_original": None,
            "prompt_imagem_final": None,
            "checkpoint_usado": None,
            "template_usado": "manual_upload",
            "layout_ia": None,
            "icone_usado": None,
            "arquivos": {
                "card": "card.png",
                "fundo": None,
                "midias": midias,
            },
        }
        (pasta_post / "post.json").write_text(
            json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        publication_raw = INTEGRACOES.after_post_generated(pasta_post)
        dados["publicacao"] = publication_raw
        publication = _post_publication_view(dados)
        rel = pasta_post.resolve().relative_to(POSTS_DIR.resolve()).as_posix()
        result = {
            "post_ref": INTEGRACOES.post_ref(pasta_post),
            "topic": "Post manual",
            "badge": "UPLOAD MANUAL",
            "title": titulo_final,
            "body": resumo,
            "highlight": f"{len(midias)} imagem" + ("" if len(midias) == 1 else "s"),
            "caption": caption,
            "template": "manual_upload",
            "icon": None,
            "checkpoint": None,
            "model": None,
            "source": "manual_upload",
            "client": cliente,
            "instagram": instagram,
            "media_count": len(midias),
            "publication": publication,
            "card_url": f"/posts/{rel}/card.png",
            "background_url": None,
        }
        return jsonify({"ok": True, "result": result}), 201
    except Exception as exc:
        if pasta_post and pasta_post.exists():
            try:
                import shutil
                shutil.rmtree(pasta_post, ignore_errors=True)
            except Exception:
                pass
        return jsonify({"error": str(exc)}), 400


@app.post("/api/generate")
def api_generate():
    global ACTIVE_JOB_ID
    payload = request.get_json(silent=True) or {}

    orientation = str(payload.get("orientation", "")).strip()[:1200]
    context_id = _current_context_id()
    template = str(payload.get("template", "auto")).strip()
    if template != "auto" and template not in TEMPLATES:
        return jsonify({"error": "Template inválido."}), 400

    use_comfyui = bool(payload.get("use_comfyui", True))

    try:
        modelos_disponiveis = _ollama_models()
    except Exception as exc:
        return jsonify({"error": f"Não foi possível consultar os modelos do Ollama: {exc}"}), 503

    model = str(payload.get("model") or _selected_model(modelos_disponiveis)).strip()
    if not model or model not in modelos_disponiveis:
        return jsonify({"error": "Modelo do Ollama inválido ou não instalado."}), 400

    checkpoint = ""
    if use_comfyui:
        try:
            checkpoints_disponiveis = listar_checkpoints()
        except Exception as exc:
            return jsonify({"error": f"Não foi possível consultar os checkpoints do ComfyUI: {exc}"}), 503
        checkpoint = str(payload.get("checkpoint") or _selected_checkpoint(checkpoints_disponiveis)).strip()
        if not checkpoint or checkpoint not in checkpoints_disponiveis:
            return jsonify({"error": "Checkpoint do ComfyUI inválido ou não encontrado."}), 400
        _save_settings({"ollama_model": model, "comfyui_checkpoint": checkpoint})
    else:
        checkpoint = str(payload.get("checkpoint") or _selected_checkpoint([])).strip()
        _save_settings({"ollama_model": model})

    with JOBS_LOCK:
        if ACTIVE_JOB_ID and ACTIVE_JOB_ID in JOBS:
            active = JOBS[ACTIVE_JOB_ID]
            if active.get("status") in {"queued", "running"}:
                return jsonify(
                    {
                        "error": "Já existe uma geração em andamento.",
                        "job_id": ACTIVE_JOB_ID,
                    }
                ), 409

        job_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat(timespec="seconds")
        JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "stage": "FILA",
            "message": "Aguardando início",
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": None,
        }
        ACTIVE_JOB_ID = job_id

    thread = threading.Thread(
        target=_worker,
        args=(job_id, {"orientation": orientation, "template": template, "use_comfyui": use_comfyui, "model": model, "checkpoint": checkpoint, "context_id": context_id}),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id}), 202


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Geração não encontrada."}), 404
        return jsonify(dict(job))


@app.get("/posts/<path:filename>")
def posts_file(filename: str):
    return send_from_directory(POSTS_DIR, filename)


@app.get("/api/latest")
def api_latest():
    itens = _historico(1)
    return jsonify({"item": itens[0] if itens else None})


# ----------------------------------------------------------------------
# Integrações Telegram + Instagram
# ----------------------------------------------------------------------
@app.get("/api/integrations/config")
def api_integrations_config():
    return jsonify(INTEGRACOES.public_config())


@app.post("/api/integrations/config")
def api_integrations_save():
    payload = request.get_json(silent=True) or {}
    try:
        config = INTEGRACOES.save_config(payload)
        return jsonify({"ok": True, "config": config})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/integrations/test/telegram")
def api_integrations_test_telegram():
    try:
        return jsonify(INTEGRACOES.test_telegram())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/integrations/test/instagram")
def api_integrations_test_instagram():
    try:
        return jsonify(INTEGRACOES.test_instagram())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

@app.post("/api/integrations/switch/instagram")
def api_integrations_switch_instagram():
    try:
        payload = request.get_json(silent=True) or {}
        return jsonify(INTEGRACOES.switch_instagram_account(payload))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/posts/<post_ref>/status")
def api_post_status(post_ref: str):
    try:
        post_dir = INTEGRACOES.resolve_post_ref(post_ref)
        data = json.loads((post_dir / "post.json").read_text(encoding="utf-8"))
        return jsonify({"publication": _post_publication_view(data)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/api/posts/<post_ref>/send-review")
def api_send_review(post_ref: str):
    try:
        post_dir = INTEGRACOES.resolve_post_ref(post_ref)
        publication = INTEGRACOES.send_for_review(post_dir)
        return jsonify({"ok": True, "publication": publication})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/posts/<post_ref>/publish")
def api_publish(post_ref: str):
    try:
        post_dir = INTEGRACOES.resolve_post_ref(post_ref)
        current = INTEGRACOES.publication_status(post_dir)
        if current.get("status") not in {"aprovado", "erro_publicacao", "publicando"}:
            return jsonify({"error": "O post precisa estar aprovado antes da publicação."}), 409
        if current.get("status") == "publicando":
            return jsonify({"ok": True, "publication": current, "message": "Publicação já em andamento."})

        publication = INTEGRACOES.update_publication(
            post_dir,
            status="publicando",
            erro=None,
        )
        threading.Thread(
            target=INTEGRACOES.publish_instagram,
            args=(post_dir,),
            daemon=True,
            name=f"ig-manual-{post_ref}",
        ).start()
        return jsonify({"ok": True, "publication": publication})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


def _open_browser():
    time.sleep(1.1)
    webbrowser.open("http://127.0.0.1:5005/")


if __name__ == "__main__":
    _configurar_logs_http()
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    INTEGRACOES.start_telegram_poller()
    print("=" * 68)
    print("  STUDIOLAB — CREATIVE AI WORKSPACE")
    print("  http://127.0.0.1:5005/")
    print("  IA livre · Telegram approval · Instagram publishing")
    print("=" * 68)
    threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=5005, debug=False, threaded=True)

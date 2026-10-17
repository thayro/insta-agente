from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
import uuid
from typing import Callable

COMFYUI_URL = "http://127.0.0.1:8188"
ProgressCallback = Callable[[int, str], None]


def _get_json(endpoint: str, timeout: int = 30):
    url = COMFYUI_URL.rstrip("/") + endpoint
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Insta-Agente/2.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(endpoint: str, payload: dict, timeout: int = 60):
    url = COMFYUI_URL.rstrip("/") + endpoint
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Insta-Agente/2.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def servidor_disponivel() -> bool:
    try:
        _get_json("/system_stats", timeout=5)
        return True
    except Exception:
        return False


def obter_system_stats() -> dict:
    return _get_json("/system_stats", timeout=5)


def listar_checkpoints():
    info = _get_json("/object_info/CheckpointLoaderSimple")
    node = info.get("CheckpointLoaderSimple", {})
    input_info = node.get("input", {}).get("required", {}).get("ckpt_name", [])

    checkpoints = []
    if isinstance(input_info, list) and input_info:
        primeiro = input_info[0]
        if isinstance(primeiro, list):
            checkpoints = primeiro

    return checkpoints


def _montar_workflow(prompt: str, ckpt_name: str, width: int = 512, height: int = 768):
    return {
        "1": {
            "inputs": {"ckpt_name": ckpt_name},
            "class_type": "CheckpointLoaderSimple",
        },
        "2": {
            "inputs": {"text": prompt, "clip": ["1", 1]},
            "class_type": "CLIPTextEncode",
        },
        "3": {
            "inputs": {
                "text": (
                    "low quality, blurry, distorted, bad anatomy, duplicated objects, "
                    "cropped, text, watermark, logo, letters, captions, signboards, labels"
                ),
                "clip": ["1", 1],
            },
            "class_type": "CLIPTextEncode",
        },
        "4": {
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptyLatentImage",
        },
        "5": {
            "inputs": {
                "seed": int(time.time() * 1000) % 2147483647,
                "steps": 15,
                "cfg": 7,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
            "class_type": "KSampler",
        },
        "6": {
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            "class_type": "VAEDecode",
        },
        "7": {
            "inputs": {
                "filename_prefix": "insta_agente",
                "images": ["6", 0],
            },
            "class_type": "SaveImage",
        },
    }


def _mostrar_progresso(percentual: int, etapa: str = ""):
    percentual = max(0, min(100, int(percentual)))
    barra_len = 30
    preenchido = int(barra_len * percentual / 100)
    barra = "#" * preenchido + "-" * (barra_len - preenchido)
    etapa_txt = f" · {etapa}" if etapa else ""
    sys.stdout.write(f"\rComfyUI [{barra}] {percentual:3d}%{etapa_txt:<42}")
    sys.stdout.flush()
    if percentual >= 100:
        sys.stdout.write("\n")
        sys.stdout.flush()


def _emitir_progresso(percentual: int, etapa: str, callback: ProgressCallback | None):
    _mostrar_progresso(percentual, etapa)
    if callback:
        try:
            callback(max(0, min(100, int(percentual))), etapa)
        except Exception:
            pass


def _etapa_por_no(node_id):
    etapas = {
        "1": (5, "carregando checkpoint"),
        "2": (12, "processando prompt"),
        "3": (16, "processando prompt negativo"),
        "4": (20, "preparando imagem"),
        "5": (22, "gerando imagem"),
        "6": (92, "decodificando imagem"),
        "7": (98, "salvando imagem"),
    }
    return etapas.get(str(node_id), (2, "processando"))


def _baixar_imagem_do_historico(prompt_id: str, output_path: str):
    historico = _get_json(f"/history/{prompt_id}", timeout=60)
    if prompt_id not in historico:
        return None

    dados_prompt = historico[prompt_id]
    status = dados_prompt.get("status", {})
    status_str = str(status).lower()
    if "error" in status_str:
        raise RuntimeError(f"O ComfyUI informou erro na execução: {status}")

    outputs = dados_prompt.get("outputs", {})
    for node_data in outputs.values():
        imagens = node_data.get("images", [])
        if not imagens:
            continue

        img = imagens[0]
        filename = img["filename"]
        subfolder = img.get("subfolder", "")
        img_type = img.get("type", "output")

        query = urllib.parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": img_type}
        )
        url_img = COMFYUI_URL.rstrip("/") + "/view?" + query

        with urllib.request.urlopen(url_img, timeout=120) as resp:
            conteudo = resp.read()

        with open(output_path, "wb") as f:
            f.write(conteudo)

        return output_path

    return None


def _aguardar_com_websocket(
    prompt_id: str,
    client_id: str,
    output_path: str,
    timeout_total: int,
    progress_callback: ProgressCallback | None = None,
):
    try:
        import websocket
    except ImportError:
        return None

    ws_url = COMFYUI_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = ws_url.rstrip("/") + f"/ws?clientId={urllib.parse.quote(client_id)}"

    ws = websocket.create_connection(ws_url, timeout=5)
    ws.settimeout(2.0)
    inicio = time.time()
    ultimo_pct = 1
    _emitir_progresso(1, "na fila", progress_callback)

    try:
        while True:
            if time.time() - inicio > timeout_total:
                raise TimeoutError("Tempo excedido aguardando geração da imagem no ComfyUI.")

            try:
                mensagem = ws.recv()
            except Exception as exc:
                if exc.__class__.__name__ not in {"WebSocketTimeoutException", "TimeoutError"}:
                    raise
                pronto = _baixar_imagem_do_historico(prompt_id, output_path)
                if pronto:
                    _emitir_progresso(100, "concluído", progress_callback)
                    return pronto
                _emitir_progresso(ultimo_pct, "processando", progress_callback)
                continue

            if not isinstance(mensagem, str):
                continue

            try:
                evento = json.loads(mensagem)
            except json.JSONDecodeError:
                continue

            tipo = evento.get("type")
            dados = evento.get("data", {}) or {}

            evento_prompt_id = dados.get("prompt_id")
            if evento_prompt_id and evento_prompt_id != prompt_id:
                continue

            if tipo == "execution_start":
                ultimo_pct = max(ultimo_pct, 2)
                _emitir_progresso(ultimo_pct, "iniciando", progress_callback)

            elif tipo == "executing":
                node = dados.get("node")
                if node is None:
                    pronto = _baixar_imagem_do_historico(prompt_id, output_path)
                    if pronto:
                        _emitir_progresso(100, "concluído", progress_callback)
                        return pronto
                else:
                    pct, etapa = _etapa_por_no(node)
                    ultimo_pct = max(ultimo_pct, pct)
                    _emitir_progresso(ultimo_pct, etapa, progress_callback)

            elif tipo == "progress":
                valor = dados.get("value", 0)
                maximo = dados.get("max", 0)
                if maximo:
                    fracao = max(0.0, min(1.0, float(valor) / float(maximo)))
                    pct = 22 + int(fracao * 68)
                    ultimo_pct = max(ultimo_pct, pct)
                    _emitir_progresso(
                        ultimo_pct,
                        f"gerando imagem {valor}/{maximo}",
                        progress_callback,
                    )

            elif tipo in {"executed", "execution_cached"}:
                ultimo_pct = max(ultimo_pct, 96)
                _emitir_progresso(ultimo_pct, "finalizando", progress_callback)

            elif tipo in {"execution_error", "execution_interrupted"}:
                mensagem_erro = dados.get("exception_message") or dados.get("message") or tipo
                raise RuntimeError(f"ComfyUI interrompeu a geração: {mensagem_erro}")

            pronto = _baixar_imagem_do_historico(prompt_id, output_path)
            if pronto:
                _emitir_progresso(100, "concluído", progress_callback)
                return pronto
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _aguardar_com_polling(
    prompt_id: str,
    output_path: str,
    timeout_total: int,
    progress_callback: ProgressCallback | None = None,
):
    inicio = time.time()
    ultimo_pct = 2
    _emitir_progresso(ultimo_pct, "processando", progress_callback)

    while True:
        decorrido = time.time() - inicio
        if decorrido > timeout_total:
            raise TimeoutError("Tempo excedido aguardando geração da imagem no ComfyUI.")

        pronto = _baixar_imagem_do_historico(prompt_id, output_path)
        if pronto:
            _emitir_progresso(100, "concluído", progress_callback)
            return pronto

        estimado = min(90, 2 + int(decorrido / max(timeout_total, 1) * 88))
        ultimo_pct = max(ultimo_pct, estimado)
        _emitir_progresso(ultimo_pct, f"processando · {int(decorrido)}s", progress_callback)
        time.sleep(2)


def gerar_imagem(
    prompt: str,
    output_path: str,
    ckpt_name: str | None = None,
    timeout_total: int = 900,
    width: int = 512,
    height: int = 768,
    progress_callback: ProgressCallback | None = None,
):
    if not servidor_disponivel():
        raise RuntimeError("ComfyUI não está acessível em http://127.0.0.1:8188")

    checkpoints = listar_checkpoints()
    if not checkpoints:
        raise RuntimeError("Nenhum checkpoint encontrado no ComfyUI.")

    if not ckpt_name:
        ckpt_name = checkpoints[0]

    if ckpt_name not in checkpoints:
        raise RuntimeError(
            f"Checkpoint '{ckpt_name}' não encontrado. Disponíveis: {', '.join(checkpoints)}"
        )

    workflow = _montar_workflow(prompt, ckpt_name, width, height)

    client_id = str(uuid.uuid4())
    _emitir_progresso(0, "enviando para o ComfyUI", progress_callback)
    resposta = _post_json("/prompt", {"prompt": workflow, "client_id": client_id})
    prompt_id = resposta.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"Não foi possível obter prompt_id. Resposta: {resposta}")

    try:
        resultado = _aguardar_com_websocket(
            prompt_id,
            client_id,
            output_path,
            timeout_total,
            progress_callback,
        )
        if resultado:
            return resultado
    except ImportError:
        pass
    except Exception as exc:
        if isinstance(exc, (RuntimeError, TimeoutError)):
            raise

    return _aguardar_com_polling(
        prompt_id,
        output_path,
        timeout_total,
        progress_callback,
    )

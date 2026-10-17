from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import random
import re
import shutil
import sys
import textwrap


def _configurar_utf8_windows():
    """Evita UnicodeEncodeError/charmap em console e logs redirecionados no Windows."""
    if os.name != "nt":
        return
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for nome in ("stdout", "stderr"):
        stream = getattr(sys, nome, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_configurar_utf8_windows()

import ollama
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from comfyui_client import gerar_imagem, listar_checkpoints, servidor_disponivel

FONT_BOLD = "C:\\Windows\\Fonts\\arialbd.ttf"
FONT_REGULAR = "C:\\Windows\\Fonts\\arial.ttf"

COR_FUNDO = "#0F3D2E"
COR_DESTAQUE = "#8FD14F"
COR_DESTAQUE_2 = "#B7F171"
COR_TEXTO = "#FFFFFF"
COR_SECUNDARIA = "#D8EDC5"
COR_SOMBRA = (0, 0, 0)

MODELO = "qwen3:14b"
MAX_TOKENS_RESPOSTA = 650
CHECKPOINT_PADRAO = "v1-5-pruned-emaonly.safetensors"
SITE_OFICIAL = ""

BASE_DIR = Path(__file__).resolve().parent
POSTS_DIR = BASE_DIR / "posts"
ULTIMO_CARD_PATH = BASE_DIR / "card_teste.png"
ULTIMO_FUNDO_PATH = BASE_DIR / "fundo_gerado.png"

SYSTEM_PROMPT = """Você é um estrategista de conteúdo e diretor criativo para Instagram dentro do StudioLab.

A conta, o nicho, a marca, o público, o tom de voz e o assunto DEVEM ser definidos pelo briefing fornecido pelo usuário e pelo contexto da conta atual. Você NÃO deve assumir que o cliente é AgroConsulta BR, agronegócio, tecnologia, confeitaria ou qualquer outro nicho sem que isso esteja sustentado pelo briefing ou pelo histórico da MESMA conta.

REGRA DE PRIORIDADE: quando houver briefing, ele é a fonte principal e obrigatória desta geração. Siga-o fielmente. Não troque o nicho, não reutilize assuntos de outro cliente e não permita que histórico antigo contradiga o briefing. Se o briefing disser para não abordar determinado tema, respeite integralmente.

Quando não houver briefing, use apenas o histórico recente pertencente à conta atual para manter continuidade e evitar repetição. Se não houver histórico suficiente, produza conteúdo neutro e coerente com as poucas informações disponíveis, sem inventar uma marca ou nicho específico.

Crie conteúdo útil, natural, variado e adequado ao Instagram. Título curto, corpo enxuto para leitura no celular e uma legenda mais completa. O prompt visual deve representar diretamente o assunto e o nicho atuais.

Responda SOMENTE com JSON válido, sem markdown, sem crases, sem texto antes ou depois, exatamente neste formato:
{
  "marca_projeto": "nome da marca/projeto/cliente definido pelo briefing, ou vazio se não estiver claro",
  "topico": "tema do post, em poucas palavras",
  "selo_visual": "selo curto de 1 a 3 palavras",
  "titulo": "título curto, idealmente até 4 palavras",
  "corpo": "1-3 frases curtas e objetivas para o card",
  "destaque": "número, percentual, sigla ou palavra-chave curta",
  "legenda_instagram": "legenda completa, coerente com o briefing e com hashtags relevantes",
  "prompt_imagem": "em inglês, descreva uma cena vertical realista ou editorial diretamente ligada ao assunto e ao nicho atual, sem texto visível, logotipos ou marcas d'água"
}
"""

PROMPT_IMAGEM_REFORCO = (
    "vertical premium editorial photography for an Instagram card background, subject and visual language aligned with the current niche and topic, "
    "natural professional lighting, clean composition, generous negative space for text overlay, keep important subjects away from the text area, "
    "high realism, no text, no letters, no numbers, no signboards, no captions, no watermarks, no logos"
)

FALLBACK_PROMPT_IMAGEM = (
    "premium realistic editorial photograph directly related to the current topic and niche, vertical social media composition, "
    "professional lighting, clean negative space for graphic design, no text, no logos, no watermark"
)

TEMPLATE_DINAMICO = "ai_dynamic"
TEMPLATES_FIXOS = ["classic_left", "spotlight_card", "modern_split"]
TEMPLATES = TEMPLATES_FIXOS + [TEMPLATE_DINAMICO]


def print_progresso(atual: int, total: int, prefixo: str = ""):
    pct = min(100, int((atual / total) * 100)) if total else 100
    barra_len = 30
    preenchido = int(barra_len * pct / 100)
    barra = "#" * preenchido + "-" * (barra_len - preenchido)
    sys.stdout.write(f"\r{prefixo} [{barra}] {pct}%")
    sys.stdout.flush()
    if pct >= 100:
        sys.stdout.write("\n")
        sys.stdout.flush()


def listar_posts_recentes(limite: int = 8, contexto_id: str = "") -> list[dict]:
    if not POSTS_DIR.exists():
        return []

    contexto_id = str(contexto_id or "").strip().lower()
    arquivos = sorted(
        POSTS_DIR.rglob("post.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    historico: list[dict] = []
    for arquivo in arquivos:
        if len(historico) >= limite:
            break
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except Exception:
            continue

        contexto_post = str(dados.get("contexto_id") or "").strip().lower()
        if contexto_id and contexto_post != contexto_id:
            # Histórico de outra conta nunca entra no prompt atual.
            continue

        historico.append(
            {
                "topico": dados.get("topico", ""),
                "titulo": dados.get("titulo", ""),
                "corpo": dados.get("corpo", ""),
                "selo_visual": dados.get("selo_visual", ""),
                "template_usado": dados.get("template_usado", ""),
                "criado_em": dados.get("criado_em", ""),
                "contexto_id": contexto_post,
            }
        )
    return historico


def montar_prompt_usuario(historico: list[dict], orientacao: str = "", contexto_id: str = "") -> str:
    briefing = str(orientacao or "").strip()
    contexto_id = str(contexto_id or "").strip().lstrip("@")

    if briefing:
        prompt = [
            "Crie o próximo post seguindo OBRIGATORIAMENTE o briefing abaixo.",
            "O briefing tem prioridade máxima sobre qualquer conhecimento anterior, histórico ou padrão de outro cliente.",
            "Não mude o nicho, a marca, o público ou o assunto definidos pelo usuário.",
            "Não reutilize temas de outro perfil. Toda a saída, inclusive o prompt de imagem, deve pertencer ao contexto deste briefing.",
        ]
        if contexto_id:
            prompt.append(f"Conta do Instagram atualmente vinculada ao projeto: @{contexto_id}.")
        prompt.extend([
            "BRIEFING PRIORITÁRIO:",
            briefing,
            "Antes de responder, verifique internamente se título, corpo, destaque, legenda e imagem são coerentes com esse briefing.",
        ])
        return "\n".join(prompt)

    prompt = [
        "Crie o próximo post para a conta atual.",
        "Não invente um nicho diferente do histórico desta conta.",
        "Evite repetir assunto, manchete, gancho e abordagem dos posts recentes.",
    ]
    if contexto_id:
        prompt.append(f"Conta atual: @{contexto_id}.")

    if historico:
        prompt.append("Histórico recente DESTA MESMA CONTA para manter continuidade e evitar repetição:")
        for item in historico:
            topico = item.get("topico") or "sem tópico"
            titulo = item.get("titulo") or "sem título"
            selo = item.get("selo_visual") or "sem selo"
            corpo = item.get("corpo") or ""
            prompt.append(f"- tópico={topico} | selo={selo} | título={titulo} | resumo={corpo}")
    else:
        prompt.append("Não há histórico desta conta. Mantenha a proposta genérica e não assuma um nicho específico sem contexto.")

    return "\n".join(prompt)


def _extrair_identidade_visual(briefing: str = "", contexto_id: str = "", marca_sugerida: str = "") -> tuple[str, str]:
    texto = str(briefing or "")
    contexto = str(contexto_id or "").strip().lstrip("@")

    def campo(chaves: list[str]) -> str:
        padrao = r"(?im)^\s*(?:" + "|".join(re.escape(c) for c in chaves) + r")\s*:\s*(.+?)\s*$"
        m = re.search(padrao, texto)
        return m.group(1).strip() if m else ""

    marca = campo(["marca", "nome da marca", "empresa", "projeto", "cliente", "perfil", "brand"])
    site = campo(["site", "website", "dominio", "domínio"])

    if not marca:
        marca = str(marca_sugerida or "").strip()
    if not marca and contexto:
        marca = contexto.replace("_", " ").replace(".", " ").strip().upper()
    if not site and contexto:
        site = f"@{contexto}"

    # Compatibilidade para instalações antigas sem conta/contexto informado.
    marca = marca or "STUDIOLAB"
    site = site or ""
    return marca[:44], site[:80]


def _contexto_visual_generico(conteudo: dict) -> str:
    base = " ".join([
        str(conteudo.get("topico", "")),
        str(conteudo.get("titulo", "")),
        str(conteudo.get("corpo", "")),
        str(conteudo.get("destaque", "")),
    ]).lower()

    if any(p in base for p in ["car", "sicar", "sigef", "mapbiomas", "fazenda", "rural", "lavoura", "agro", "uso do solo"]):
        return "credible rural or territorial editorial context, agribusiness realism only when supported by the current topic"
    if any(p in base for p in ["bolo", "brownie", "confeitaria", "doce", "sobremesa", "chocolate", "brigadeiro", "fatia"]):
        return "premium food photography, appetizing texture, elegant bakery or confectionery presentation, commercial social media styling"
    if any(p in base for p in ["software", "tecnologia", "app", "sistema", "digital", "ia", "inteligência artificial", "inteligencia artificial"]):
        return "modern technology editorial photography, clean digital atmosphere, professional contemporary composition"
    if any(p in base for p in ["beleza", "estética", "estetica", "salão", "salao", "cosmético", "cosmetico", "maquiagem"]):
        return "premium beauty editorial photography, refined clean styling, elegant commercial composition"
    if any(p in base for p in ["produto", "oferta", "promoção", "promocao", "compre", "venda"]):
        return "premium commercial product photography, strong product focus, clean advertising composition"
    return "premium editorial visual language directly tied to the current subject, without importing another client's niche"


def normalizar_prompt_visual(prompt: str) -> str:
    texto = re.sub(r"\s+", " ", (prompt or "").strip())
    bloqueados = [
        "signpost",
        "sign board",
        "signboard",
        "caption",
        "captions",
        "words",
        "letters",
        "logo",
        "logos",
        "watermark",
        "watermarks",
        "text overlay",
        "written text",
        "readable text",
        "label",
        "labels",
    ]
    for termo in bloqueados:
        texto = re.sub(re.escape(termo), "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+,", ",", texto)
    texto = re.sub(r",\s*,", ", ", texto)
    return texto.strip(" ,")


def inferir_categoria(texto: str) -> str:
    base = (texto or "").lower()
    if any(p in base for p in ["embargo", "desmat", "ambient", "ibama", "risco"]):
        return "alerta"
    if any(p in base for p in ["mapbiomas", "mapa", "satélite", "satelite", "uso do solo"]):
        return "mapa"
    if any(p in base for p in ["score", "pontuação", "0 a 100", "indice", "índice"]):
        return "score"
    if any(p in base for p in ["car", "sicar", "regularização", "registro", "cadastro"]):
        return "documental"
    if any(p in base for p in ["comprar", "vender", "negociar", "investir"]):
        return "negocio"
    return "analise"


def montar_prompt_visual(conteudo: dict, layout_ia: dict | None = None) -> str:
    base = normalizar_prompt_visual(conteudo.get("prompt_imagem", "")) or FALLBACK_PROMPT_IMAGEM
    contexto = " ".join(
        [
            str(conteudo.get("topico", "")),
            str(conteudo.get("titulo", "")),
            str(conteudo.get("corpo", "")),
            str(conteudo.get("destaque", "")),
        ]
    )
    categoria = inferir_categoria(contexto)

    reforco_contexto = _contexto_visual_generico(conteudo)

    if layout_ia:
        content = layout_ia.get("content", {}) if isinstance(layout_ia, dict) else {}
        try:
            centro = int(content.get("x", 70)) + int(content.get("width", 520)) / 2
        except Exception:
            centro = 330
        if centro >= 620:
            espaco = (
                "leave a generous clean negative space area for text overlay on the right side and upper-right, "
                "place important visual subjects more to the left side, lower-left or in the background"
            )
        elif 430 <= centro < 620:
            espaco = (
                "leave a generous clean negative space area through the central zone for text overlay, "
                "keep important visual subjects near the outer edges or in the background"
            )
        else:
            espaco = (
                "leave a generous clean negative space area for text overlay on the left side and upper-left, "
                "place important visual subjects more to the right side, lower-right or in the background"
            )
        reforco_final = (
            "vertical premium editorial photography for an Instagram card background, visual language aligned with the current niche and topic, natural professional light, "
            f"clean composition, {espaco}, avoid clutter behind text areas, "
            "no text, no letters, no numbers, no signboards, no captions, no watermarks, no logos"
        )
    else:
        reforco_final = PROMPT_IMAGEM_REFORCO

    return ", ".join(
        [
            base,
            reforco_contexto,
            reforco_final,
        ]
    )


def _texto_valido(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (dict, list)):
        return ""
    return str(valor).strip()


def _destaque_automatico(dados: dict) -> str:
    """Cria um destaque curto quando a IA omite esse campo."""
    titulo = _texto_valido(dados.get("titulo"))
    topico = _texto_valido(dados.get("topico"))
    corpo = _texto_valido(dados.get("corpo"))
    base = " ".join([titulo, topico, corpo])

    # Prioriza percentuais, números com unidade e siglas que já estejam no conteúdo.
    padroes = [
        r"\b\d{1,3}(?:[.,]\d+)?\s*%\b",
        r"\b\d+(?:[.,]\d+)?\s*(?:ha|km²|km2|m²|m2)\b",
        r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,12}\b",
    ]
    for padrao in padroes:
        achados = re.findall(padrao, base)
        for item in achados:
            candidato = str(item).strip().upper()
            if 1 < len(candidato) <= 16:
                return candidato

    # Caso não haja número/sigla, usa uma palavra de conteúdo relevante.
    stopwords = {
        "PARA", "COM", "SEM", "UMA", "UM", "DOS", "DAS", "DE", "DO", "DA",
        "E", "EM", "NO", "NA", "NOS", "NAS", "POR", "QUE", "SEU", "SUA", "SEUS",
        "SUAS", "COMO", "MAIS", "ANTES", "DEPOIS", "SOBRE", "ENTRE", "PELO", "PELA",
        "OS", "AS", "O", "A", "AO", "AOS", "OU", "É", "SER", "ESTÁ", "ESTAO", "ESTÃO",
    }
    palavras = re.findall(r"[A-Za-zÀ-ÿ0-9]+", f"{topico} {titulo}")
    candidatas = [p for p in palavras if len(p) >= 4 and p.upper() not in stopwords]
    if candidatas:
        # Prefere uma palavra relativamente curta para preservar o layout.
        candidatas.sort(key=lambda p: (len(p) > 12, -len(p)))
        return candidatas[0][:16].upper()

    return "DESTAQUE"


def _compactar_corpo_para_card(texto: str, limite_chars: int = 230, max_frases: int = 2) -> str:
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()
    if not texto:
        return ""
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", texto) if f.strip()]
    if len(frases) > max_frases:
        texto = " ".join(frases[:max_frases])
    if len(texto) > limite_chars:
        corte = texto[:limite_chars].rsplit(" ", 1)[0].strip()
        texto = (corte or texto[:limite_chars]).rstrip(" ,;:-") + "…"
    return texto


def _reparar_conteudo_ia(dados: dict) -> dict:
    """Normaliza e completa campos recuperáveis sem interromper a geração."""
    if not isinstance(dados, dict):
        dados = {}

    reparado = dict(dados)
    for campo in ("marca_projeto", "topico", "selo_visual", "titulo", "corpo", "destaque", "legenda_instagram", "prompt_imagem"):
        reparado[campo] = _texto_valido(reparado.get(campo))

    if not reparado["topico"]:
        reparado["topico"] = reparado["titulo"] or "Conteúdo editorial"

    if not reparado["titulo"] and reparado["topico"]:
        reparado["titulo"] = reparado["topico"][:80]

    if not reparado["destaque"]:
        reparado["destaque"] = _destaque_automatico(reparado)
        print(f"[IA] Campo 'destaque' ausente; fallback aplicado: {reparado['destaque']}")

    reparado["corpo"] = _compactar_corpo_para_card(reparado["corpo"])

    if not reparado["legenda_instagram"] and (reparado["titulo"] or reparado["corpo"]):
        partes = [p for p in (reparado["titulo"], reparado["corpo"]) if p]
        reparado["legenda_instagram"] = "\n\n".join(partes)
        print("[IA] Campo 'legenda_instagram' ausente; legenda reconstruída localmente.")

    if not reparado["prompt_imagem"] and (reparado["topico"] or reparado["titulo"]):
        tema = reparado["topico"] or reparado["titulo"]
        contexto = reparado["corpo"][:260]
        reparado["prompt_imagem"] = (
            f"Premium editorial realistic photograph representing: {tema}. {contexto}. "
            "Professional composition, strong visual storytelling, clean negative space for graphic design, "
            "no text, no letters, no numbers, no logos, no watermark."
        ).strip()
        print("[IA] Campo 'prompt_imagem' ausente; prompt visual reconstruído localmente.")

    return reparado


def gerar_conteudo_ia(orientacao: str = "", progress_callback=None, modelo: str | None = None, contexto_id: str = "") -> dict:
    briefing = str(orientacao or "").strip()
    # Briefing preenchido não recebe histórico: evita contaminação entre nichos/clientes.
    historico = [] if briefing else listar_posts_recentes(limite=8, contexto_id=contexto_id)
    if historico:
        print(f"[HISTORICO] {len(historico)} post(s) da conta atual carregado(s)")
    elif briefing:
        print("[CONTEXTO] Briefing prioritário ativo; histórico anterior ignorado.")

    modelo_usado = (modelo or MODELO).strip() or MODELO

    stream = ollama.chat(
        model=modelo_usado,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": montar_prompt_usuario(historico, orientacao, contexto_id=contexto_id)},
        ],
        options={
            "temperature": 0.95,
            "num_predict": MAX_TOKENS_RESPOSTA,
        },
        think=False,
        format="json",
        stream=True,
    )

    texto = ""
    tokens_recebidos = 0
    for chunk in stream:
        pedaco = chunk["message"]["content"]
        texto += pedaco
        tokens_recebidos += max(1, len(pedaco.split()))
        print_progresso(tokens_recebidos, MAX_TOKENS_RESPOSTA, "Gerando conteúdo (IA)")
        if progress_callback:
            pct = min(100, int(tokens_recebidos / MAX_TOKENS_RESPOSTA * 100))
            progress_callback(pct, "IA", "Criando tema, texto e direção visual")

    print_progresso(MAX_TOKENS_RESPOSTA, MAX_TOKENS_RESPOSTA, "Gerando conteúdo (IA)")
    if progress_callback:
        progress_callback(100, "IA", "Conteúdo concluído")

    texto = texto.strip()
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip()

    if texto.startswith("```"):
        texto = texto.strip("`")
        texto = texto.replace("json\n", "", 1).strip()

    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ValueError(f"O modelo não retornou JSON válido:\n{texto}") from exc

    dados = _reparar_conteudo_ia(dados)

    # Somente campos realmente essenciais interrompem a geração. Os demais possuem fallback.
    essenciais = ["titulo", "corpo"]
    faltando_essenciais = [campo for campo in essenciais if not _texto_valido(dados.get(campo))]
    if faltando_essenciais:
        raise ValueError(
            "A IA não produziu conteúdo textual suficiente para montar o card. "
            f"Campos essenciais ausentes: {faltando_essenciais}"
        )

    if not _texto_valido(dados.get("selo_visual")):
        dados["selo_visual"] = selo_fallback(dados)

    marca_visual, rodape_visual = _extrair_identidade_visual(
        orientacao,
        contexto_id,
        marca_sugerida=dados.get("marca_projeto", ""),
    )
    dados["marca_visual"] = marca_visual
    dados["rodape_visual"] = rodape_visual
    dados["contexto_id"] = str(contexto_id or "").strip().lower()
    dados["briefing_usado"] = briefing

    return dados


def selo_fallback(conteudo: dict) -> str:
    texto = " ".join(
        [
            str(conteudo.get("topico", "")),
            str(conteudo.get("titulo", "")),
            str(conteudo.get("corpo", "")),
            str(conteudo.get("destaque", "")),
        ]
    )
    categoria = inferir_categoria(texto)
    mapa = {
        "alerta": "ALERTA",
        "mapa": "GUIA VISUAL",
        "score": "DADOS",
        "documental": "DICA PRÁTICA",
        "negocio": "OPORTUNIDADE",
        "analise": "EM DESTAQUE",
    }
    return mapa.get(categoria, "EM DESTAQUE")


def icone_para_conteudo(conteudo: dict) -> str:
    texto = " ".join(
        [
            str(conteudo.get("topico", "")),
            str(conteudo.get("titulo", "")),
            str(conteudo.get("corpo", "")),
            str(conteudo.get("destaque", "")),
        ]
    )
    categoria = inferir_categoria(texto)
    mapa = {
        "alerta": "shield",
        "mapa": "pin",
        "score": "chart",
        "documental": "document",
        "negocio": "target",
        "analise": "spark",
    }
    texto_lower = texto.lower()
    if any(p in texto_lower for p in ["bolo", "brownie", "confeitaria", "doce", "sobremesa", "chocolate"]):
        return "spark"
    if any(p in texto_lower for p in ["software", "tecnologia", "app", "digital", "ia"]):
        return "chart"
    return mapa.get(categoria, "spark")


def _cover(imagem: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = imagem.size
    escala = max(width / src_w, height / src_h)
    novo_w = int(src_w * escala)
    novo_h = int(src_h * escala)
    imagem = imagem.resize((novo_w, novo_h), Image.LANCZOS)

    left = max(0, (novo_w - width) // 2)
    top = max(0, (novo_h - height) // 2)
    return imagem.crop((left, top, left + width, top + height))


def preparar_fundo(imagem_fundo_path: str, width: int, height: int):
    img = Image.open(imagem_fundo_path).convert("RGB")
    img = _cover(img, width, height)

    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(0.94)
    img = ImageEnhance.Brightness(img).enhance(0.84)

    base = img.convert("RGBA")
    overlay = Image.new("RGBA", (width, height), (5, 8, 12, 54))
    base.alpha_composite(overlay)
    return base.convert("RGBA")


def desenhar_gradiente_lateral(base: Image.Image, width: int, height: int, lado: str = "left", intensidade: int = 195):
    grad = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    for x in range(width):
        if lado == "right":
            alpha = max(0, int(intensidade * (x / width)))
        else:
            alpha = max(0, int(intensidade * (1 - x / width)))
        grad_draw.line([(x, 0), (x, height)], fill=(0, 0, 0, alpha))
    base.alpha_composite(grad)


def desenhar_icone(draw: ImageDraw.ImageDraw, x: int, y: int, tipo: str, cor: str):
    if tipo == "shield":
        pontos = [(x + 18, y), (x + 36, y + 8), (x + 36, y + 28), (x + 18, y + 42), (x, y + 28), (x, y + 8)]
        draw.polygon(pontos, outline=cor, fill=None, width=3)
    elif tipo == "pin":
        draw.ellipse((x + 4, y, x + 32, y + 28), outline=cor, width=3)
        draw.polygon([(x + 18, y + 42), (x + 8, y + 22), (x + 28, y + 22)], outline=cor, fill=None, width=3)
        draw.ellipse((x + 13, y + 9, x + 23, y + 19), outline=cor, width=2)
    elif tipo == "chart":
        draw.line((x, y + 38, x + 38, y + 38), fill=cor, width=3)
        draw.line((x, y + 38, x, y + 2), fill=cor, width=3)
        draw.line((x + 6, y + 30, x + 16, y + 20), fill=cor, width=3)
        draw.line((x + 16, y + 20, x + 25, y + 24), fill=cor, width=3)
        draw.line((x + 25, y + 24, x + 36, y + 10), fill=cor, width=3)
    elif tipo == "document":
        draw.rounded_rectangle((x, y, x + 32, y + 40), radius=6, outline=cor, width=3)
        draw.line((x + 7, y + 13, x + 25, y + 13), fill=cor, width=2)
        draw.line((x + 7, y + 22, x + 25, y + 22), fill=cor, width=2)
        draw.line((x + 7, y + 31, x + 20, y + 31), fill=cor, width=2)
    elif tipo == "target":
        draw.ellipse((x, y, x + 40, y + 40), outline=cor, width=3)
        draw.ellipse((x + 10, y + 10, x + 30, y + 30), outline=cor, width=3)
        draw.line((x + 20, y - 4, x + 20, y + 12), fill=cor, width=3)
        draw.line((x + 20, y + 28, x + 20, y + 44), fill=cor, width=3)
        draw.line((x - 4, y + 20, x + 12, y + 20), fill=cor, width=3)
        draw.line((x + 28, y + 20, x + 44, y + 20), fill=cor, width=3)
    else:  # spark / ícone genérico
        draw.line((x + 20, y, x + 20, y + 40), fill=cor, width=3)
        draw.line((x, y + 20, x + 40, y + 20), fill=cor, width=3)
        draw.line((x + 7, y + 7, x + 33, y + 33), fill=cor, width=3)
        draw.line((x + 33, y + 7, x + 7, y + 33), fill=cor, width=3)


def _fonte(caminho: str, tamanho: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(caminho, max(10, int(tamanho)))


def _largura_texto(draw: ImageDraw.ImageDraw, texto: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), texto or "", font=font)
    return max(0, bbox[2] - bbox[0])


def _altura_texto(draw: ImageDraw.ImageDraw, texto: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = draw.textbbox((0, 0), texto or "Ag", font=font)
    return max(1, bbox[3] - bbox[1])


def _quebrar_linhas_pixel(
    draw: ImageDraw.ImageDraw,
    texto: str,
    font: ImageFont.FreeTypeFont,
    largura_max: int,
) -> list[str]:
    palavras = str(texto or "").strip().split()
    if not palavras:
        return []

    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        tentativa = palavra if not atual else f"{atual} {palavra}"
        if _largura_texto(draw, tentativa, font) <= largura_max:
            atual = tentativa
            continue

        if atual:
            linhas.append(atual)
            atual = ""

        # Palavra excepcionalmente longa: reduz a chance de estourar o layout.
        if _largura_texto(draw, palavra, font) <= largura_max:
            atual = palavra
        else:
            pedaco = ""
            for ch in palavra:
                teste = pedaco + ch
                if pedaco and _largura_texto(draw, teste, font) > largura_max:
                    linhas.append(pedaco)
                    pedaco = ch
                else:
                    pedaco = teste
            atual = pedaco

    if atual:
        linhas.append(atual)
    return linhas


def _ajustar_texto_multilinha(
    draw: ImageDraw.ImageDraw,
    texto: str,
    largura_max: int,
    altura_max: int,
    tamanho_max: int,
    tamanho_min: int,
    max_linhas: int,
    bold: bool = False,
    espacamento: float = 1.12,
):
    caminho = FONT_BOLD if bold else FONT_REGULAR
    for tamanho in range(tamanho_max, tamanho_min - 1, -2):
        font = _fonte(caminho, tamanho)
        linhas = _quebrar_linhas_pixel(draw, texto, font, largura_max)
        if not linhas:
            return font, [], max(1, tamanho)
        line_h = max(_altura_texto(draw, "Ag", font), int(tamanho * 0.92))
        passo = max(line_h + 4, int(tamanho * espacamento))
        altura = line_h + max(0, len(linhas) - 1) * passo
        if len(linhas) <= max_linhas and altura <= altura_max:
            return font, linhas, passo

    font = _fonte(caminho, tamanho_min)
    linhas = _quebrar_linhas_pixel(draw, texto, font, largura_max)[:max_linhas]
    passo = max(_altura_texto(draw, "Ag", font) + 4, int(tamanho_min * espacamento))
    return font, linhas, passo


def _ajustar_fonte_linha(
    draw: ImageDraw.ImageDraw,
    texto: str,
    largura_max: int,
    tamanho_max: int,
    tamanho_min: int,
    bold: bool = True,
):
    caminho = FONT_BOLD if bold else FONT_REGULAR
    for tamanho in range(tamanho_max, tamanho_min - 1, -2):
        font = _fonte(caminho, tamanho)
        if _largura_texto(draw, texto, font) <= largura_max:
            return font
    return _fonte(caminho, tamanho_min)


def desenhar_selo(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    texto: str,
    icone: str,
    largura_max: int = 520,
):
    texto = (texto or "EM DESTAQUE").upper().strip()
    altura = 50
    area_texto = max(100, largura_max - 82)
    font = _ajustar_fonte_linha(draw, texto, area_texto, 22, 14, bold=True)
    largura_texto = _largura_texto(draw, texto, font)
    largura = min(largura_max, max(190, largura_texto + 82))

    draw.rounded_rectangle(
        (x, y, x + largura, y + altura),
        radius=18,
        fill=(10, 21, 17),
        outline=COR_DESTAQUE,
        width=2,
    )
    desenhar_icone(draw, x + 14, y + 4, icone, COR_DESTAQUE)
    text_y = y + max(7, (altura - _altura_texto(draw, texto, font)) // 2 - 2)
    draw.text((x + 58, text_y), texto, font=font, fill=COR_TEXTO)
    return altura


def desenhar_bloco_destaque(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    texto: str,
    largura_max: int = 520,
    tamanho_max: int = 170,
    tamanho_min: int = 72,
    compacto: bool = False,
):
    texto = str(texto or "").strip().upper()
    padding_esq = 36 if not compacto else 28
    padding_dir = 28 if not compacto else 22
    padding_y = 18 if not compacto else 14
    largura_texto_max = max(100, largura_max - padding_esq - padding_dir)
    font = _ajustar_fonte_linha(
        draw,
        texto,
        largura_texto_max,
        tamanho_max,
        tamanho_min,
        bold=True,
    )
    largura_texto = _largura_texto(draw, texto, font)
    altura_texto = _altura_texto(draw, texto, font)
    largura = min(largura_max, max(220, largura_texto + padding_esq + padding_dir))
    altura = max(112 if compacto else 142, altura_texto + padding_y * 2)

    # sombra discreta para separar o bloco da fotografia
    draw.rounded_rectangle(
        (x + 5, y + 7, x + largura + 5, y + altura + 7),
        radius=30 if compacto else 34,
        fill=(0, 0, 0, 65),
    )
    draw.rounded_rectangle(
        (x, y, x + largura, y + altura),
        radius=30 if compacto else 34,
        fill=(8, 18, 14),
        outline=COR_DESTAQUE,
        width=3,
    )

    # barra lateral fina, sem invadir a primeira letra
    barra_w = 14 if compacto else 16
    draw.rounded_rectangle(
        (x, y, x + barra_w, y + altura),
        radius=10,
        fill=COR_DESTAQUE,
    )

    texto_x = x + padding_esq
    texto_y = y + max(8, (altura - altura_texto) // 2 - 6)
    draw.text((texto_x, texto_y), texto, font=font, fill=COR_DESTAQUE_2)
    return altura


def desenhar_bloco_destaque_compacto(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    texto: str,
    largura_max: int = 500,
):
    return desenhar_bloco_destaque(
        draw,
        x,
        y,
        texto,
        largura_max=largura_max,
        tamanho_max=124,
        tamanho_min=58,
        compacto=True,
    )


def _desenhar_titulo(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    titulo: str,
    largura_max: int,
    altura_max: int,
    tamanho_max: int,
    tamanho_min: int,
    max_linhas: int,
):
    font, linhas, passo = _ajustar_texto_multilinha(
        draw,
        titulo,
        largura_max,
        altura_max,
        tamanho_max,
        tamanho_min,
        max_linhas,
        bold=True,
        espacamento=1.08,
    )
    cy = y
    for linha in linhas:
        draw.text((x, cy), linha, font=font, fill=COR_TEXTO)
        cy += passo
    return cy


def _desenhar_corpo(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    corpo: str,
    largura_max: int,
    altura_max: int,
    tamanho_max: int,
    tamanho_min: int,
    max_linhas: int,
):
    font, linhas, passo = _ajustar_texto_multilinha(
        draw,
        corpo,
        largura_max,
        altura_max,
        tamanho_max,
        tamanho_min,
        max_linhas,
        bold=False,
        espacamento=1.20,
    )
    cy = y
    for linha in linhas:
        draw.text((x, cy), linha, font=font, fill=COR_SECUNDARIA)
        cy += passo
    return cy


def _extrair_conteudo_resposta(resposta) -> str:
    """Extrai o texto retornado pelo cliente Ollama em versões novas e antigas."""
    mensagem = getattr(resposta, "message", None)
    if mensagem is not None:
        conteudo = getattr(mensagem, "content", None)
        if conteudo is not None:
            return str(conteudo)
    if isinstance(resposta, dict):
        mensagem = resposta.get("message", {})
        if isinstance(mensagem, dict):
            return str(mensagem.get("content", ""))
    return ""


def _clamp_int(valor, minimo: int, maximo: int, padrao: int) -> int:
    try:
        valor = int(round(float(valor)))
    except Exception:
        valor = padrao
    return max(minimo, min(maximo, valor))


def _normalizar_layout_ia(layout: dict) -> dict:
    """Valida e limita o layout criado pela IA para nunca desenhar fora do card."""
    if not isinstance(layout, dict):
        layout = {}

    content = layout.get("content") if isinstance(layout.get("content"), dict) else {}
    panel = layout.get("panel") if isinstance(layout.get("panel"), dict) else {}
    accent = layout.get("accent") if isinstance(layout.get("accent"), dict) else {}
    brand = layout.get("brand") if isinstance(layout.get("brand"), dict) else {}

    content_w = _clamp_int(content.get("width"), 360, 620, 520)
    content_x = _clamp_int(content.get("x"), 50, 1080 - content_w - 50, 70)
    content_y = _clamp_int(content.get("y"), 135, 350, 155)

    panel_x = _clamp_int(panel.get("x"), 24, 760, max(30, content_x - 30))
    panel_y = _clamp_int(panel.get("y"), 90, 520, max(100, content_y - 35))
    panel_w = _clamp_int(panel.get("width"), 400, 760, min(680, content_w + 70))
    if panel_x + panel_w > 1055:
        panel_x = max(24, 1055 - panel_w)
    panel_h = _clamp_int(panel.get("height"), 620, 1080, 830)
    if panel_y + panel_h > 1250:
        panel_h = max(620, 1250 - panel_y)

    gradient_side = str(layout.get("gradient_side", "left")).lower()
    if gradient_side not in {"left", "right", "none"}:
        gradient_side = "left"

    panel_style = str(panel.get("style", "glass")).lower()
    if panel_style not in {"glass", "solid", "outline", "none"}:
        panel_style = "glass"

    accent_orientation = str(accent.get("orientation", "vertical")).lower()
    if accent_orientation not in {"vertical", "horizontal", "corner", "none"}:
        accent_orientation = "vertical"

    highlight_style = str(content.get("highlight_style", "block")).lower()
    if highlight_style not in {"block", "compact", "plain"}:
        highlight_style = "block"

    return {
        "concept": str(layout.get("concept", "editorial dynamic"))[:120],
        "gradient_side": gradient_side,
        "gradient_intensity": _clamp_int(layout.get("gradient_intensity"), 70, 220, 145),
        "panel": {
            "style": panel_style,
            "x": panel_x,
            "y": panel_y,
            "width": panel_w,
            "height": panel_h,
            "radius": _clamp_int(panel.get("radius"), 0, 60, 30),
            "opacity": _clamp_int(panel.get("opacity"), 25, 210, 82),
        },
        "accent": {
            "orientation": accent_orientation,
            "thickness": _clamp_int(accent.get("thickness"), 3, 32, 8),
            "offset": _clamp_int(accent.get("offset"), 0, 38, 12),
        },
        "brand": {
            "x": _clamp_int(brand.get("x"), 50, 720, content_x),
            "y": _clamp_int(brand.get("y"), 45, 125, 60),
            "line": bool(brand.get("line", True)),
        },
        "content": {
            "x": content_x,
            "y": content_y,
            "width": content_w,
            "title_max": _clamp_int(content.get("title_max"), 48, 76, 62),
            "title_min": _clamp_int(content.get("title_min"), 32, 48, 39),
            "title_lines": _clamp_int(content.get("title_lines"), 2, 4, 3),
            "highlight_style": highlight_style,
            "highlight_max": _clamp_int(content.get("highlight_max"), 90, 180, 150),
            "body_max": _clamp_int(content.get("body_max"), 29, 42, 36),
            "body_min": _clamp_int(content.get("body_min"), 22, 30, 25),
            "body_lines": _clamp_int(content.get("body_lines"), 4, 9, 6),
            "gap_badge_title": _clamp_int(content.get("gap_badge_title"), 70, 115, 86),
            "gap_title_highlight": _clamp_int(content.get("gap_title_highlight"), 12, 38, 20),
            "gap_highlight_body": _clamp_int(content.get("gap_highlight_body"), 18, 44, 30),
        },
    }


def gerar_layout_dinamico_ia(conteudo: dict, modelo: str, progress_callback=None) -> dict:
    """Pede ao modelo uma composição inédita, sem escolher os templates fixos."""
    prompt = f"""
Você é diretor de arte do StudioLab. Crie uma composição VISUAL NOVA para um card vertical 1080x1350.
Não escolha, copie nem mencione templates existentes. Você deve projetar o layout usando parâmetros geométricos.
O card terá uma fotografia de fundo e estes conteúdos:
- selo: {conteudo.get('selo_visual', '')}
- título: {conteudo.get('titulo', '')}
- destaque: {conteudo.get('destaque', '')}
- corpo: {conteudo.get('corpo', '')}

Retorne SOMENTE JSON válido, sem markdown, neste formato:
{{
  "concept": "nome curto do conceito visual",
  "gradient_side": "left|right|none",
  "gradient_intensity": 70,
  "panel": {{"style": "glass|solid|outline|none", "x": 40, "y": 120, "width": 620, "height": 850, "radius": 30, "opacity": 80}},
  "accent": {{"orientation": "vertical|horizontal|corner|none", "thickness": 8, "offset": 12}},
  "brand": {{"x": 70, "y": 60, "line": true}},
  "content": {{
    "x": 70, "y": 155, "width": 520,
    "title_max": 62, "title_min": 39, "title_lines": 3,
    "highlight_style": "block|compact|plain", "highlight_max": 150,
    "body_max": 36, "body_min": 25, "body_lines": 6,
    "gap_badge_title": 86, "gap_title_highlight": 20, "gap_highlight_body": 30
  }}
}}

Faixas permitidas: content x=50-650, y=135-350, width=360-620; panel x=24-760, y=90-520, width=400-760, height=620-1080.
Priorize legibilidade, equilíbrio, espaço de respiro e aparência premium. Faça uma composição diferente e coerente com o assunto.
""".strip()

    if progress_callback:
        progress_callback(12, "LAYOUT IA", "Projetando composição exclusiva")

    resposta = ollama.chat(
        model=modelo,
        messages=[
            {"role": "system", "content": "Você responde exclusivamente JSON válido para especificações de design."},
            {"role": "user", "content": prompt},
        ],
        options={"temperature": 0.9, "num_predict": 520},
        think=False,
        stream=False,
    )
    texto = _extrair_conteudo_resposta(resposta).strip()
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL).strip()
    if texto.startswith("```"):
        texto = texto.strip("`")
        texto = re.sub(r"^json\s*", "", texto, flags=re.IGNORECASE).strip()
    try:
        bruto = json.loads(texto)
    except Exception:
        inicio = texto.find("{")
        fim = texto.rfind("}")
        if inicio >= 0 and fim > inicio:
            try:
                bruto = json.loads(texto[inicio: fim + 1])
            except Exception as exc:
                raise ValueError(f"A IA não retornou um layout JSON válido: {texto[:500]}") from exc
        else:
            raise ValueError(f"A IA não retornou um layout JSON válido: {texto[:500]}")

    layout = _normalizar_layout_ia(bruto)
    if progress_callback:
        progress_callback(100, "LAYOUT IA", f"Composição criada: {layout.get('concept', 'dinâmica')}")
    return layout


def preparar_template_dinamico(base: Image.Image, width: int, height: int, layout: dict):
    gradient_side = layout.get("gradient_side", "left")
    if gradient_side in {"left", "right"}:
        desenhar_gradiente_lateral(base, width, height, lado=gradient_side, intensidade=int(layout.get("gradient_intensity", 145)))

    panel = layout.get("panel", {})
    style = panel.get("style", "glass")
    if style != "none":
        camada = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(camada)
        x, y = int(panel["x"]), int(panel["y"])
        w, h = int(panel["width"]), int(panel["height"])
        op = int(panel.get("opacity", 82))
        radius = int(panel.get("radius", 30))
        if style == "solid":
            fill = (5, 13, 11, min(225, max(120, op + 55)))
            outline = (255, 255, 255, 18)
        elif style == "outline":
            fill = (0, 0, 0, max(18, op // 3))
            outline = (143, 209, 79, 150)
        else:
            fill = (5, 12, 10, op)
            outline = (255, 255, 255, 24)
        d.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=fill, outline=outline, width=2)
        base.alpha_composite(camada)

    accent = layout.get("accent", {})
    orientation = accent.get("orientation", "none")
    if orientation != "none":
        camada = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(camada)
        x, y = int(panel["x"]), int(panel["y"])
        w, h = int(panel["width"]), int(panel["height"])
        t = int(accent.get("thickness", 8))
        off = int(accent.get("offset", 12))
        cor = (143, 209, 79, 220)
        if orientation == "vertical":
            ax = min(width - 20, x + w + off)
            d.rounded_rectangle((ax, y + 45, ax + t, y + h - 45), radius=max(1, t // 2), fill=cor)
        elif orientation == "horizontal":
            ay = max(20, y - off - t)
            d.rounded_rectangle((x + 35, ay, x + w - 35, ay + t), radius=max(1, t // 2), fill=cor)
        elif orientation == "corner":
            d.line([(x + 26, y + 70), (x + 26, y + 26), (x + 150, y + 26)], fill=cor, width=t)
        base.alpha_composite(camada)


def layout_dinamico(draw: ImageDraw.ImageDraw, width: int, height: int, titulo: str, corpo: str, destaque: str, selo: str, icone: str, layout: dict, marca_visual: str):
    cfg = layout.get("content", {})
    brand = layout.get("brand", {})
    x = int(cfg.get("x", 70))
    y = int(cfg.get("y", 160))
    content_w = int(cfg.get("width", 520))

    bx = int(brand.get("x", x))
    by = int(brand.get("y", 60))
    marca_visual = str(marca_visual or "STUDIOLAB").upper().strip()
    brand_font = _ajustar_fonte_linha(draw, marca_visual, min(440, max(280, content_w)), 34, 20, bold=True)
    draw.text((bx, by), marca_visual, font=brand_font, fill=COR_SECUNDARIA)
    if brand.get("line", True):
        line_end = min(1010, bx + max(280, content_w))
        draw.line([(bx, by + 52), (line_end, by + 52)], fill=COR_DESTAQUE, width=3)

    desenhar_selo(draw, x, y, selo, icone, largura_max=content_w)
    y += int(cfg.get("gap_badge_title", 86))

    y = _desenhar_titulo(
        draw, x, y, titulo,
        largura_max=content_w,
        altura_max=235,
        tamanho_max=int(cfg.get("title_max", 62)),
        tamanho_min=int(cfg.get("title_min", 39)),
        max_linhas=int(cfg.get("title_lines", 3)),
    )
    y += int(cfg.get("gap_title_highlight", 20))

    style = cfg.get("highlight_style", "block")
    if style == "plain":
        font = _ajustar_fonte_linha(draw, destaque, content_w, int(cfg.get("highlight_max", 150)), 58, bold=True)
        draw.text((x, y), destaque, font=font, fill=COR_DESTAQUE_2)
        _, top, _, bottom = draw.textbbox((0, 0), destaque, font=font)
        destaque_h = max(70, bottom - top + 18)
    elif style == "compact":
        destaque_h = desenhar_bloco_destaque_compacto(draw, x, y, destaque, largura_max=content_w)
    else:
        destaque_h = desenhar_bloco_destaque(draw, x, y, destaque, largura_max=content_w, tamanho_max=int(cfg.get("highlight_max", 150)), tamanho_min=62)

    y += destaque_h + int(cfg.get("gap_highlight_body", 30))
    body_limit = max(150, min(1120 - y, 430))
    _desenhar_corpo(
        draw, x, y, corpo,
        largura_max=content_w,
        altura_max=body_limit,
        tamanho_max=int(cfg.get("body_max", 36)),
        tamanho_min=int(cfg.get("body_min", 25)),
        max_linhas=int(cfg.get("body_lines", 6)),
    )


def preparar_template_base(base: Image.Image, draw: ImageDraw.ImageDraw, width: int, height: int, template: str):
    if template == "classic_left":
        desenhar_gradiente_lateral(base, width, height, lado="left", intensidade=188)
        painel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        painel_draw = ImageDraw.Draw(painel)
        painel_draw.rounded_rectangle(
            (38, 138, 650, 875),
            radius=34,
            fill=(0, 0, 0, 46),
            outline=(255, 255, 255, 18),
            width=1,
        )
        base.alpha_composite(painel)
    elif template == "spotlight_card":
        desenhar_gradiente_lateral(base, width, height, lado="left", intensidade=130)
        painel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        painel_draw = ImageDraw.Draw(painel)
        painel_draw.rounded_rectangle(
            (54, 170, 690, 920),
            radius=42,
            fill=(9, 18, 14, 96),
            outline=(143, 209, 79, 96),
            width=2,
        )
        base.alpha_composite(painel)
    elif template == "modern_split":
        desenhar_gradiente_lateral(base, width, height, lado="right", intensidade=88)
        painel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        painel_draw = ImageDraw.Draw(painel)
        painel_draw.rectangle((38, 90, 520, 1240), fill=(7, 16, 12, 150))
        painel_draw.rectangle((500, 90, 548, 1240), fill=(143, 209, 79, 195))
        base.alpha_composite(painel)


def layout_classic(draw: ImageDraw.ImageDraw, width: int, height: int, titulo: str, corpo: str, destaque: str, selo: str, icone: str, marca_visual: str):
    x = 70
    content_w = 535
    draw.text((x, 60), str(marca_visual or "STUDIOLAB").upper(), font=_ajustar_fonte_linha(draw, str(marca_visual or "STUDIOLAB").upper(), 520, 34, 20, bold=True), fill=COR_SECUNDARIA)
    draw.line([(x, 110), (1010, 110)], fill=COR_DESTAQUE, width=3)
    desenhar_selo(draw, x, 145, selo, icone, largura_max=content_w)

    y = _desenhar_titulo(
        draw, x, 230, titulo,
        largura_max=content_w,
        altura_max=160,
        tamanho_max=60,
        tamanho_min=42,
        max_linhas=3,
    )
    y += 18
    destaque_h = desenhar_bloco_destaque(
        draw, x, y, destaque,
        largura_max=content_w,
        tamanho_max=166,
        tamanho_min=68,
    )
    y += destaque_h + 34
    _desenhar_corpo(
        draw, x, y, corpo,
        largura_max=content_w,
        altura_max=max(150, 805 - y),
        tamanho_max=38,
        tamanho_min=27,
        max_linhas=6,
    )


def layout_spotlight(draw: ImageDraw.ImageDraw, width: int, height: int, titulo: str, corpo: str, destaque: str, selo: str, icone: str, marca_visual: str):
    draw.text((70, 60), str(marca_visual or "STUDIOLAB").upper(), font=_ajustar_fonte_linha(draw, str(marca_visual or "STUDIOLAB").upper(), 520, 34, 20, bold=True), fill=COR_SECUNDARIA)
    draw.line([(70, 110), (1010, 110)], fill=COR_DESTAQUE, width=3)

    x = 92
    content_w = 545
    desenhar_selo(draw, x, 196, selo, icone, largura_max=content_w)
    y = _desenhar_titulo(
        draw, x, 292, titulo,
        largura_max=content_w,
        altura_max=170,
        tamanho_max=62,
        tamanho_min=42,
        max_linhas=3,
    )
    y += 18
    destaque_h = desenhar_bloco_destaque_compacto(
        draw, x, y, destaque,
        largura_max=content_w,
    )
    y += destaque_h + 34
    _desenhar_corpo(
        draw, x, y, corpo,
        largura_max=content_w,
        altura_max=max(150, 850 - y),
        tamanho_max=36,
        tamanho_min=26,
        max_linhas=6,
    )


def layout_modern_split(draw: ImageDraw.ImageDraw, width: int, height: int, titulo: str, corpo: str, destaque: str, selo: str, icone: str, marca_visual: str):
    x = 68
    content_w = 392
    draw.text((70, 60), str(marca_visual or "STUDIOLAB").upper(), font=_ajustar_fonte_linha(draw, str(marca_visual or "STUDIOLAB").upper(), 520, 34, 20, bold=True), fill=COR_SECUNDARIA)
    desenhar_selo(draw, x, 145, selo, icone, largura_max=content_w)

    y = _desenhar_titulo(
        draw, x, 240, titulo,
        largura_max=content_w,
        altura_max=220,
        tamanho_max=54,
        tamanho_min=36,
        max_linhas=4,
    )
    y += 16
    destaque_h = desenhar_bloco_destaque_compacto(
        draw, x, y, destaque,
        largura_max=content_w,
    )
    y += destaque_h + 30
    _desenhar_corpo(
        draw, x, y, corpo,
        largura_max=content_w,
        altura_max=max(200, 1060 - y),
        tamanho_max=34,
        tamanho_min=24,
        max_linhas=9,
    )


def desenhar_rodape(draw: ImageDraw.ImageDraw, width: int, height: int, texto: str = ""):
    texto = str(texto or "").strip()
    if not texto:
        return
    font = _ajustar_fonte_linha(draw, texto, 420, 28, 18, bold=False)
    tw = _largura_texto(draw, texto, font)
    box_w = min(500, max(220, tw + 52))
    draw.rounded_rectangle((60, height - 120, 60 + box_w, height - 55), radius=18, fill=(0, 0, 0, 205))
    draw.text((82, height - 100), texto, font=font, fill=COR_TEXTO)


def gerar_card(
    titulo: str,
    corpo: str,
    destaque: str,
    selo_visual: str,
    output_path: str,
    template: str,
    fundo_path: str | None = None,
    icone: str = "spark",
    layout_ia: dict | None = None,
    marca_visual: str = "STUDIOLAB",
    rodape_visual: str = "",
    progress_callback=None,
):
    etapas_total = 6
    etapa = 0
    width, height = 1080, 1350

    if fundo_path and os.path.exists(fundo_path):
        img = preparar_fundo(fundo_path, width, height)
    else:
        img = Image.new("RGBA", (width, height), COR_FUNDO)

    draw = ImageDraw.Draw(img)
    etapa += 1
    print_progresso(etapa, etapas_total, "Montando card")
    if progress_callback: progress_callback(12, "CARD", "Preparando base visual")

    if template == TEMPLATE_DINAMICO and layout_ia:
        preparar_template_dinamico(img, width, height, layout_ia)
    else:
        preparar_template_base(img, draw, width, height, template)
    draw = ImageDraw.Draw(img)
    etapa += 1
    print_progresso(etapa, etapas_total, "Montando card")
    if progress_callback: progress_callback(32, "CARD", "Aplicando template")

    if template == TEMPLATE_DINAMICO and layout_ia:
        layout_dinamico(draw, width, height, titulo, corpo, destaque, selo_visual, icone, layout_ia, marca_visual)
    elif template == "spotlight_card":
        layout_spotlight(draw, width, height, titulo, corpo, destaque, selo_visual, icone, marca_visual)
    elif template == "modern_split":
        layout_modern_split(draw, width, height, titulo, corpo, destaque, selo_visual, icone, marca_visual)
    else:
        layout_classic(draw, width, height, titulo, corpo, destaque, selo_visual, icone, marca_visual)
    etapa += 1
    print_progresso(etapa, etapas_total, "Montando card")
    if progress_callback: progress_callback(68, "CARD", "Montando textos e destaque")

    desenhar_rodape(draw, width, height, rodape_visual)
    etapa += 1
    print_progresso(etapa, etapas_total, "Montando card")
    if progress_callback: progress_callback(82, "CARD", "Finalizando identidade visual")

    img = img.convert("RGB")
    etapa += 1
    print_progresso(etapa, etapas_total, "Montando card")

    img.save(output_path, quality=95)
    if progress_callback: progress_callback(100, "CARD", "Card salvo")
    etapa += 1
    print_progresso(etapa, etapas_total, "Montando card")

    return output_path


def preparar_pasta_post() -> Path:
    agora = datetime.now()
    pasta_data = POSTS_DIR / agora.strftime("%Y-%m-%d")
    pasta_execucao = pasta_data / agora.strftime("%H%M%S")
    pasta_execucao.mkdir(parents=True, exist_ok=True)
    return pasta_execucao


def escolher_template(historico: list[dict]) -> str:
    ultimo = historico[0].get("template_usado") if historico else None
    candidatos = [t for t in TEMPLATES_FIXOS if t != ultimo] or TEMPLATES_FIXOS[:]
    return random.choice(candidatos)


def salvar_metadados_post(
    pasta_post: Path,
    conteudo: dict,
    modelo_ia: str,
    prompt_visual_final: str,
    checkpoint_usado: str | None,
    card_path: Path,
    fundo_path: Path | None,
    template_usado: str,
    icone_usado: str,
    layout_ia: dict | None = None,
):
    contexto_id = str(conteudo.get("contexto_id") or "").strip().lstrip("@")
    instagram = f"@{contexto_id}" if contexto_id else ""
    marca_visual = str(conteudo.get("marca_visual") or "").strip()
    rodape_visual = str(conteudo.get("rodape_visual") or "").strip()
    cliente = marca_visual or instagram or "StudioLab"

    payload = {
        "criado_em": datetime.now().isoformat(timespec="seconds"),
        "cliente": cliente,
        "marca_projeto": conteudo.get("marca_projeto") or marca_visual,
        "instagram": instagram,
        "site_oficial": rodape_visual if rodape_visual and not rodape_visual.startswith("@") else "",
        "contexto_id": contexto_id,
        "briefing_usado": conteudo.get("briefing_usado") or "",
        "marca_visual": marca_visual,
        "rodape_visual": rodape_visual,
        "modelo_ia": modelo_ia,
        "topico": conteudo.get("topico"),
        "selo_visual": conteudo.get("selo_visual"),
        "titulo": conteudo.get("titulo"),
        "corpo": conteudo.get("corpo"),
        "destaque": conteudo.get("destaque"),
        "legenda_instagram": conteudo.get("legenda_instagram"),
        "prompt_imagem_original": conteudo.get("prompt_imagem"),
        "prompt_imagem_final": prompt_visual_final,
        "checkpoint_usado": checkpoint_usado,
        "template_usado": template_usado,
        "layout_ia": layout_ia,
        "icone_usado": icone_usado,
        "arquivos": {
            "card": card_path.name,
            "fundo": fundo_path.name if fundo_path else None,
        },
    }

    (pasta_post / "post.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def gerar_post_completo(
    orientacao: str = "",
    template_preferido: str = "auto",
    usar_comfyui: bool = True,
    modelo_ia: str | None = None,
    checkpoint_preferido: str | None = None,
    contexto_id: str = "",
    progress_callback=None,
) -> dict:
    """Executa o fluxo completo e retorna os dados do post para CLI ou portal."""
    historico = listar_posts_recentes(limite=8, contexto_id=contexto_id)

    def emit(pct: int, etapa: str, mensagem: str):
        if progress_callback:
            try:
                progress_callback(max(0, min(100, int(pct))), etapa, mensagem)
            except Exception:
                pass

    modelo_usado = (modelo_ia or MODELO).strip() or MODELO
    checkpoint_escolhido = (checkpoint_preferido or CHECKPOINT_PADRAO).strip() or CHECKPOINT_PADRAO
    emit(2, "INÍCIO", f"Preparando geração com {modelo_usado}")

    def ia_cb(pct, etapa, msg):
        emit(5 + int(pct * 0.24), etapa, msg)

    conteudo = gerar_conteudo_ia(orientacao=orientacao, progress_callback=ia_cb, modelo=modelo_usado, contexto_id=contexto_id)
    if not str(conteudo.get("selo_visual", "")).strip():
        conteudo["selo_visual"] = selo_fallback(conteudo)

    emit(30, "DIREÇÃO", "Definindo composição visual")
    if template_preferido in TEMPLATES:
        template_usado = template_preferido
    else:
        template_usado = escolher_template(historico)

    layout_ia = None
    if template_usado == TEMPLATE_DINAMICO:
        def layout_cb(pct, etapa, msg):
            emit(30 + int(pct * 0.08), etapa, msg)
        layout_ia = gerar_layout_dinamico_ia(conteudo, modelo_usado, progress_callback=layout_cb)

    prompt_visual_final = montar_prompt_visual(conteudo, layout_ia=layout_ia)
    icone_usado = icone_para_conteudo(conteudo)
    pasta_post = preparar_pasta_post()

    fundo_root_path = str(ULTIMO_FUNDO_PATH)
    fundo_post_path = pasta_post / "fundo.png"
    card_post_path = pasta_post / "card.png"
    checkpoint_usado: str | None = None
    fundo_utilizado: Path | None = None
    fundo_para_card: str | None = None
    comfyui_erro: str | None = None

    if usar_comfyui:
        try:
            if servidor_disponivel():
                checkpoints = listar_checkpoints()
                if not checkpoints:
                    raise RuntimeError("Nenhum checkpoint encontrado no ComfyUI.")

                checkpoint_usado = (
                    checkpoint_escolhido if checkpoint_escolhido in checkpoints
                    else (CHECKPOINT_PADRAO if CHECKPOINT_PADRAO in checkpoints else checkpoints[0])
                )

                comfy_inicio = 39 if layout_ia else 34
                comfy_faixa = 44 if layout_ia else 49
                emit(comfy_inicio, "COMFYUI", "Enviando cena para o gerador de imagem")

                def comfy_cb(pct: int, etapa: str):
                    emit(comfy_inicio + int(pct * comfy_faixa / 100), "COMFYUI", etapa)

                gerar_imagem(
                    prompt=prompt_visual_final,
                    output_path=fundo_root_path,
                    ckpt_name=checkpoint_usado,
                    timeout_total=900,
                    width=512,
                    height=768,
                    progress_callback=comfy_cb,
                )
                shutil.copy2(ULTIMO_FUNDO_PATH, fundo_post_path)
                fundo_utilizado = fundo_post_path
                fundo_para_card = fundo_root_path
            else:
                comfyui_erro = "ComfyUI não está acessível. Card criado com fundo padrão."
        except Exception as exc:
            comfyui_erro = str(exc)
    else:
        comfyui_erro = "Geração de imagem desativada pelo usuário."

    emit(84, "CARD", f"Aplicando template {template_usado}")

    def card_cb(pct: int, etapa: str, msg: str):
        emit(84 + int(pct * 0.12), etapa, msg)

    caminho = gerar_card(
        titulo=conteudo["titulo"],
        corpo=conteudo["corpo"],
        destaque=conteudo["destaque"],
        selo_visual=conteudo["selo_visual"],
        output_path=str(ULTIMO_CARD_PATH),
        template=template_usado,
        fundo_path=fundo_para_card,
        icone=icone_usado,
        layout_ia=layout_ia,
        marca_visual=conteudo.get("marca_visual") or "STUDIOLAB",
        rodape_visual=conteudo.get("rodape_visual") or "",
        progress_callback=card_cb,
    )

    shutil.copy2(Path(caminho), card_post_path)
    salvar_metadados_post(
        pasta_post=pasta_post,
        conteudo=conteudo,
        modelo_ia=modelo_usado,
        prompt_visual_final=prompt_visual_final,
        checkpoint_usado=checkpoint_usado,
        card_path=card_post_path,
        fundo_path=fundo_utilizado,
        template_usado=template_usado,
        icone_usado=icone_usado,
        layout_ia=layout_ia,
    )

    emit(100, "CONCLUÍDO", "Post pronto")

    return {
        "conteudo": conteudo,
        "modelo_ia": modelo_usado,
        "prompt_visual_final": prompt_visual_final,
        "template_usado": template_usado,
        "layout_ia": layout_ia,
        "icone_usado": icone_usado,
        "checkpoint_usado": checkpoint_usado,
        "comfyui_erro": comfyui_erro,
        "pasta_post": str(pasta_post),
        "card_path": str(card_post_path),
        "fundo_path": str(fundo_utilizado) if fundo_utilizado else None,
        "card_atual_path": str(ULTIMO_CARD_PATH),
    }


if __name__ == "__main__":
    resultado = gerar_post_completo()
    conteudo = resultado["conteudo"]
    print("\n--- conteúdo gerado pela IA ---")
    print(json.dumps(conteudo, indent=2, ensure_ascii=False))
    print(f"\nTemplate: {resultado['template_usado']}")
    if resultado.get("comfyui_erro"):
        print(f"[AVISO] {resultado['comfyui_erro']}")
    print(f"\nCard gerado em {resultado['card_atual_path']}")
    print(f"Post salvo em {resultado['pasta_post']}")
    print(f"\nLegenda para o Instagram:\n{conteudo['legenda_instagram']}")

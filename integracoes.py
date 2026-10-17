from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import re
import threading
import time
from typing import Any

import requests


DEFAULT_CONFIG = {
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": "",
        "allowed_user_ids": [],
        "auto_send_review": True,
    },
    "instagram": {
        "enabled": False,
        "username": "",
        "password": "",
        "auto_publish_on_approval": True,
    },
}


class IntegracoesService:
    def __init__(self, base_dir: Path, posts_dir: Path, site_oficial: str):
        self.base_dir = Path(base_dir)
        self.posts_dir = Path(posts_dir)
        self.site_oficial = site_oficial
        self.data_dir = self.base_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.data_dir / "config_integracoes.json"
        self.instagram_session_path = self.data_dir / "instagram_session.json"
        self._config_lock = threading.RLock()
        self._post_lock = threading.RLock()
        self._publish_lock = threading.Lock()
        self._poll_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_poll_error: str | None = None
        self._telegram_bot_name: str | None = None
        self._telegram_offset: int | None = None
        self._poll_token_fingerprint: str | None = None
        self._ensure_config_file()

    # ------------------------------------------------------------------
    # Configuração
    # ------------------------------------------------------------------
    def _ensure_config_file(self):
        if not self.config_path.exists():
            self._write_config(DEFAULT_CONFIG)

    def _merge_defaults(self, raw: dict | None) -> dict:
        cfg = deepcopy(DEFAULT_CONFIG)
        raw = raw or {}
        for section in ("telegram", "instagram"):
            if isinstance(raw.get(section), dict):
                cfg[section].update(raw[section])
        if not isinstance(cfg["telegram"].get("allowed_user_ids"), list):
            cfg["telegram"]["allowed_user_ids"] = []
        return cfg

    def _read_config(self) -> dict:
        with self._config_lock:
            try:
                raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
            return self._merge_defaults(raw)

    def _write_config(self, cfg: dict):
        with self._config_lock:
            tmp = self.config_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.config_path)

    def public_config(self) -> dict:
        cfg = self._read_config()
        tg = cfg["telegram"]
        ig = cfg["instagram"]
        return {
            "telegram": {
                "enabled": bool(tg.get("enabled")),
                "chat_id": str(tg.get("chat_id") or ""),
                "allowed_user_ids": [str(x) for x in tg.get("allowed_user_ids", [])],
                "auto_send_review": bool(tg.get("auto_send_review", True)),
                "token_saved": bool(tg.get("bot_token")),
                "token_hint": self._mask_secret(str(tg.get("bot_token") or "")),
                "configured": self.telegram_configured(cfg),
                "bot_name": self._telegram_bot_name,
                "polling": bool(self._poll_thread and self._poll_thread.is_alive()),
                "last_error": self._last_poll_error,
            },
            "instagram": {
                "enabled": bool(ig.get("enabled")),
                "username": str(ig.get("username") or ""),
                "auto_publish_on_approval": bool(ig.get("auto_publish_on_approval", True)),
                "password_saved": bool(ig.get("password")),
                "configured": self.instagram_configured(cfg),
                "session_saved": self.instagram_session_path.exists(),
                "active_account": f"@{str(ig.get('username') or '').lstrip('@')}" if str(ig.get("username") or "").strip() else "",
            },
        }

    @staticmethod
    def _mask_secret(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "••••"
        return f"••••{value[-6:]}"

    @staticmethod
    def _parse_user_ids(value: Any) -> list[str]:
        if isinstance(value, list):
            raw = value
        else:
            raw = re.split(r"[,;\s]+", str(value or "").strip())
        out = []
        for item in raw:
            text = str(item).strip()
            if text and re.fullmatch(r"-?\d+", text):
                out.append(text)
        return list(dict.fromkeys(out))

    def save_config(self, payload: dict) -> dict:
        cfg = self._read_config()
        tg_in = payload.get("telegram") if isinstance(payload.get("telegram"), dict) else {}
        ig_in = payload.get("instagram") if isinstance(payload.get("instagram"), dict) else {}

        tg = cfg["telegram"]
        if "enabled" in tg_in:
            tg["enabled"] = bool(tg_in.get("enabled"))
        if "chat_id" in tg_in:
            tg["chat_id"] = str(tg_in.get("chat_id") or "").strip()
        if "allowed_user_ids" in tg_in:
            tg["allowed_user_ids"] = self._parse_user_ids(tg_in.get("allowed_user_ids"))
        if "auto_send_review" in tg_in:
            tg["auto_send_review"] = bool(tg_in.get("auto_send_review"))
        token = str(tg_in.get("bot_token") or "").strip()
        if token:
            tg["bot_token"] = token

        ig = cfg["instagram"]
        if "enabled" in ig_in:
            ig["enabled"] = bool(ig_in.get("enabled"))
        if "username" in ig_in:
            username = str(ig_in.get("username") or "").strip().lstrip("@")
            atual = str(ig.get("username") or "").strip().lstrip("@")
            if atual and username and username.lower() != atual.lower():
                raise ValueError(
                    f"A conta ativa é @{atual}. Use o botão 'Trocar conta' para conectar @{username} com validação segura."
                )
            if not atual:
                ig["username"] = username
        if "auto_publish_on_approval" in ig_in:
            ig["auto_publish_on_approval"] = bool(ig_in.get("auto_publish_on_approval"))
        password = str(ig_in.get("password") or "")
        if password:
            ig["password"] = password

        self._write_config(cfg)
        self.start_telegram_poller()
        return self.public_config()

    def switch_instagram_account(self, payload: dict) -> dict:
        """Troca a conta ativa de forma transacional e só confirma após login válido."""
        username = str((payload or {}).get("username") or "").strip().lstrip("@")
        password = str((payload or {}).get("password") or "")
        if not username:
            raise ValueError("Informe o usuário da nova conta do Instagram.")
        if not password:
            raise ValueError("Informe a senha da nova conta para validar a troca.")

        with self._publish_lock:
            cfg_anterior = self._read_config()
            sessao_anterior = None
            if self.instagram_session_path.exists():
                try:
                    sessao_anterior = self.instagram_session_path.read_bytes()
                except Exception:
                    sessao_anterior = None

            nova_cfg = deepcopy(cfg_anterior)
            ig = nova_cfg["instagram"]
            ig["enabled"] = bool((payload or {}).get("enabled", True))
            ig["username"] = username
            ig["password"] = password
            if "auto_publish_on_approval" in (payload or {}):
                ig["auto_publish_on_approval"] = bool((payload or {}).get("auto_publish_on_approval"))

            try:
                self._write_config(nova_cfg)
                self._remove_instagram_session()
                client = self._instagram_client()
                user_id = getattr(client, "user_id", None)
            except Exception:
                # Rollback completo: credenciais + sessão da conta anterior.
                self._write_config(cfg_anterior)
                self._remove_instagram_session()
                if sessao_anterior:
                    try:
                        self.instagram_session_path.write_bytes(sessao_anterior)
                    except Exception:
                        pass
                raise

            public = self.public_config()
            return {
                "ok": True,
                "username": username,
                "user_id": str(user_id or ""),
                "active_account": f"@{username}",
                "config": public,
            }

    @staticmethod
    def telegram_configured(cfg: dict) -> bool:
        tg = cfg.get("telegram", {})
        return bool(tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"))

    @staticmethod
    def instagram_configured(cfg: dict) -> bool:
        ig = cfg.get("instagram", {})
        return bool(ig.get("enabled") and ig.get("username") and ig.get("password"))

    # ------------------------------------------------------------------
    # Posts / metadata
    # ------------------------------------------------------------------
    @staticmethod
    def post_ref(post_dir: Path) -> str:
        date_part = post_dir.parent.name.replace("-", "")
        time_part = post_dir.name.replace(":", "")
        ref = f"{date_part}{time_part}"
        return ref if re.fullmatch(r"\d{14}", ref) else post_dir.name

    def resolve_post_ref(self, ref: str) -> Path:
        ref = str(ref or "").strip()
        if not re.fullmatch(r"\d{14}", ref):
            raise ValueError("Referência de post inválida.")
        date_part = f"{ref[0:4]}-{ref[4:6]}-{ref[6:8]}"
        time_part = ref[8:14]
        post_dir = (self.posts_dir / date_part / time_part).resolve()
        posts_root = self.posts_dir.resolve()
        if posts_root not in post_dir.parents:
            raise ValueError("Post fora da biblioteca.")
        if not (post_dir / "post.json").exists():
            raise FileNotFoundError("Post não encontrado.")
        return post_dir

    def _read_post(self, post_dir: Path) -> dict:
        path = post_dir / "post.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_post(self, post_dir: Path, data: dict):
        path = post_dir / "post.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def update_publication(self, post_dir: Path, **values) -> dict:
        with self._post_lock:
            data = self._read_post(post_dir)
            publication = data.get("publicacao")
            if not isinstance(publication, dict):
                publication = {}
            publication.update(values)
            publication["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
            data["publicacao"] = publication
            self._write_post(post_dir, data)
            return publication

    def publication_status(self, post_dir: Path) -> dict:
        try:
            data = self._read_post(post_dir)
            publication = data.get("publicacao")
            return publication if isinstance(publication, dict) else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Telegram Bot API
    # ------------------------------------------------------------------
    @staticmethod
    def _telegram_url(token: str, method: str) -> str:
        return f"https://api.telegram.org/bot{token}/{method}"

    def _telegram_json(self, token: str, method: str, data: dict | None = None, timeout: int = 30) -> dict:
        response = requests.post(self._telegram_url(token, method), data=data or {}, timeout=timeout)
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"Telegram retornou HTTP {response.status_code} sem JSON válido.") from exc
        if not response.ok or not payload.get("ok"):
            description = payload.get("description") or f"HTTP {response.status_code}"
            raise RuntimeError(f"Telegram: {description}")
        return payload

    def test_telegram(self) -> dict:
        cfg = self._read_config()
        tg = cfg["telegram"]
        if not (tg.get("bot_token") and tg.get("chat_id")):
            raise RuntimeError("Informe o token do bot e o Chat ID do Telegram.")
        me = self._telegram_json(str(tg["bot_token"]), "getMe")
        bot = me.get("result", {})
        self._telegram_bot_name = bot.get("username") or bot.get("first_name")
        self._telegram_json(
            str(tg["bot_token"]),
            "sendMessage",
            {
                "chat_id": str(tg["chat_id"]),
                "text": "✅ StudioLab conectado. Este chat receberá os posts para validação.",
            },
        )
        self._last_poll_error = None
        self.start_telegram_poller()
        return {"ok": True, "bot": self._telegram_bot_name}

    @staticmethod
    def _instagram_label(value: str) -> str:
        value = str(value or "").strip()
        if not value:
            return ""
        return "@" + value.lstrip("@")

    def _post_identity(self, post: dict) -> tuple[str, str]:
        """Resolve projeto e Instagram usando os metadados do próprio post."""
        cfg = self._read_config()
        ig_cfg = cfg.get("instagram", {}) if isinstance(cfg, dict) else {}
        current_instagram = self._instagram_label(ig_cfg.get("username"))

        instagram = self._instagram_label(
            post.get("instagram") or post.get("contexto_id") or current_instagram
        )

        projeto = ""
        for candidato in (post.get("cliente"), post.get("marca_visual")):
            texto = str(candidato or "").strip()
            if texto:
                projeto = texto
                break

        # Um domínio antigo salvo em site_oficial nunca deve substituir a
        # identidade atual; projeto vem de cliente/marca ou da conta ativa.
        projeto = projeto or instagram or "StudioLab"
        return projeto, instagram

    def _approval_caption(self, post: dict, status: str, extra: str = "") -> str:
        topic = str(post.get("topico") or "Conteúdo")
        title = str(post.get("titulo") or "Sem título")
        highlight = str(post.get("destaque") or "")
        caption = str(post.get("legenda_instagram") or "").strip()
        origem = str(post.get("origem") or "ia")
        midias = (post.get("arquivos") or {}).get("midias") or []
        projeto, instagram = self._post_identity(post)
        instagram_line = f"Instagram: {instagram}\n" if instagram and instagram.lower() != projeto.lower() else ""

        if origem == "manual_upload":
            tipo = "Carrossel manual" if len(midias) > 1 else "Post manual"
            header = (
                "StudioLab · Validação de post\n"
                f"Projeto: {projeto}\n"
                f"{instagram_line}"
                f"Tipo: {tipo}\n"
                f"Mídias: {max(1, len(midias))}\n"
                f"Título interno: {title}\n\n"
            )
        else:
            header = (
                "StudioLab · Validação de post\n"
                f"Projeto: {projeto}\n"
                f"{instagram_line}"
                f"Tópico: {topic}\n"
                f"Título: {title}\n"
                f"Destaque: {highlight}\n\n"
            )
        status_text = f"\n\nStatus: {status}"
        if extra:
            status_text += f"\n{extra}"

        available = 1024 - len(header) - len(status_text)
        if available < 80:
            available = 80
        if len(caption) > available:
            caption = caption[: max(0, available - 1)].rstrip() + "…"
        return header + caption + status_text

    def send_for_review(self, post_dir: Path) -> dict:
        cfg = self._read_config()
        tg = cfg["telegram"]
        if not self.telegram_configured(cfg):
            raise RuntimeError("Telegram ainda não está configurado no StudioLab.")

        atual = self.publication_status(post_dir)
        if atual.get("status") == "aguardando_aprovacao" and atual.get("telegram_message_id"):
            return atual
        if atual.get("status") in {"publicando", "publicado"}:
            raise RuntimeError("Este post já foi aprovado para publicação ou já foi publicado.")

        post = self._read_post(post_dir)
        card_path = post_dir / "card.png"
        if not card_path.exists():
            raise FileNotFoundError("Imagem do card não encontrada.")

        ref = self.post_ref(post_dir)
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Aprovar e publicar", "callback_data": f"ap:{ref}"},
                {"text": "❌ Reprovar", "callback_data": f"rp:{ref}"},
            ]]
        }
        caption = self._approval_caption(post, "⏳ AGUARDANDO APROVAÇÃO")

        with card_path.open("rb") as photo:
            response = requests.post(
                self._telegram_url(str(tg["bot_token"]), "sendPhoto"),
                data={
                    "chat_id": str(tg["chat_id"]),
                    "caption": caption,
                    "reply_markup": json.dumps(keyboard, ensure_ascii=False),
                },
                files={"photo": (card_path.name, photo, "image/png")},
                timeout=60,
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"Telegram retornou HTTP {response.status_code} sem JSON válido.") from exc
        if not response.ok or not payload.get("ok"):
            raise RuntimeError(f"Telegram: {payload.get('description') or response.status_code}")

        message = payload.get("result", {})
        publication = self.update_publication(
            post_dir,
            status="aguardando_aprovacao",
            telegram_enviado_em=datetime.now().isoformat(timespec="seconds"),
            telegram_chat_id=str(tg["chat_id"]),
            telegram_message_id=message.get("message_id"),
            telegram_post_ref=ref,
            erro=None,
        )
        return publication

    def _edit_telegram_status(self, post_dir: Path, status_label: str, extra: str = ""):
        cfg = self._read_config()
        tg = cfg["telegram"]
        publication = self.publication_status(post_dir)
        message_id = publication.get("telegram_message_id")
        chat_id = publication.get("telegram_chat_id") or tg.get("chat_id")
        if not tg.get("bot_token") or not message_id or not chat_id:
            return
        try:
            post = self._read_post(post_dir)
            caption = self._approval_caption(post, status_label, extra)
            self._telegram_json(
                str(tg["bot_token"]),
                "editMessageCaption",
                {
                    "chat_id": str(chat_id),
                    "message_id": str(message_id),
                    "caption": caption,
                    "reply_markup": json.dumps({"inline_keyboard": []}),
                },
            )
        except Exception:
            pass

    def start_telegram_poller(self):
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop.clear()
        self._poll_thread = threading.Thread(target=self._telegram_poll_loop, daemon=True, name="telegram-poller")
        self._poll_thread.start()

    def _telegram_poll_loop(self):
        while not self._stop.is_set():
            cfg = self._read_config()
            tg = cfg["telegram"]
            if not self.telegram_configured(cfg):
                time.sleep(3)
                continue

            token = str(tg["bot_token"])
            fingerprint = token[-12:]
            if fingerprint != self._poll_token_fingerprint:
                self._poll_token_fingerprint = fingerprint
                self._telegram_offset = None
                try:
                    # Long polling e webhook são mutuamente exclusivos.
                    self._telegram_json(token, "deleteWebhook", {"drop_pending_updates": "false"}, timeout=15)
                    me = self._telegram_json(token, "getMe", timeout=15)
                    bot = me.get("result", {})
                    self._telegram_bot_name = bot.get("username") or bot.get("first_name")
                    self._last_poll_error = None
                except Exception as exc:
                    self._last_poll_error = str(exc)
                    time.sleep(5)
                    continue

            try:
                params = {
                    "timeout": 25,
                    "allowed_updates": json.dumps(["callback_query"]),
                }
                if self._telegram_offset is not None:
                    params["offset"] = self._telegram_offset
                payload = self._telegram_json(token, "getUpdates", params, timeout=35)
                self._last_poll_error = None
                for update in payload.get("result", []):
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self._telegram_offset = update_id + 1
                    callback = update.get("callback_query")
                    if callback:
                        self._handle_callback(callback)
            except Exception as exc:
                self._last_poll_error = str(exc)
                time.sleep(4)

    def _callback_authorized(self, callback: dict, cfg: dict) -> bool:
        tg = cfg["telegram"]
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        from_user = callback.get("from") or {}
        if str(chat.get("id")) != str(tg.get("chat_id")):
            return False
        allowed = {str(x) for x in tg.get("allowed_user_ids", []) if str(x).strip()}
        if allowed and str(from_user.get("id")) not in allowed:
            return False
        return True

    def _answer_callback(self, token: str, callback_id: str, text: str, alert: bool = False):
        try:
            self._telegram_json(
                token,
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": text[:180],
                    "show_alert": "true" if alert else "false",
                },
                timeout=10,
            )
        except Exception:
            pass

    def _handle_callback(self, callback: dict):
        cfg = self._read_config()
        tg = cfg["telegram"]
        token = str(tg.get("bot_token") or "")
        callback_id = str(callback.get("id") or "")
        data = str(callback.get("data") or "")

        if not self._callback_authorized(callback, cfg):
            self._answer_callback(token, callback_id, "Você não tem permissão para validar este post.", alert=True)
            return

        match = re.fullmatch(r"(ap|rp):(\d{14})", data)
        if not match:
            self._answer_callback(token, callback_id, "Ação inválida ou expirada.", alert=True)
            return

        action, ref = match.groups()
        try:
            post_dir = self.resolve_post_ref(ref)
        except Exception:
            self._answer_callback(token, callback_id, "Post não encontrado no StudioLab.", alert=True)
            return

        publication = self.publication_status(post_dir)
        current = publication.get("status")
        if current == "publicado":
            self._answer_callback(token, callback_id, "Este post já foi publicado.")
            return
        if current == "publicando":
            self._answer_callback(token, callback_id, "Publicação já está em andamento.")
            return

        approver = callback.get("from") or {}
        approver_name = " ".join(
            [str(approver.get("first_name") or ""), str(approver.get("last_name") or "")]
        ).strip() or str(approver.get("username") or approver.get("id") or "Telegram")

        if action == "rp":
            self.update_publication(
                post_dir,
                status="rejeitado",
                rejeitado_em=datetime.now().isoformat(timespec="seconds"),
                validado_por=approver_name,
                telegram_user_id=approver.get("id"),
                erro=None,
            )
            self._answer_callback(token, callback_id, "Post reprovado. Nada será publicado.")
            self._edit_telegram_status(post_dir, "❌ REPROVADO", f"Validado por: {approver_name}")
            return

        self.update_publication(
            post_dir,
            status="aprovado",
            aprovado_em=datetime.now().isoformat(timespec="seconds"),
            validado_por=approver_name,
            telegram_user_id=approver.get("id"),
            erro=None,
        )
        self._answer_callback(token, callback_id, "Post aprovado. StudioLab vai publicar no Instagram.")

        ig_cfg = cfg["instagram"]
        if not (self.instagram_configured(cfg) and ig_cfg.get("auto_publish_on_approval", True)):
            self._edit_telegram_status(
                post_dir,
                "✅ APROVADO",
                "Instagram não está configurado para publicação automática.",
            )
            return

        self._edit_telegram_status(post_dir, "✅ APROVADO · PUBLICANDO…", f"Validado por: {approver_name}")
        threading.Thread(target=self.publish_instagram, args=(post_dir,), daemon=True, name=f"ig-{ref}").start()

    # ------------------------------------------------------------------
    # Instagram / instagrapi
    # ------------------------------------------------------------------
    @staticmethod
    def _instagram_upgrade_error(exc: Exception) -> bool:
        texto = str(exc or "").lower()
        sinais = (
            "needs_upgrade",
            "out of date",
            "upgrade your app",
            "please upgrade your app",
            "version of instagram is out of date",
            "unsupported app version",
            "bloks_versioning_id",
        )
        return any(sinal in texto for sinal in sinais)

    def _remove_instagram_session(self):
        try:
            self.instagram_session_path.unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _new_instagram_client(Client):
        # Instagrapi 3.x: usa o perfil de aplicativo atual mesmo quando
        # existirem dados antigos de versão dentro de uma sessão salva.
        return Client(override_app_version=True)

    def _instagram_client(self):
        cfg = self._read_config()
        ig = cfg["instagram"]
        if not self.instagram_configured(cfg):
            raise RuntimeError("Instagram ainda não está configurado no StudioLab.")

        try:
            from instagrapi import Client
        except Exception as exc:
            raise RuntimeError("Pacote instagrapi não está instalado no ambiente do StudioLab.") from exc

        username = str(ig["username"])
        password = str(ig["password"])
        client = self._new_instagram_client(Client)
        sessao_carregada = False

        if self.instagram_session_path.exists():
            try:
                # Mantém device/session já confiáveis, mas substitui somente
                # o perfil de versão do app pelo perfil atual do Instagrapi.
                client.load_settings(
                    str(self.instagram_session_path),
                    override_app_version=True,
                )
                sessao_carregada = True
            except Exception:
                # Sessão corrompida ou incompatível: será recriada abaixo.
                self._remove_instagram_session()
                client = self._new_instagram_client(Client)

        try:
            client.login(username, password)
        except Exception as exc:
            # Uma sessão antiga pode carregar parâmetros rejeitados pelo
            # Instagram. Em needs_upgrade (ou qualquer falha com sessão já
            # carregada), remove SOMENTE a sessão do Instagram e tenta uma
            # única vez com um cliente limpo e perfil de app atualizado.
            if sessao_carregada or self._instagram_upgrade_error(exc):
                self._remove_instagram_session()
                client = self._new_instagram_client(Client)
                try:
                    client.login(username, password)
                except Exception as retry_exc:
                    if self._instagram_upgrade_error(retry_exc):
                        raise RuntimeError(
                            "Instagram rejeitou o perfil do aplicativo mesmo após atualizar a sessão. "
                            "Confirme que o ambiente do StudioLab está usando instagrapi 3.0.4. "
                            f"Detalhe: {retry_exc}"
                        ) from retry_exc
                    raise
            else:
                raise

        client.dump_settings(str(self.instagram_session_path))
        return client

    def test_instagram(self) -> dict:
        with self._publish_lock:
            client = self._instagram_client()
            user_id = getattr(client, "user_id", None)
            return {"ok": True, "username": self._read_config()["instagram"]["username"], "user_id": str(user_id or "")}

    def publish_instagram(self, post_dir: Path) -> dict:
        with self._publish_lock:
            publication = self.publication_status(post_dir)
            if publication.get("status") == "publicado":
                return publication

            cfg = self._read_config()
            if not self.instagram_configured(cfg):
                publication = self.update_publication(
                    post_dir,
                    status="aprovado",
                    erro="Instagram não configurado.",
                )
                self._edit_telegram_status(post_dir, "✅ APROVADO", "Aguardando configuração do Instagram.")
                return publication

            self.update_publication(
                post_dir,
                status="publicando",
                publicando_em=datetime.now().isoformat(timespec="seconds"),
                erro=None,
            )

            try:
                post = self._read_post(post_dir)
                caption = str(post.get("legenda_instagram") or "").strip()
                arquivos = post.get("arquivos") if isinstance(post.get("arquivos"), dict) else {}
                nomes_midias = [str(nome) for nome in (arquivos.get("midias") or []) if str(nome).strip()]
                caminhos_midias = [post_dir / nome for nome in nomes_midias]

                if caminhos_midias:
                    ausentes = [p.name for p in caminhos_midias if not p.exists()]
                    if ausentes:
                        raise FileNotFoundError(f"Mídias não encontradas: {', '.join(ausentes)}")
                else:
                    card_path = post_dir / "card.png"
                    if not card_path.exists():
                        raise FileNotFoundError("Imagem card.png não encontrada.")
                    caminhos_midias = [card_path]

                client = self._instagram_client()
                if len(caminhos_midias) > 1:
                    media = client.album_upload(caminhos_midias, caption)
                else:
                    media = client.photo_upload(caminhos_midias[0], caption)
                code = str(getattr(media, "code", "") or "")
                pk = str(getattr(media, "pk", "") or "")
                url = f"https://www.instagram.com/p/{code}/" if code else ""
                publication = self.update_publication(
                    post_dir,
                    status="publicado",
                    publicado_em=datetime.now().isoformat(timespec="seconds"),
                    instagram_media_pk=pk,
                    instagram_code=code,
                    instagram_url=url,
                    erro=None,
                )
                self._edit_telegram_status(post_dir, "🚀 PUBLICADO NO INSTAGRAM", url)
                return publication
            except Exception as exc:
                error = str(exc)[:800]
                publication = self.update_publication(
                    post_dir,
                    status="erro_publicacao",
                    erro=error,
                )
                self._edit_telegram_status(post_dir, "⚠️ APROVADO · ERRO AO PUBLICAR", error[:240])
                return publication

    def after_post_generated(self, post_dir: Path) -> dict:
        cfg = self._read_config()
        if self.telegram_configured(cfg) and cfg["telegram"].get("auto_send_review", True):
            try:
                return self.send_for_review(post_dir)
            except Exception as exc:
                return self.update_publication(
                    post_dir,
                    status="erro_telegram",
                    erro=str(exc)[:800],
                )
        return self.update_publication(
            post_dir,
            status="rascunho",
            erro=None,
        )

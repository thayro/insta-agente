import json
import sys
import urllib.error
import urllib.request

COMFYUI_URL = "http://127.0.0.1:8188"


def get_json(endpoint, timeout=10):
    url = COMFYUI_URL.rstrip("/") + endpoint
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Insta-Agente-ComfyUI-Test/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def testar_servidor():
    print("=" * 60)
    print("TESTE COMFYUI - INSTA AGENTE")
    print("=" * 60)
    print(f"\nServidor: {COMFYUI_URL}")

    try:
        stats = get_json("/system_stats")
        print("\n[OK] ComfyUI está acessível.")

        system = stats.get("system", {}) if isinstance(stats, dict) else {}
        if system:
            print(f"SO: {system.get('os', 'não informado')}")
            print(f"Python: {system.get('python_version', 'não informado')}")

        devices = stats.get("devices", []) if isinstance(stats, dict) else []
        if devices:
            print("\nDispositivo(s):")
            for dev in devices:
                nome = dev.get("name", "desconhecido")
                tipo = dev.get("type", "")
                vram_total = dev.get("vram_total")
                texto = f" - {nome}"
                if tipo:
                    texto += f" ({tipo})"
                if isinstance(vram_total, (int, float)) and vram_total > 0:
                    texto += f" | memória: {vram_total / (1024 ** 3):.2f} GB"
                print(texto)

    except urllib.error.URLError as exc:
        print("\n[ERRO] Não foi possível conectar ao ComfyUI.")
        print(f"Detalhe: {exc}")
        print("\nConfirme que o ComfyUI está aberto com:")
        print("  comfy launch -- --cpu")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[ERRO] Falha ao consultar o ComfyUI: {exc}")
        sys.exit(1)


def listar_checkpoints():
    print("\n" + "-" * 60)
    print("CHECKPOINTS")
    print("-" * 60)

    try:
        info = get_json("/object_info/CheckpointLoaderSimple")

        node = info.get("CheckpointLoaderSimple", {})
        input_info = node.get("input", {}).get("required", {}).get("ckpt_name", [])

        checkpoints = []
        if isinstance(input_info, list) and input_info:
            primeiro = input_info[0]
            if isinstance(primeiro, list):
                checkpoints = primeiro

        if checkpoints:
            print(f"\n[OK] {len(checkpoints)} checkpoint(s) encontrado(s):")
            for i, checkpoint in enumerate(checkpoints, 1):
                print(f" {i}. {checkpoint}")
        else:
            print("\n[ATENÇÃO] Nenhum checkpoint foi encontrado.")
            print("\nColoque um modelo .safetensors ou .ckpt em:")
            print(r"  C:\Users\User\Documents\comfy\ComfyUI\models\checkpoints")

    except urllib.error.HTTPError as exc:
        print(f"\n[ERRO] ComfyUI respondeu HTTP {exc.code}.")
    except Exception as exc:
        print(f"\n[ERRO] Não foi possível listar checkpoints: {exc}")


if __name__ == "__main__":
    testar_servidor()
    listar_checkpoints()

    print("\n" + "=" * 60)
    print("Teste concluído.")
    print("=" * 60)

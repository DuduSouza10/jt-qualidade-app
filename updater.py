import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen


def log(msg: str) -> None:
    print(msg, flush=True)


def normalize_version(value: str):
    raw = str(value or "").strip().lower().lstrip("v")
    parts = re.findall(r"\d+", raw)

    if not parts:
        return (0, 0, 0)

    numbers = [int(p) for p in parts[:4]]

    while len(numbers) < 3:
        numbers.append(0)

    return tuple(numbers)


def close_main_app_process(pid: int, timeout: int = 20) -> None:
    if not pid:
        log("Nenhum PID recebido. Vou continuar sem fechar processo.")
        return

    if pid == os.getpid():
        log("PID recebido é o próprio atualizador. Não vou fechar.")
        return

    log(f"Fechando aplicativo principal. PID: {pid}")

    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except Exception as exc:
        log(f"Não consegui executar taskkill: {exc}")

    start = time.time()

    while time.time() - start <= timeout:
        try:
            os.kill(pid, 0)
            time.sleep(0.5)
        except OSError:
            log("Aplicativo principal fechado com sucesso.")
            return
        except Exception:
            time.sleep(0.5)

    log("Não consegui confirmar o fechamento pelo PID, mas vou continuar.")


def load_update_config(config_path: Path) -> Dict[str, Any]:
    default = {
        "owner": "",
        "repo": "",
        "asset_contains": "JMS_Coletor_Waybill",
        "allow_prerelease": False,
        "github_token": "",
    }

    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            default.update(data)
        except Exception as exc:
            raise RuntimeError(f"Não consegui ler update_config.json: {exc}")

    owner = str(default.get("owner", "")).strip()
    repo = str(default.get("repo", "")).strip()

    if not owner or not repo or owner.startswith("SEU_") or repo.startswith("SEU_"):
        raise RuntimeError("Configure owner e repo no update_config.json.")

    return default


def github_headers(token: str = "") -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "JMS-Coletor-Waybill-Updater",
    }

    token = str(token or "").strip()

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def http_get_json(url: str, headers: Dict[str, str]) -> Any:
    request = Request(url, headers=headers, method="GET")

    with urlopen(request, timeout=40) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw)

def download_file(url: str, output_path: Path, headers: Dict[str, str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    request = Request(url, headers=headers, method="GET")

    with urlopen(request, timeout=120) as response:
        total = response.headers.get("Content-Length")
        total_size = int(total) if total and total.isdigit() else 0

        downloaded = 0

        with output_path.open("wb") as file:
            while True:
                chunk = response.read(1024 * 512)

                if not chunk:
                    break

                file.write(chunk)
                downloaded += len(chunk)

                if total_size:
                    percent = int((downloaded / total_size) * 100)
                    print(f"\rBaixando atualização... {percent}%", end="", flush=True)

    print()


def get_latest_release(cfg: Dict[str, Any]) -> Dict[str, Any]:
    owner = str(cfg.get("owner", "")).strip()
    repo = str(cfg.get("repo", "")).strip()
    token = str(cfg.get("github_token", "")).strip()
    allow_prerelease = bool(cfg.get("allow_prerelease", False))

    headers = github_headers(token)

    if allow_prerelease:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        releases_data = http_get_json(url, headers)

        if not isinstance(releases_data, list):
            raise RuntimeError("Resposta inválida do GitHub ao buscar releases.")

        for release in releases_data:
            if not isinstance(release, dict):
                continue

            if not release.get("draft"):
                return release

        raise RuntimeError("Nenhuma release publicada encontrada.")

    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    release_data = http_get_json(url, headers)

    if not isinstance(release_data, dict):
        raise RuntimeError("Resposta inválida do GitHub ao buscar a última release.")

    return release_data

def find_release_asset(release: Dict[str, Any], asset_contains: str) -> Dict[str, Any]:
    assets = release.get("assets") or []
    asset_contains = str(asset_contains or "").lower().strip()

    for asset in assets:
        name = str(asset.get("name") or "")
        lower_name = name.lower()

        if lower_name.endswith(".zip") and asset_contains in lower_name:
            return asset

    for asset in assets:
        name = str(asset.get("name") or "")
        lower_name = name.lower()

        if lower_name.endswith(".zip"):
            return asset

    raise RuntimeError("Nenhum arquivo .zip encontrado na release.")


def find_payload_root(extract_dir: Path, main_folder_name: str, app_exe_name: str) -> Path:
    expected = extract_dir / main_folder_name

    if expected.exists() and expected.is_dir():
        return expected

    candidates = []

    for item in extract_dir.iterdir():
        if item.is_dir():
            if (item / app_exe_name).exists():
                return item

            if (item / "templates").exists() and (item / "static").exists():
                candidates.append(item)

    if len(candidates) == 1:
        return candidates[0]

    if (extract_dir / app_exe_name).exists():
        return extract_dir

    raise RuntimeError(
        f"Não encontrei a pasta '{main_folder_name}' nem o EXE '{app_exe_name}' dentro do ZIP."
    )


def should_skip_item(relative_path: Path) -> bool:
    parts = [p.lower() for p in relative_path.parts]

    if not parts:
        return False

    filename = relative_path.name.lower()

    # Não substitui o próprio atualizador enquanto ele está rodando.
    if filename in {
        "atualizador.exe",
        "updater.exe",
        "updater.py",
    }:
        return True

    # Não sobrescreve dados/configurações do usuário.
    protected_top_level = {
        "config.json",
        "exports",
        "debug_pod_tracking",
        "chrome_jms_profile",
        "logs",
    }

    if parts[0] in protected_top_level:
        return True

    return False


def copy_update_files(source_root: Path, target_dir: Path) -> None:
    log(f"Aplicando atualização em: {target_dir}")

    copied = 0
    skipped = 0

    for source in source_root.rglob("*"):
        if not source.is_file():
            continue

        relative = source.relative_to(source_root)

        if should_skip_item(relative):
            skipped += 1
            continue

        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, 6):
            try:
                shutil.copy2(source, destination)
                copied += 1
                break
            except PermissionError:
                log(f"Arquivo em uso, tentando novamente ({attempt}/5): {destination}")
                time.sleep(2)
            except Exception as exc:
                raise RuntimeError(f"Erro copiando {source} para {destination}: {exc}")

    log(f"Arquivos atualizados: {copied}")
    log(f"Arquivos preservados: {skipped}")


def start_updated_app(app_dir: Path, app_exe_name: str) -> None:
    exe_path = app_dir / app_exe_name

    if not exe_path.exists():
        log(f"Não encontrei o EXE atualizado para abrir: {exe_path}")
        return

    log("Abrindo sistema atualizado...")

    subprocess.Popen(
        [str(exe_path)],
        cwd=str(app_dir),
        close_fds=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--app-exe-name", default="Verificacao_IDs_JT_Express.exe")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--config", required=True)
    parser.add_argument("--main-folder-name", default="JMS_Coletor_Waybill")

    args = parser.parse_args()

    app_dir = Path(args.app_dir).resolve()
    app_exe_name = str(args.app_exe_name)
    config_path = Path(args.config).resolve()
    main_folder_name = str(args.main_folder_name)

    log("========================================")
    log("Atualizador - Qualidade J&T")
    log("========================================")
    log(f"Pasta destino: {app_dir}")
    log(f"EXE principal: {app_exe_name}")
    log(f"Config: {config_path}")
    log("")

    if not app_dir.exists():
        raise RuntimeError(f"Pasta destino não existe: {app_dir}")

    cfg = load_update_config(config_path)

    release = get_latest_release(cfg)

    release_version = str(
        release.get("tag_name")
        or release.get("name")
        or ""
    ).strip()

    log(f"Release encontrada: {release_version}")

    asset = find_release_asset(
        release,
        str(cfg.get("asset_contains") or main_folder_name),
    )

    asset_name = str(asset.get("name") or "")
    download_url = str(asset.get("browser_download_url") or "")

    if not download_url:
        raise RuntimeError("Asset da release não possui browser_download_url.")

    log(f"Arquivo da release: {asset_name}")

    temp_dir = Path(tempfile.mkdtemp(prefix="jms_update_"))
    zip_path = temp_dir / asset_name
    extract_dir = temp_dir / "extracted"

    try:
        log("Baixando versão mais recente...")
        download_file(
            download_url,
            zip_path,
            github_headers(str(cfg.get("github_token", "")).strip()),
        )

        log("Fechando programa principal para aplicar atualização...")
        close_main_app_process(args.pid)

        log("Extraindo pacote...")
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(extract_dir)

        payload_root = find_payload_root(
            extract_dir=extract_dir,
            main_folder_name=main_folder_name,
            app_exe_name=app_exe_name,
        )

        log(f"Conteúdo da atualização encontrado em: {payload_root}")

        copy_update_files(payload_root, app_dir)

        log("")
        log("Atualização concluída com sucesso.")
        start_updated_app(app_dir, app_exe_name)

        return 0

    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log("")
        log("ERRO AO ATUALIZAR:")
        log(str(exc))
        log("")
        input("Pressione ENTER para fechar...")
        raise SystemExit(1)
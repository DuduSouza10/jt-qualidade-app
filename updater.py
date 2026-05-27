import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from tkinter import Tk, StringVar, messagebox
from tkinter import ttk


PRESERVE_NAMES = {
    "config.json",
    "update_config.json",
    "chrome_jms_profile",
    "exports",
    "_update",
}


def resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / relative
    return Path(__file__).resolve().parent / relative


class UpdaterUI:
    def __init__(self):
        self.root = Tk()
        self.root.title("Atualizador - JMS")
        self.root.geometry("520x210")
        self.root.resizable(False, False)

        self.status = StringVar(value="Preparando atualização...")
        self.detail = StringVar(value="Aguarde. Não feche esta janela.")

        frame = ttk.Frame(self.root, padding=22)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Atualização do sistema", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.status, font=("Segoe UI", 10)).pack(anchor="w", pady=(14, 3))
        ttk.Label(frame, textvariable=self.detail, font=("Segoe UI", 9)).pack(anchor="w")

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(22, 0))

    def set_status(self, status: str, detail: str = "", percent=None):
        def apply():
            self.status.set(status)
            if detail:
                self.detail.set(detail)
            if percent is not None:
                self.progress["value"] = max(0, min(100, int(percent)))
        self.root.after(0, apply)

    def info(self, title: str, text: str):
        self.root.after(0, lambda: messagebox.showinfo(title, text))

    def error(self, title: str, text: str):
        self.root.after(0, lambda: messagebox.showerror(title, text))

    def close(self):
        self.root.after(0, self.root.destroy)


def normalize_version(value: str):
    raw = str(value or "").strip().lower().lstrip("v")
    parts = re.findall(r"\d+", raw)
    if not parts:
        return (0, 0, 0)
    numbers = [int(p) for p in parts[:4]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def github_headers(token: str = ""):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "JMS-Coletor-Waybill-Updater",
    }
    token = str(token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def urlopen_json(url: str, headers: dict):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def choose_release(config: dict):
    owner = str(config.get("owner", "")).strip()
    repo = str(config.get("repo", "")).strip()
    token = str(config.get("github_token", "")).strip()
    allow_prerelease = bool(config.get("allow_prerelease", False))

    if not owner or not repo or owner.startswith("SEU_") or repo.startswith("SEU_"):
        raise RuntimeError("Configure owner e repo no update_config.json antes de atualizar.")

    headers = github_headers(token)

    if allow_prerelease:
        releases = urlopen_json(f"https://api.github.com/repos/{owner}/{repo}/releases", headers)
        for release in releases:
            if not release.get("draft"):
                return release, headers
        raise RuntimeError("Nenhuma release publicada foi encontrada.")

    release = urlopen_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest", headers)
    return release, headers


def find_zip_asset(release: dict, config: dict):
    contains = str(config.get("asset_contains", "Verificacao_IDs_JT_Express")).lower().strip()
    assets = release.get("assets") or []

    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(".zip") and contains in name.lower():
            return asset

    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(".zip"):
            return asset

    raise RuntimeError(f"Nenhum ZIP foi encontrado na release {release.get('tag_name') or ''}.")


def download_file(url: str, output: Path, headers: dict, ui: UpdaterUI):
    req = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(req, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or "0")
        downloaded = 0
        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open("wb") as f:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break

                f.write(chunk)
                downloaded += len(chunk)

                if total:
                    percent = downloaded * 100 / total
                    ui.set_status(
                        "Baixando nova versão...",
                        f"{downloaded // 1024 // 1024} MB de {total // 1024 // 1024} MB",
                        percent,
                    )
                else:
                    ui.set_status("Baixando nova versão...", f"{downloaded // 1024 // 1024} MB baixados")


def wait_for_process(pid: int, timeout_seconds: int = 40):
    if not pid:
        time.sleep(2)
        return

    if os.name == "nt":
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x00000000
        WAIT_TIMEOUT = 0x00000102

        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if handle:
            try:
                result = ctypes.windll.kernel32.WaitForSingleObject(handle, timeout_seconds * 1000)
                if result in (WAIT_OBJECT_0, WAIT_TIMEOUT):
                    return
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)

    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            os.kill(pid, 0)
            time.sleep(0.5)
        except Exception:
            return


def safe_remove(path: Path):
    if not path.exists():
        return

    for attempt in range(10):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return
        except PermissionError:
            time.sleep(0.7)
        except FileNotFoundError:
            return

    raise PermissionError(f"Não consegui remover: {path}")


def find_app_root(extract_dir: Path, app_exe_name: str):
    direct = extract_dir / app_exe_name
    if direct.exists():
        return extract_dir

    for child in extract_dir.iterdir():
        if child.is_dir() and (child / app_exe_name).exists():
            return child

    matches = list(extract_dir.rglob(app_exe_name))
    if matches:
        return matches[0].parent

    raise RuntimeError(f"Não encontrei {app_exe_name} dentro do ZIP baixado.")


def copy_update(source_root: Path, app_dir: Path, ui: UpdaterUI):
    preserve = {x.lower() for x in PRESERVE_NAMES}

    ui.set_status("Preparando substituição...", "Preservando login, perfil Chrome e exportações.", 78)

    for child in list(app_dir.iterdir()):
        if child.name.lower() in preserve:
            continue
        safe_remove(child)

    ui.set_status("Copiando arquivos novos...", "Substituindo EXE e dependências.", 86)

    items = list(source_root.iterdir())
    total = max(len(items), 1)

    for i, item in enumerate(items, start=1):
        if item.name.lower() in preserve:
            continue

        destination = app_dir / item.name

        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)

        ui.set_status(
            "Copiando arquivos novos...",
            f"{i} de {total} itens copiados.",
            86 + int((i / total) * 10),
        )


def run_update(args, ui: UpdaterUI):
    app_dir = Path(args.app_dir).resolve()
    config_path = Path(args.config).resolve()
    app_exe_name = args.app_exe_name

    if not app_dir.exists():
        raise RuntimeError(f"Pasta do app não existe: {app_dir}")

    if not config_path.exists():
        raise RuntimeError(f"Arquivo de configuração não existe: {config_path}")

    config = load_json(config_path)

    ui.set_status("Consultando GitHub...", "Buscando a última release publicada.", 5)

    release, headers = choose_release(config)
    asset = find_zip_asset(release, config)

    tag = str(release.get("tag_name") or release.get("name") or "").strip()
    asset_name = str(asset.get("name") or "atualizacao.zip")
    download_url = str(asset.get("browser_download_url") or "").strip()

    if not download_url:
        raise RuntimeError("A release não retornou browser_download_url para o ZIP.")

    work_dir = Path(tempfile.mkdtemp(prefix="jms_update_files_"))
    zip_path = work_dir / asset_name
    extract_dir = work_dir / "extraido"

    ui.set_status("Versão encontrada.", f"Baixando {asset_name} ({tag}).", 12)
    download_file(download_url, zip_path, headers, ui)

    ui.set_status("Extraindo atualização...", "Lendo pacote baixado.", 72)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    source_root = find_app_root(extract_dir, app_exe_name)

    ui.set_status("Fechando versão antiga...", "Aguardando o sistema principal encerrar.", 76)
    wait_for_process(int(args.pid or 0), timeout_seconds=45)

    copy_update(source_root, app_dir, ui)

    new_exe = app_dir / app_exe_name
    if not new_exe.exists():
        raise RuntimeError(f"Atualização copiada, mas não encontrei o novo EXE: {new_exe}")

    ui.set_status("Finalizando...", "Abrindo o sistema atualizado.", 100)
    subprocess.Popen([str(new_exe)], cwd=str(app_dir), close_fds=True)

    ui.info("Atualização concluída", f"Sistema atualizado com sucesso para {tag or 'a nova versão'}.")

    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--app-exe-name", default="Verificacao_IDs_JT_Express.exe")
    parser.add_argument("--pid", default="0")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    ui = UpdaterUI()

    def worker():
        try:
            run_update(args, ui)
            ui.close()
        except Exception as exc:
            ui.set_status("Erro na atualização.", str(exc), 0)
            ui.error("Erro na atualização", str(exc))

    threading.Thread(target=worker, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()

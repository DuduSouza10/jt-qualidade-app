import base64
import csv
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import tempfile
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape
import socket
from werkzeug.serving import make_server

import requests
import webview
from flask import Flask, Response, jsonify, render_template, request
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


JMS_URL = "https://jmsbr.jtjms-br.com/"
WAYBILL_API = "https://gw.jtjms-br.com/servicequality/thirdService/waybill/commonWaybillListByWaybillNos"

LOGIN_USER_XPATH = (
    '//input[contains(@class, "el-input__inner") '
    'and @type="text" '
    'and (contains(@placeholder, "funcionário") '
    'or contains(@placeholder, "员工编号") '
    'or contains(@placeholder, "número"))]'
)

LOGIN_PASS_XPATH = (
    '//input[contains(@class, "el-input__inner") '
    'and @type="password" '
    'and (contains(@placeholder, "senha") '
    'or contains(@placeholder, "密码"))]'
)

LOGIN_USER_SELECTOR = 'input.el-input__inner[placeholder="请输入员工编号"]'
LOGIN_PASS_SELECTOR = 'input.el-input__inner[type="password"][placeholder="请输密码"]'

REMEMBER_BOX_SELECTOR = ".remember-pwd"
REMEMBER_CHECK_SELECTOR = ".remember-pwd .rp-check"

LOGIN_BUTTON_XPATH = (
    '//button[contains(@class, "login-btn") '
    'and .//span[contains(normalize-space(), "Login")]]'
)

DEFAULT_APP_PORT = 5018
APP_PORT = DEFAULT_APP_PORT
MAX_LOGS = 1500

APP_VERSION = "1.0.0"
APP_EXE_NAME = "Verificacao_IDs_JT_Express.exe"
UPDATER_EXE_NAME = "Atualizador.exe"





def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()

# IMPORTANTE:
# Quando roda em EXE, PyInstaller joga templates/static dentro do _MEIPASS.
# Quando roda em Python normal, usa a própria pasta do projeto.
if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS")).resolve()
else:
    RESOURCE_DIR = APP_DIR.resolve()

TEMPLATES_DIR = RESOURCE_DIR / "templates"
STATIC_DIR = RESOURCE_DIR / "static"

CONFIG_FILE = APP_DIR / "config.json"
EXPORTS_DIR = APP_DIR / "exports"
VERSION_FILE = APP_DIR / "version.json"
UPDATE_CONFIG_FILE = APP_DIR / "update_config.json"
UPDATER_EXE_FILE = APP_DIR / UPDATER_EXE_NAME

ROBOT_USER_DATA_DIR = APP_DIR / "chrome_jms_profile"
ROBOT_DEFAULT_PROFILE_DIR = ROBOT_USER_DATA_DIR / "Default"

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR),
    static_url_path="/static",
)


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

state_lock = threading.Lock()
stop_event = threading.Event()

current_driver: Optional[webdriver.Chrome] = None
current_thread: Optional[threading.Thread] = None

state: Dict[str, Any] = {
    "running": False,
    "status": "idle",
    "logs": [],
    "results": [],
    "current": 0,
    "total": 0,
    "started_at": None,
    "finished_at": None,
}


# ============================================================
# CONFIG JSON
# ============================================================

def encode_password(password: str) -> str:
    if not password:
        return ""
    return base64.b64encode(password.encode("utf-8")).decode("ascii")


def decode_password(encoded: str) -> str:
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def default_config() -> Dict[str, Any]:
    return {
        "username": "",
        "password": "",
        "save_password": False,
        "waybills": "",
        "recreate_profile": False,
    }


def load_config() -> Dict[str, Any]:
    cfg = default_config()

    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.update(raw)
        except Exception:
            pass

    if cfg.get("save_password"):
        cfg["password"] = decode_password(str(cfg.get("password_encoded", "")))
    else:
        cfg["password"] = ""

    cfg.pop("password_encoded", None)
    return cfg


def save_config(data: Dict[str, Any]) -> None:
    save_password = bool(data.get("save_password"))

    cfg = {
        "username": str(data.get("username", "")),
        "save_password": save_password,
        "password_encoded": encode_password(str(data.get("password", ""))) if save_password else "",
        "waybills": str(data.get("waybills", "")),
        "recreate_profile": bool(data.get("recreate_profile", False)),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# ESTADO / LOGS
# ============================================================

def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(message: str, level: str = "info") -> None:
    line = {
        "time": now_text(),
        "message": message,
        "level": level,
    }

    with state_lock:
        state["logs"].append(line)

        if len(state["logs"]) > MAX_LOGS:
            state["logs"] = state["logs"][-MAX_LOGS:]


def set_state(**kwargs: Any) -> None:
    with state_lock:
        state.update(kwargs)


def append_result(row: Dict[str, Any]) -> None:
    with state_lock:
        state["results"].append(row)


def snapshot_state() -> Dict[str, Any]:
    with state_lock:
        return json.loads(json.dumps(state, ensure_ascii=False))


def reset_runtime_state(total: int = 0) -> None:
    with state_lock:
        state.update(
            {
                "running": True,
                "status": "running",
                "logs": [],
                "results": [],
                "current": 0,
                "total": total,
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
            }
        )


# ============================================================
# CLONE DO PERFIL DEFAULT DO CHROME
# ============================================================

SKIP_DIRS = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "GrShaderCache",
    "ShaderCache",
    "DawnCache",
    "Crashpad",
    "BrowserMetrics",
    "OptimizationHints",
    "Safe Browsing",
    "File System",
}

SKIP_FILES_PREFIX = (
    "Singleton",
    "lockfile",
)

SKIP_FILES_EXACT = {
    "LOCK",
    "RunningChromeVersion",
}


def get_chrome_user_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    if not local_app_data:
        raise RuntimeError("Não consegui localizar a variável LOCALAPPDATA do Windows.")

    return Path(local_app_data) / "Google" / "Chrome" / "User Data"


def copy_file_tolerant(src: Path, dst: Path) -> None:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    except Exception:
        # Ignora arquivos travados/cache.
        pass


def copy_dir_tolerant(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)

    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        target_root = dst / rel
        target_root.mkdir(parents=True, exist_ok=True)

        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and not d.endswith("Cache")
        ]

        for filename in files:
            if filename in SKIP_FILES_EXACT or filename.startswith(SKIP_FILES_PREFIX):
                continue

            copy_file_tolerant(root_path / filename, target_root / filename)


def ensure_robot_profile(recreate: bool = False) -> None:
    if recreate and ROBOT_USER_DATA_DIR.exists():
        log("♻️ Recriando perfil clonado do Chrome...", "warn")
        shutil.rmtree(ROBOT_USER_DATA_DIR, ignore_errors=True)

    if ROBOT_DEFAULT_PROFILE_DIR.exists():
        log(f"✅ Usando perfil fixo já clonado: {ROBOT_USER_DATA_DIR}")
        return

    chrome_root = get_chrome_user_data_root()
    source_default = chrome_root / "Default"

    if not source_default.exists():
        raise RuntimeError(f"Não encontrei o perfil Default do Chrome em: {source_default}")

    log("📁 Clonando perfil Default do Chrome para o perfil fixo do robô...")

    ROBOT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    local_state = chrome_root / "Local State"

    if local_state.exists():
        copy_file_tolerant(local_state, ROBOT_USER_DATA_DIR / "Local State")

    copy_dir_tolerant(source_default, ROBOT_DEFAULT_PROFILE_DIR)

    log("✅ Perfil clonado com sucesso.")


# ============================================================
# SELENIUM / LOGIN JMS
# ============================================================

def create_chrome_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()

    options.add_argument(f"--user-data-dir={ROBOT_USER_DATA_DIR}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument("--remote-debugging-port=0")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)

    return driver


def local_storage_snapshot(driver: webdriver.Chrome) -> Dict[str, str]:
    try:
        return driver.execute_script(
            """
            const out = {};

            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                out[k] = localStorage.getItem(k);
            }

            return out;
            """
        ) or {}
    except Exception:
        return {}


def clean_token(value: str) -> str:
    value = str(value or "").strip()

    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]

    return value.strip()


def extract_token(storage: Dict[str, str]) -> str:
    preferred_keys = [
        "YL_TOKEN",
        "yl_token",
        "authToken",
        "AuthToken",
        "token",
        "TOKEN",
        "accessToken",
    ]

    for key in preferred_keys:
        value = clean_token(storage.get(key, ""))

        if len(value) > 10:
            return value

    for key, value in storage.items():
        if "token" in key.lower():
            value = clean_token(value)

            if len(value) > 10:
                return value

    return ""


def extract_user_data(storage: Dict[str, str]) -> Dict[str, Any]:
    raw = storage.get("userData") or storage.get("USER_DATA") or ""

    if not raw:
        return {}

    try:
        return json.loads(raw)
    except Exception:
        return {}

def locate_login_inputs(driver: webdriver.Chrome) -> Tuple[Optional[Any], Optional[Any]]:
    def find_here() -> Tuple[Optional[Any], Optional[Any]]:
        user_el = None
        pass_el = None

        users = driver.find_elements(By.XPATH, LOGIN_USER_XPATH)
        passes = driver.find_elements(By.XPATH, LOGIN_PASS_XPATH)

        for item in users:
            try:
                if item.is_displayed() and item.is_enabled():
                    user_el = item
                    break
            except Exception:
                continue

        for item in passes:
            try:
                if item.is_displayed() and item.is_enabled():
                    pass_el = item
                    break
            except Exception:
                continue

        if user_el and pass_el:
            return user_el, pass_el

        # Fallback bruto: pega input texto visível + input password visível.
        all_text_inputs = driver.find_elements(
            By.CSS_SELECTOR,
            'input.el-input__inner[type="text"]'
        )

        all_password_inputs = driver.find_elements(
            By.CSS_SELECTOR,
            'input.el-input__inner[type="password"]'
        )

        for item in all_text_inputs:
            try:
                placeholder = (item.get_attribute("placeholder") or "").lower()

                if item.is_displayed() and item.is_enabled():
                    if "funcion" in placeholder or "员工" in placeholder or "número" in placeholder or "numero" in placeholder:
                        user_el = item
                        break
            except Exception:
                continue

        if not user_el:
            for item in all_text_inputs:
                try:
                    if item.is_displayed() and item.is_enabled():
                        user_el = item
                        break
                except Exception:
                    continue

        for item in all_password_inputs:
            try:
                if item.is_displayed() and item.is_enabled():
                    pass_el = item
                    break
            except Exception:
                continue

        return user_el, pass_el

    try:
        driver.switch_to.default_content()

        user_el, pass_el = find_here()

        if user_el and pass_el:
            return user_el, pass_el

        frames = driver.find_elements(By.TAG_NAME, "iframe") + driver.find_elements(By.TAG_NAME, "frame")

        for frame in frames:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)

                user_el, pass_el = find_here()

                if user_el and pass_el:
                    return user_el, pass_el

            except Exception:
                continue

        driver.switch_to.default_content()
        return None, None

    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        return None, None


def is_login_screen(driver: webdriver.Chrome) -> bool:
    user_el, pass_el = locate_login_inputs(driver)

    exists = user_el is not None and pass_el is not None

    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    return exists


def has_valid_login_data(storage: Dict[str, str]) -> bool:
    token = extract_token(storage)
    user_data = extract_user_data(storage)

    if not token:
        return False

    if not user_data:
        return False

    staff_no = (
        user_data.get("staffNo")
        or user_data.get("staff_no")
        or user_data.get("userCode")
    )

    network_code = (
        user_data.get("networkCode")
        or user_data.get("network_code")
    )

    # Não precisa ter os dois obrigatoriamente, mas precisa ter algum dado real de usuário.
    if not staff_no and not network_code:
        return False

    return True


def set_input_value(driver: webdriver.Chrome, element: Any, value: str) -> None:
    driver.execute_script(
        """
        const input = arguments[0];
        const value = arguments[1];

        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype,
            'value'
        ).set;

        nativeInputValueSetter.call(input, value);

        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
        """,
        element,
        value,
    )

def find_visible_element_by_css(driver: webdriver.Chrome, selector: str) -> Optional[Any]:
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)

        for el in elements:
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue

    except Exception:
        pass

    return None


def find_visible_element_by_xpath(driver: webdriver.Chrome, xpath: str) -> Optional[Any]:
    try:
        elements = driver.find_elements(By.XPATH, xpath)

        for el in elements:
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue

    except Exception:
        pass

    return None


def ensure_remember_account_checked(driver: webdriver.Chrome) -> bool:
    """
    Se o checkbox estiver:
    - rp-check => desmarcado
    - rp-check rp-check-bg => marcado

    A função só clica se estiver desmarcado.
    """
    try:
        check_el = find_visible_element_by_css(driver, REMEMBER_CHECK_SELECTOR)

        if not check_el:
            log("⚠️ Não encontrei o checkbox 'Lembrar da conta'.", "warn")
            return False

        class_name = check_el.get_attribute("class") or ""

        if "rp-check-bg" in class_name:
            log("✅ 'Lembrar da conta' já estava marcado.")
            return True

        remember_box = find_visible_element_by_css(driver, REMEMBER_BOX_SELECTOR)

        if remember_box:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                remember_box,
            )
            time.sleep(0.2)

            try:
                remember_box.click()
            except Exception:
                driver.execute_script("arguments[0].click();", remember_box)

            time.sleep(0.4)

        class_name_after = check_el.get_attribute("class") or ""

        if "rp-check-bg" in class_name_after:
            log("✅ 'Lembrar da conta' marcado.")
            return True

        log("⚠️ Tentei marcar 'Lembrar da conta', mas ele não confirmou visualmente.", "warn")
        return False

    except Exception as exc:
        log(f"⚠️ Erro ao marcar 'Lembrar da conta': {exc}", "warn")
        return False


def click_login_button(driver: webdriver.Chrome) -> bool:
    try:
        login_btn = find_visible_element_by_xpath(driver, LOGIN_BUTTON_XPATH)

        if not login_btn:
            log("❌ Não encontrei o botão Login.", "error")
            return False

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            login_btn,
        )
        time.sleep(0.3)

        try:
            login_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", login_btn)

        log("✅ Botão Login clicado.")
        return True

    except Exception as exc:
        log(f"❌ Erro ao clicar no botão Login: {exc}", "error")
        return False


def fill_login_fields(
    driver: webdriver.Chrome,
    username: str,
    password: str,
) -> bool:
    try:
        user_el, pass_el = locate_login_inputs(driver)

        if not user_el or not pass_el:
            log("❌ Não encontrei os campos de usuário/senha para digitar.", "error")
            return False

        log("🔐 Campos de login encontrados. Digitando usuário e senha...")

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", user_el)
        time.sleep(0.3)

        user_el.click()
        time.sleep(0.2)
        user_el.send_keys(Keys.CONTROL, "a")
        user_el.send_keys(Keys.BACKSPACE)
        time.sleep(0.2)
        set_input_value(driver, user_el, username)

        time.sleep(0.4)

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", pass_el)
        pass_el.click()
        time.sleep(0.2)
        pass_el.send_keys(Keys.CONTROL, "a")
        pass_el.send_keys(Keys.BACKSPACE)
        time.sleep(0.2)
        set_input_value(driver, pass_el, password)

        time.sleep(0.5)

        typed_user = user_el.get_attribute("value") or ""
        typed_pass = pass_el.get_attribute("value") or ""

        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        if not typed_user.strip():
            log("❌ O campo de usuário continuou vazio depois da tentativa de digitar.", "error")
            return False

        if not typed_pass.strip():
            log("❌ O campo de senha continuou vazio depois da tentativa de digitar.", "error")
            return False

        log("✅ Login e senha inseridos corretamente.")

        ensure_remember_account_checked(driver)

        log("🖱️ Clicando no botão Login...")
        click_login_button(driver)

        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        log("🧩 Se aparecer captcha, resolva manualmente no Chrome aberto.")
        log("⏳ Aguardando a tela de login sumir e o userData aparecer...")

        return True

    except Exception as exc:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

        log(f"❌ Falha ao digitar login/senha: {exc}", "error")
        return False


def wait_for_login_screen_or_session(driver: webdriver.Chrome, timeout: int = 45) -> str:
    """
    Retorna:
    - "login" se achou campos de login
    - "session" se achou token + userData válidos e não está na tela de login
    - "unknown" se não conseguiu definir
    """
    start = time.time()
    last_log = 0.0

    while time.time() - start <= timeout and not stop_event.is_set():
        login_screen = is_login_screen(driver)
        storage = local_storage_snapshot(driver)

        if login_screen:
            log("🔐 Tela de login confirmada pelos campos de usuário/senha.")
            return "login"

        if has_valid_login_data(storage):
            log("✅ Sessão válida encontrada: token + userData.")
            return "session"

        if time.time() - last_log >= 6:
            log("⏳ Aguardando JMS carregar tela de login ou sessão válida...")
            last_log = time.time()

        time.sleep(1)

    return "unknown"


def wait_for_jms_token(driver: webdriver.Chrome) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
    last_log = 0.0

    while not stop_event.is_set():
        login_screen = is_login_screen(driver)
        storage = local_storage_snapshot(driver)
        token = extract_token(storage)
        user_data = extract_user_data(storage)

        if login_screen:
            if time.time() - last_log >= 8:
                log("🔎 Campos de login ainda estão na tela.")
                log("🚫 Ignorando token antigo do perfil clonado.")
                log("⏳ Aguardando captcha/login ser concluído...")
                last_log = time.time()

            time.sleep(1)
            continue

        if token and user_data:
            staff_no = (
                user_data.get("staffNo")
                or user_data.get("staff_no")
                or user_data.get("userCode")
            )

            network_code = (
                user_data.get("networkCode")
                or user_data.get("network_code")
            )

            if staff_no or network_code:
                time.sleep(1)

                if not is_login_screen(driver):
                    storage = local_storage_snapshot(driver)
                    token = extract_token(storage)
                    user_data = extract_user_data(storage)

                    if token and user_data:
                        log("🔐 Login confirmado: token + userData encontrados fora da tela de login.")
                        return token, user_data, storage

        if token and not user_data:
            if time.time() - last_log >= 8:
                log("⚠️ Token encontrado, mas sem userData. Considerando token antigo/inválido.", "warn")
                log("⏳ Aguardando login real ser concluído...")
                last_log = time.time()

            time.sleep(1)
            continue

        if time.time() - last_log >= 10:
            log("⏳ Aguardando token válido + userData do JMS...")
            last_log = time.time()

        time.sleep(1)

    raise RuntimeError("Automação interrompida antes de detectar login válido.")


def login_and_get_auth(
    driver: webdriver.Chrome,
    username: str,
    password: str,
) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
    log(f"🌐 Abrindo JMS: {JMS_URL}")
    driver.get(JMS_URL)

    status = wait_for_login_screen_or_session(driver, timeout=45)

    if status == "login":
        log("🔐 Tela de login detectada. Vou inserir usuário e senha agora.")

        if username and password:
            preenchido = fill_login_fields(driver, username, password)

            if not preenchido:
                log("⚠️ Não consegui preencher automaticamente. Preencha manualmente no Chrome.", "warn")
        else:
            log("⚠️ Usuário/senha vazios. Preencha manualmente no Chrome aberto.", "warn")

        return wait_for_jms_token(driver)

    if status == "session":
        storage = local_storage_snapshot(driver)
        token = extract_token(storage)
        user_data = extract_user_data(storage)

        log("✅ Perfil já estava logado de verdade.")
        return token, user_data, storage

    log("⚠️ Não consegui confirmar login nem sessão válida.", "warn")
    log("🔎 Vou tentar localizar os campos de login diretamente...")

    if username and password:
        preenchido = fill_login_fields(driver, username, password)

        if preenchido:
            return wait_for_jms_token(driver)

    log("🔎 Vou aguardar login manual/token válido agora...")
    return wait_for_jms_token(driver)


# ============================================================
# REQUESTS JMS
# ============================================================

def selenium_cookies_to_requests(driver: webdriver.Chrome) -> requests.Session:
    session = requests.Session()

    for cookie in driver.get_cookies():
        name = cookie.get("name")
        value = cookie.get("value")

        if not name or value is None:
            continue

        try:
            session.cookies.set(
                name,
                value,
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )
        except Exception:
            session.cookies.set(name, value)

    return session


def build_headers(
    driver: webdriver.Chrome,
    token: str,
    user_data: Dict[str, Any],
) -> Dict[str, str]:
    try:
        user_agent = driver.execute_script("return navigator.userAgent") or "Mozilla/5.0"
    except Exception:
        user_agent = "Mozilla/5.0"

    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": str(user_agent),
        "Origin": "https://jmsbr.jtjms-br.com",
        "Referer": "https://jmsbr.jtjms-br.com/",
        "authtoken": token,
        "Authorization": token,
        "lang": "PT",
    }

    staff_no = (
        user_data.get("staffNo")
        or user_data.get("staff_no")
        or user_data.get("userCode")
    )

    network_code = (
        user_data.get("networkCode")
        or user_data.get("network_code")
    )

    country_id = (
        user_data.get("countryId")
        or user_data.get("country_id")
    )

    country_code = (
        user_data.get("countryCode")
        or user_data.get("country_code")
    )

    if staff_no:
        headers["staffNo"] = str(staff_no)

    if network_code:
        headers["networkCode"] = str(network_code)

    if country_id:
        headers["countryId"] = str(country_id)

    if country_code:
        headers["countryCode"] = str(country_code)

    return headers


def deep_find(obj: Any, key_name: str) -> Any:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == key_name:
                return value

        for value in obj.values():
            found = deep_find(value, key_name)

            if found is not None:
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = deep_find(item, key_name)

            if found is not None:
                return found

    return None


def deep_find_message(obj: Any) -> str:
    for key in ["msg", "message", "errorMsg", "errorMessage", "messageDesc"]:
        found = deep_find(obj, key)

        if found:
            return str(found)

    return ""


def format_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    return str(value)


def parse_waybills(text: str) -> List[str]:
    found = re.findall(r"\d+", text or "")

    seen = set()
    ids = []

    for item in found:
        if item not in seen:
            seen.add(item)
            ids.append(item)

    return ids


def query_waybill(
    session: requests.Session,
    headers: Dict[str, str],
    waybill: str,
) -> Dict[str, Any]:
    url = f"{WAYBILL_API}?waybillNos={quote(waybill)}"

    row: Dict[str, Any] = {
        "waybillNos": waybill,
        "goodsName": "",
        "insuredAmount": "",
        "status": "",
        "message": "",
        "http_status": "",
    }

    try:
        response = session.get(url, headers=headers, timeout=45)
        row["http_status"] = response.status_code

        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:1000]}

        if response.status_code in (401, 403):
            row["status"] = "erro"
            row["message"] = f"Sem autorização ({response.status_code}). Token pode ter expirado."
            return row

        if not response.ok:
            row["status"] = "erro"
            row["message"] = deep_find_message(data) or f"HTTP {response.status_code}"
            return row

        goods_name = deep_find(data, "goodsName")
        insured_amount = deep_find(data, "insuredAmount")

        row["goodsName"] = format_value(goods_name)
        row["insuredAmount"] = format_value(insured_amount)

        if goods_name is None and insured_amount is None:
            row["status"] = "aviso"
            row["message"] = deep_find_message(data) or "Retornou, mas não encontrei goodsName/insuredAmount no JSON."
        else:
            row["status"] = "ok"
            row["message"] = "Consulta concluída."

        return row

    except requests.RequestException as exc:
        row["status"] = "erro"
        row["message"] = f"Falha na request: {exc}"
        return row


# ============================================================
# WORKER
# ============================================================

def automation_worker(payload: Dict[str, Any]) -> None:
    global current_driver

    driver: Optional[webdriver.Chrome] = None

    try:
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        recreate_profile = bool(payload.get("recreate_profile"))
        ids = parse_waybills(str(payload.get("waybills", "")))

        if not ids:
            raise RuntimeError("Nenhum waybillNos válido foi informado.")

        set_state(total=len(ids))

        log(f"🚀 Iniciando automação para {len(ids)} ID(s).")

        ensure_robot_profile(recreate=recreate_profile)

        if stop_event.is_set():
            raise RuntimeError("Automação interrompida antes de abrir o Chrome.")

        log("🌐 Abrindo Chrome com o perfil fixo clonado...")

        driver = create_chrome_driver()
        current_driver = driver

        token, user_data, _storage = login_and_get_auth(driver, username, password)

        if user_data:
            staff = user_data.get("staffNo") or user_data.get("userCode") or ""
            network = user_data.get("networkCode") or ""
            log(f"👤 Dados detectados no JMS: staffNo={staff} | networkCode={network}")
        else:
            log("ℹ️ Token encontrado, mas userData não foi localizado no localStorage.", "warn")

        session = selenium_cookies_to_requests(driver)
        headers = build_headers(driver, token, user_data)

        log("✅ Login confirmado e dados de autenticação capturados.")
        log("🔒 Fechando Chrome. As consultas continuarão em segundo plano...")

        try:
            driver.quit()
        except Exception:
            pass

        current_driver = None
        driver = None

        log("🌙 Chrome fechado. Iniciando requests em background...")

        for index, waybill in enumerate(ids, start=1):
            if stop_event.is_set():
                log("🛑 Parada solicitada. Encerrando loop de consultas...", "warn")
                set_state(status="stopped")
                break

            set_state(current=index)

            log(f"🔎 Consultando {index}/{len(ids)}: {waybill}")

            row = query_waybill(session, headers, waybill)
            append_result(row)

            if row["status"] == "ok":
                log(f"✅ {waybill} | Conteúdo: {row['goodsName']} | NF: {row['insuredAmount']}")
            else:
                level = "warn" if row["status"] == "aviso" else "error"
                log(f"⚠️ {waybill} | {row['message']}", level)

            time.sleep(0.35)

        if not stop_event.is_set():
            set_state(status="finished", current=len(ids))
            log("🏁 Automação finalizada.")

    except WebDriverException as exc:
        set_state(status="error")
        log(f"❌ ERRO DO CHROME/SELENIUM: {exc}", "error")

    except Exception as exc:
        set_state(status="error")
        log(f"❌ ERRO: {exc}", "error")
        log(traceback.format_exc(), "error")

    finally:
        try:
            if driver:
                driver.quit()
                log("🔒 Chrome do robô fechado.")
        except Exception:
            pass

        current_driver = None

        set_state(
            running=False,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


# ============================================================
# AUTOATUALIZACAO
# ============================================================

def normalize_version(value: str) -> Tuple[int, ...]:
    raw = str(value or "").strip().lower().lstrip("v")
    parts = re.findall(r"\d+", raw)
    if not parts:
        return (0, 0, 0)
    numbers = [int(p) for p in parts[:4]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def current_app_version() -> str:
    if VERSION_FILE.exists():
        try:
            data = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
            version = str(data.get("version") or "").strip()
            if version:
                return version.lstrip("v")
        except Exception:
            pass

    return APP_VERSION.lstrip("v")


def load_update_config() -> Dict[str, Any]:
    default = {
        "owner": "SEU_USUARIO_OU_ORGANIZACAO",
        "repo": "SEU_REPOSITORIO",
        "asset_contains": "Verificacao_IDs_JT_Express",
        "allow_prerelease": False,
        "github_token": "",
    }

    if UPDATE_CONFIG_FILE.exists():
        try:
            raw = json.loads(UPDATE_CONFIG_FILE.read_text(encoding="utf-8"))
            default.update(raw)
        except Exception:
            pass

    return default


def github_headers(token: str = "") -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"JMS-Coletor-Waybill/{current_app_version()}",
    }

    token = str(token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def find_release_asset(release: Dict[str, Any], asset_contains: str) -> Optional[Dict[str, Any]]:
    assets = release.get("assets") or []
    asset_contains = str(asset_contains or "").lower().strip()

    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(".zip") and asset_contains in name.lower():
            return asset

    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(".zip"):
            return asset

    return None


def fetch_latest_release_info() -> Dict[str, Any]:
    cfg = load_update_config()
    owner = str(cfg.get("owner", "")).strip()
    repo = str(cfg.get("repo", "")).strip()
    token = str(cfg.get("github_token", "")).strip()
    allow_prerelease = bool(cfg.get("allow_prerelease", False))
    asset_contains = str(cfg.get("asset_contains", "Verificacao_IDs_JT_Express")).strip()

    if not owner or not repo or owner.startswith("SEU_") or repo.startswith("SEU_"):
        return {
            "ok": False,
            "message": "Configure owner e repo no arquivo update_config.json antes de usar o atualizador.",
        }

    if allow_prerelease:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        response = requests.get(url, headers=github_headers(token), timeout=20)
        response.raise_for_status()
        releases = response.json()

        release = None
        for item in releases:
            if not item.get("draft"):
                release = item
                break

        if not release:
            return {"ok": False, "message": "Nenhuma release publicada foi encontrada."}
    else:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        response = requests.get(url, headers=github_headers(token), timeout=20)
        response.raise_for_status()
        release = response.json()

    asset = find_release_asset(release, asset_contains)

    if not asset:
        return {
            "ok": False,
            "message": f"Nenhum arquivo .zip contendo '{asset_contains}' foi encontrado na última release.",
        }

    latest_version = str(release.get("tag_name") or release.get("name") or "").strip().lstrip("v")
    current_version = current_app_version()
    has_update = normalize_version(latest_version) > normalize_version(current_version)

    return {
        "ok": True,
        "current_version": current_version,
        "latest_version": latest_version,
        "has_update": has_update,
        "release_name": release.get("name") or release.get("tag_name"),
        "release_tag": release.get("tag_name"),
        "published_at": release.get("published_at"),
        "asset_name": asset.get("name"),
        "asset_size": asset.get("size"),
        "download_url": asset.get("browser_download_url"),
    }


def shutdown_after_update_start(delay: float = 1.2) -> None:
    time.sleep(delay)
    os._exit(0)


# ============================================================
# ROTAS FLASK
# ============================================================

@app.get("/")
def index():
    return render_template(
        "index.html",
        cache_id=int(time.time())
    )


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/api/update/check")
def api_update_check():
    try:
        info = fetch_latest_release_info()

        if not info.get("ok"):
            return jsonify(info), 400

        if info.get("has_update"):
            info["message"] = f"Nova versão disponível: v{info.get('latest_version')}"
        else:
            info["message"] = f"Sistema já está atualizado. Versão atual: v{info.get('current_version')}"

        # Não expõe URL/token no front.
        info.pop("download_url", None)
        return jsonify(info)

    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 500
        msg = "Erro ao consultar o GitHub."

        if status == 404:
            msg = "Não encontrei a release no GitHub. Confira owner/repo e se já existe uma Release publicada."
        elif status in (401, 403):
            msg = "Sem permissão para consultar a release. Se o repositório for privado, configure um token no update_config.json."

        return jsonify({"ok": False, "message": msg, "detail": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Erro ao verificar atualização: {exc}"}), 400


@app.post("/api/update/apply")
def api_update_apply():
    if not getattr(sys, "frozen", False):
        return jsonify(
            {
                "ok": False,
                "message": "Atualização automática só funciona no EXE gerado. Em modo Python, use o build_release.bat.",
            }
        ), 400

    if not UPDATER_EXE_FILE.exists():
        return jsonify(
            {
                "ok": False,
                "message": f"Não encontrei {UPDATER_EXE_NAME} na pasta do sistema.",
            }
        ), 400

    try:
        # Faz uma consulta antes para evitar abrir o atualizador sem release válida.
        info = fetch_latest_release_info()
        if not info.get("ok"):
            return jsonify(info), 400

        if not info.get("has_update"):
            return jsonify(
                {
                    "ok": False,
                    "message": f"Você já está na última versão: v{info.get('current_version')}",
                }
            ), 400

        temp_dir = Path(tempfile.mkdtemp(prefix="jms_updater_"))
        temp_updater = temp_dir / UPDATER_EXE_NAME
        shutil.copy2(UPDATER_EXE_FILE, temp_updater)

        args = [
            str(temp_updater),
            "--app-dir",
            str(APP_DIR),
            "--app-exe-name",
            APP_EXE_NAME,
            "--pid",
            str(os.getpid()),
            "--config",
            str(UPDATE_CONFIG_FILE),
        ]

        subprocess.Popen(args, cwd=str(temp_dir), close_fds=True)

        threading.Thread(
            target=shutdown_after_update_start,
            daemon=True,
        ).start()

        return jsonify(
            {
                "ok": True,
                "message": "Atualizador aberto. O sistema vai fechar para concluir a atualização.",
            }
        )

    except Exception as exc:
        return jsonify({"ok": False, "message": f"Erro ao abrir atualizador: {exc}"}), 400


@app.get("/api/config")
def api_get_config():
    return jsonify(load_config())


@app.post("/api/config")
def api_save_config():
    data = request.get_json(silent=True) or {}
    save_config(data)

    return jsonify({"ok": True})


@app.post("/api/start")
def api_start():
    global current_thread

    payload = request.get_json(silent=True) or {}

    with state_lock:
        if state.get("running"):
            return jsonify(
                {
                    "ok": False,
                    "message": "A automação já está rodando.",
                }
            ), 409

    ids = parse_waybills(str(payload.get("waybills", "")))

    if not ids:
        return jsonify(
            {
                "ok": False,
                "message": "Informe pelo menos um waybillNos válido.",
            }
        ), 400

    save_config(payload)

    stop_event.clear()
    reset_runtime_state(total=len(ids))

    current_thread = threading.Thread(
        target=automation_worker,
        args=(payload,),
        daemon=True,
    )

    current_thread.start()

    return jsonify(
        {
            "ok": True,
            "total": len(ids),
        }
    )


@app.post("/api/stop")
def api_stop():
    stop_event.set()
    log("🛑 Parada solicitada pelo usuário.", "warn")

    return jsonify({"ok": True})


@app.get("/api/status")
def api_status():
    return jsonify(snapshot_state())



@app.get("/api/export/preview")
def api_export_preview():
    rows = get_export_rows()
    filename = generate_export_filename()

    return jsonify(
        {
            "ok": True,
            "filename": filename,
            "folder": str(EXPORTS_DIR),
            "total": len(rows),
            "rows": rows,
        }
    )


def generate_export_filename() -> str:
    now = datetime.now()
    date_part = now.strftime("%d-%m-%y")
    time_part = now.strftime("%H-%M")

    return f"ID's exportados - {date_part} - {time_part}.xlsx"


def get_export_rows() -> List[Dict[str, Any]]:
    snap = snapshot_state()
    results = snap.get("results", [])

    rows: List[Dict[str, Any]] = []

    for row in results:
        rows.append(
            {
                "waybillNos": row.get("waybillNos", ""),
                "goodsName": row.get("goodsName", ""),
                "insuredAmount": row.get("insuredAmount", ""),
            }
        )

    return rows


def excel_column_name(index: int) -> str:
    name = ""

    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name

    return name


def clean_xml_text(value: Any) -> str:
    text = "" if value is None else str(value)

    # Remove caracteres que o XML do XLSX não aceita.
    return re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F]",
        "",
        text,
    )


def xlsx_cell_text(value: Any) -> str:
    return xml_escape(clean_xml_text(value))


def make_inline_string_cell(
    row_number: int,
    col_number: int,
    value: Any,
    style_id: int,
) -> str:
    cell_ref = f"{excel_column_name(col_number)}{row_number}"

    return (
        f'<c r="{cell_ref}" t="inlineStr" s="{style_id}">'
        f"<is><t>{xlsx_cell_text(value)}</t></is>"
        f"</c>"
    )


def build_xlsx_sheet_xml(rows: List[Dict[str, Any]]) -> str:
    headers = [
        "Códigos de Rastreio",
        "Conteúdo do Pacote",
        "Valor da NF",
    ]

    xml_rows: List[str] = []

    header_cells = [
        make_inline_string_cell(1, index, header, 1)
        for index, header in enumerate(headers, start=1)
    ]

    xml_rows.append(f'<row r="1" ht="24" customHeight="1">{"".join(header_cells)}</row>')

    for row_index, row in enumerate(rows, start=2):
        values = [
            row.get("waybillNos", ""),
            row.get("goodsName", ""),
            row.get("insuredAmount", ""),
        ]

        cells = [
            make_inline_string_cell(row_index, col_index, value, 2)
            for col_index, value in enumerate(values, start=1)
        ]

        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    last_row = max(len(rows) + 1, 1)

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
           xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
      <selection pane="bottomLeft" activeCell="A2" sqref="A2"/>
    </sheetView>
  </sheetViews>
  <cols>
    <col min="1" max="1" width="26" customWidth="1"/>
    <col min="2" max="2" width="38" customWidth="1"/>
    <col min="3" max="3" width="18" customWidth="1"/>
  </cols>
  <sheetData>
    {''.join(xml_rows)}
  </sheetData>
  <autoFilter ref="A1:C{last_row}"/>
  <pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>
</worksheet>"""


def build_xlsx_styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3">
    <font>
      <sz val="11"/>
      <color theme="1"/>
      <name val="Calibri"/>
      <family val="2"/>
    </font>
    <font>
      <b/>
      <sz val="11"/>
      <color rgb="FFFFFFFF"/>
      <name val="Calibri"/>
      <family val="2"/>
    </font>
    <font>
      <sz val="11"/>
      <color rgb="FF111827"/>
      <name val="Calibri"/>
      <family val="2"/>
    </font>
  </fonts>
  <fills count="3">
    <fill>
      <patternFill patternType="none"/>
    </fill>
    <fill>
      <patternFill patternType="gray125"/>
    </fill>
    <fill>
      <patternFill patternType="solid">
        <fgColor rgb="FFE52336"/>
        <bgColor indexed="64"/>
      </patternFill>
    </fill>
  </fills>
  <borders count="2">
    <border>
      <left/>
      <right/>
      <top/>
      <bottom/>
      <diagonal/>
    </border>
    <border>
      <left style="thin"><color rgb="FFD1D5DB"/></left>
      <right style="thin"><color rgb="FFD1D5DB"/></right>
      <top style="thin"><color rgb="FFD1D5DB"/></top>
      <bottom style="thin"><color rgb="FFD1D5DB"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center"/>
    </xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1">
      <alignment vertical="center"/>
    </xf>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
  <dxfs count="0"/>
  <tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>"""


def create_xlsx_file(rows: List[Dict[str, Any]], output_path: Path) -> None:
    created_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

    root_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Exportação" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

    workbook_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>JMS Automation</Application>
</Properties>"""

    core_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>JMS Automation</dc:creator>
  <cp:lastModifiedBy>JMS Automation</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created_at}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created_at}</dcterms:modified>
</cp:coreProperties>"""

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as xlsx:
        xlsx.writestr("[Content_Types].xml", content_types_xml)
        xlsx.writestr("_rels/.rels", root_rels_xml)
        xlsx.writestr("docProps/app.xml", app_xml)
        xlsx.writestr("docProps/core.xml", core_xml)
        xlsx.writestr("xl/workbook.xml", workbook_xml)
        xlsx.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        xlsx.writestr("xl/styles.xml", build_xlsx_styles_xml())
        xlsx.writestr("xl/worksheets/sheet1.xml", build_xlsx_sheet_xml(rows))


@app.post("/api/export")
def api_export_file():
    rows = get_export_rows()

    if not rows:
        return jsonify(
            {
                "ok": False,
                "message": "Não há resultados para exportar.",
            }
        ), 400

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    filename = generate_export_filename()
    output_path = EXPORTS_DIR / filename

    create_xlsx_file(rows, output_path)

    log(f"📁 XLSX exportado com sucesso: {output_path}")

    return jsonify(
        {
            "ok": True,
            "filename": filename,
            "path": str(output_path),
            "total": len(rows),
        }
    )



def find_free_port(start_port: int = 5017, attempts: int = 80) -> int:
    for port in range(start_port, start_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue

    raise RuntimeError("Não encontrei nenhuma porta livre para iniciar o servidor interno.")


class FlaskServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.ready = threading.Event()
        self.error: Optional[Exception] = None
        self.server = None

    def run(self) -> None:
        try:
            print("=" * 80)
            print("Iniciando servidor interno...")
            print(f"APP_DIR: {APP_DIR}")
            print(f"RESOURCE_DIR: {RESOURCE_DIR}")
            print(f"TEMPLATES_DIR: {TEMPLATES_DIR}")
            print(f"STATIC_DIR: {STATIC_DIR}")
            print(f"CSS EXISTE? {(STATIC_DIR / 'css' / 'style.css').exists()}")
            print(f"JS EXISTE? {(STATIC_DIR / 'js' / 'script.js').exists()}")
            print(f"LOGO EXISTE? {(STATIC_DIR / 'icons' / 'jt-logo.svg').exists()}")
            print(f"PORTA USADA: {self.port}")
            print("=" * 80)

            self.server = make_server(
                host="127.0.0.1",
                port=self.port,
                app=app,
                threaded=True,
            )

            self.ready.set()
            self.server.serve_forever()

        except Exception as exc:
            self.error = exc
            self.ready.set()

            print("=" * 80)
            print("ERRO AO INICIAR O SERVIDOR INTERNO:")
            print(exc)
            print("=" * 80)
            traceback.print_exc()


def wait_flask_ready(port: int, timeout: int = 25) -> bool:
    url = f"http://127.0.0.1:{port}/health"
    start = time.time()

    while time.time() - start < timeout:
        try:
            response = requests.get(url, timeout=1)

            if response.status_code == 200:
                return True

        except Exception:
            pass

        time.sleep(0.3)

    return False


if __name__ == "__main__":
    APP_PORT = find_free_port(DEFAULT_APP_PORT)

    if APP_PORT != DEFAULT_APP_PORT:
        print(f"⚠️ Porta {DEFAULT_APP_PORT} estava ocupada. Usando porta {APP_PORT}.")

    flask_server = FlaskServerThread(APP_PORT)
    flask_server.start()

    print("Aguardando servidor interno iniciar...")

    flask_server.ready.wait(timeout=12)

    if flask_server.error:
        print("ERRO: O servidor interno quebrou antes de iniciar.")
        print(flask_server.error)
        input("Pressione ENTER para fechar...")
        sys.exit(1)

    print("Aguardando servidor interno responder...")

    if not wait_flask_ready(APP_PORT, timeout=25):
        print("ERRO: O servidor interno não respondeu a tempo.")
        print(f"Tente abrir manualmente no navegador para testar: http://127.0.0.1:{APP_PORT}/health")
        input("Pressione ENTER para fechar...")
        sys.exit(1)

    print("Servidor interno OK. Abrindo janela do programa...")

    webview.create_window(
        title="Verificação de ID's - J&T Express",
        url=f"http://127.0.0.1:{APP_PORT}/?v={int(time.time())}",
        width=1280,
        height=820,
        min_size=(1080, 720),
        resizable=True,
        confirm_close=True,
    )

    try:
        webview.start(gui="edgechromium", debug=False)
    except Exception as exc:
        print("ERRO AO ABRIR COM EDGE CHROMIUM:")
        print(exc)
        print()
        print("Tentando abrir com motor padrão...")

        webview.start(debug=False)
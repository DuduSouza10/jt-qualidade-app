import json
import re
import sys
from datetime import datetime
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python set_version.py 1.0.1")

    version = sys.argv[1].strip().lstrip("v")
    if not re.match(r"^\d+\.\d+\.\d+([.-][A-Za-z0-9]+)?$", version):
        raise SystemExit("Versão inválida. Use algo como: 1.0.1")

    root = Path(__file__).resolve().parent

    version_file = root / "version.json"
    version_file.write_text(
        json.dumps(
            {
                "version": version,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    app_file = root / "app.py"
    text = app_file.read_text(encoding="utf-8")
    text = re.sub(
        r'APP_VERSION\s*=\s*"[^"]+"',
        f'APP_VERSION = "{version}"',
        text,
        count=1,
    )
    app_file.write_text(text, encoding="utf-8")

    print(f"Versão atualizada para v{version}")


if __name__ == "__main__":
    main()

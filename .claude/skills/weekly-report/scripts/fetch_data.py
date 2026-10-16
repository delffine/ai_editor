# Скачать данные недели с KZ VPS: архив страниц предложений, логи прогонов и рерайта,
# ленту сайта. python fetch_data.py 2026-10-12 <папка>   (дата — понедельник недели)
# Нужен ssh-ключ ~/.ssh/ai_editor_deploy; адрес — AI_EDITOR_SSH (deploy@<VPS>). Секретов не читает.
import datetime as dt
import json
import subprocess
import sys
import tarfile
import io
import os
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows — cp1252

HOST = os.environ.get("AI_EDITOR_SSH", "deploy@VPS_HOST")
KEY = str(Path.home() / ".ssh" / "ai_editor_deploy")
SITE = "http://www.syzran-small.ru/rss-claude.php?limit=400"  # https с KZ IP режется


def ssh(cmd, binary=False):
    p = subprocess.run(["ssh", "-i", KEY, "-o", "ConnectTimeout=20", HOST, cmd], capture_output=True, timeout=300)
    if p.returncode != 0:
        sys.exit(f"ssh: {p.stderr.decode('utf-8', 'replace')[:300]}")
    return p.stdout if binary else p.stdout.decode("utf-8")


def main():
    d0 = dt.date.fromisoformat(sys.argv[1])
    if d0.weekday() != 0:
        sys.exit("нужна дата понедельника")
    out = Path(sys.argv[2])
    days = [d0 + dt.timedelta(days=i) for i in range(5)]
    months = sorted({f"{d:%Y-%m}" for d in days})
    # страницы недели + последняя страница перед понедельником (её предложения — переходящие)
    names = " ".join(f"archive/digest_{d:%Y-%m-%d}_*" for d in days)
    cmd = ("cd /var/www/ai-editor && { ls archive/digest_*.html | awk -v c=archive/digest_" + f"{d0:%Y-%m-%d}" +
           " '$0 < c' | tail -1; ls " + names + " 2>/dev/null; echo index.html; } | tar czf - -T -")
    tarfile.open(fileobj=io.BytesIO(ssh(cmd, binary=True)), mode="r:gz").extractall(out / "pages", filter="data")
    logs = out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    for d in days:
        (logs / f"run_{d}.log").write_bytes(ssh(f"cat ~/ai-editor/logs/run_{d}.log 2>/dev/null || true", binary=True))
    for m in months:
        (logs / f"rewrite_{m}.log").write_bytes(ssh(f"cat ~/ai-editor/logs/rewrite_{m}.log 2>/dev/null || true", binary=True))
    (out / "site.xml").write_bytes(ssh(f'curl -s -m 90 "{SITE}"', binary=True))
    n = len(list((out / "pages" / "archive").glob("digest_*.html")))
    (out / "meta.json").write_text(json.dumps({"week": str(d0), "fetched_at": dt.datetime.now().isoformat(timespec="minutes"),
                                               "pages": n}), encoding="utf-8")
    print(f"страниц {n}, логов {len(days)}, лента сайта {(out / 'site.xml').stat().st_size} байт -> {out}")


if __name__ == "__main__":
    main()

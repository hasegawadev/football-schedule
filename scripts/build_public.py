"""Package only public assets plus the untracked fetch heartbeat for Pages."""

import argparse
import json
from pathlib import Path
import shutil

from validate_data import utc_timestamp, validate_data
from app_config import enabled_competitions, filter_data, filter_status

ROOT = Path(__file__).resolve().parents[1]
FILES = ("index.html", "site/index.html", "site/app.js", "site/style.css",
         "data/matches.json", "data/fetch_status.json")


def build(source=ROOT, output=None, environment="public"):
    source = Path(source)
    output = Path(output) if output else source / "public"
    competitions = enabled_competitions(environment, source)
    data = filter_data(json.loads((source / "data/matches.json").read_text(encoding="utf-8-sig")), competitions)
    validate_data(data)
    status_path = source / "data/fetch_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"schemaVersion": 1, "competitions": {}}
    if status.get("schemaVersion") != 1 or not isinstance(status.get("competitions"), dict):
        raise ValueError("invalid fetch heartbeat")
    status = filter_status(status, competitions)
    for parts in status["competitions"].values():
        for entry in parts.values():
            for key in ("lastAttemptAt", "lastSuccessAt"):
                if key in entry:
                    utc_timestamp(entry[key])
    if output.exists():
        unexpected = [path for path in output.rglob("*") if path.is_symlink() or path.is_file() and path.relative_to(output).as_posix() not in FILES]
        if unexpected:
            raise ValueError("public output contains unexpected files; refusing to publish")
    for name in FILES:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name in ("data/matches.json", "data/fetch_status.json"):
            value = data if name == "data/matches.json" else status
            target.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        elif name == "site/index.html":
            html = (source / name).read_text(encoding="utf-8")
            marker = 'data-environment="local"'
            if html.count(marker) != 1:
                raise ValueError("expected exactly one source environment marker")
            target.write_text(html.replace(marker, f'data-environment="{environment}"'), encoding="utf-8")
        else:
            shutil.copyfile(source / name, target)
    print(f"Public files packaged: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--environment", choices=("local", "public"), default="public")
    args = parser.parse_args()
    build(output=args.output, environment=args.environment)

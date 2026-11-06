"""Fail before publishing or committing excluded data to the public repository."""
import json
from pathlib import Path
from app_config import EUROPE
from validate_data import validate_data

ROOT = Path(__file__).resolve().parents[1]

def check(root=ROOT):
    data = json.loads((root / "data/matches.json").read_text(encoding="utf-8-sig"))
    validate_data(data)
    for key in ("competitions", "standings", "competitionUpdatedAt"):
        if set(data.get(key, {})) - set(EUROPE):
            raise ValueError(f"Nonpublic competition found in {key}")
    if set(data["competitions"]) != set(EUROPE):
        raise ValueError("Expected all six European competitions")
    print("Release check passed: six European competitions; no excluded snapshots")

if __name__ == "__main__":
    check()

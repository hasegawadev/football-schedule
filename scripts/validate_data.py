"""Schema checks for fetched/served data, independent of the current season."""

from datetime import date, datetime, timedelta
import json
import argparse
from pathlib import Path
import sys


def utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a UTC string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return parsed


def integer(value, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError("invalid integer")


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing text")


def validate_matches(matches, code):
    if not isinstance(matches, list) or not matches:
        raise ValueError("empty/invalid matches")
    ids = set()
    for match in matches:
        integer(match["id"], 1)
        if match["id"] in ids or match["competition"] != code:
            raise ValueError("duplicate ID or competition mismatch")
        ids.add(match["id"])
        if match["matchday"] is not None or code != "CL":
            integer(match["matchday"], 1)
        text(match["stage"])
        text(match["home"])
        text(match["away"])
        if match["utcDate"] is not None:
            utc_timestamp(match["utcDate"])
        if "dateJst" in match:
            date.fromisoformat(match["dateJst"])
        if match["status"] not in {"予定", "試合中", "終了", "延期", "中止"}:
            raise ValueError("unknown match status")
        for side in ("home", "away"):
            score = match["score"][side]
            if score is not None:
                integer(score, 0)
                if match["status"] != "終了":
                    raise ValueError("unfinished match has final score")


def validate_standings(standing, code):
    if not isinstance(standing, dict) or not isinstance(standing.get("groups"), list):
        raise ValueError("invalid standings")
    if not standing["groups"] and code != "CL":
        raise ValueError("empty league standings")
    for group in standing["groups"]:
        text(group["stage"])
        text(group["label"])
        if not isinstance(group["table"], list) or not group["table"]:
            raise ValueError("empty standings group")
        ids = set()
        for row in group["table"]:
            integer(row["position"], 1)
            text(row["team"])
            team_id = row["teamId"]
            if not isinstance(team_id, (str, int)) or isinstance(team_id, bool) or team_id in ids:
                raise ValueError("invalid/duplicate standings team ID")
            ids.add(team_id)
            for field in ("played", "won", "draw", "lost", "goalsFor", "goalsAgainst"):
                integer(row[field], 0)
            integer(row["points"])
            integer(row["goalDifference"])
            if row["played"] != row["won"] + row["draw"] + row["lost"]:
                raise ValueError("inconsistent played games")
            if row["goalDifference"] != row["goalsFor"] - row["goalsAgainst"]:
                raise ValueError("inconsistent goal difference")
    if "updatedAt" in standing:
        utc_timestamp(standing["updatedAt"])


def validate_data(data):
    if not isinstance(data, dict) or not isinstance(data.get("competitions"), dict):
        raise ValueError("invalid data root")
    if data.get("updatedAt") is not None:
        utc_timestamp(data["updatedAt"])
    for code, matches in data["competitions"].items():
        # A fresh checkout may contain an explicit unfetched empty competition.
        if matches == []:
            continue
        validate_matches(matches, code)
    if not isinstance(data.get("standings", {}), dict):
        raise ValueError("invalid standings root")
    for code, standing in data.get("standings", {}).items():
        validate_standings(standing, code)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path("data/matches.json"))
    parser.add_argument("--environment", choices=("local", "public"))
    args = parser.parse_args()
    try:
        data = json.loads(args.path.read_text(encoding="utf-8-sig"))
        if args.environment:
            from app_config import enabled_competitions, filter_data
            data = filter_data(data, enabled_competitions(args.environment))
        validate_data(data)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"Data validation failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    print(f"Data validation passed: {len(data['competitions'])} competitions")
    return 0


if __name__ == "__main__":
    sys.exit(main())

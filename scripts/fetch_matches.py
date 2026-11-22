"""Update each competition independently; preserve good snapshots on failure."""

import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from validate_data import validate_matches, validate_standings
from app_config import enabled_competitions

API_URL = "https://api.football-data.org/v4"
COMPETITIONS = ("PL", "BL1", "PD", "SA", "FL1", "CL")
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "matches.json"
RETRY_DELAYS = (7, 15)
STATUSES = {
    "SCHEDULED": "予定", "TIMED": "予定",
    "IN_PLAY": "試合中", "PAUSED": "試合中", "EXTRA_TIME": "試合中",
    "PENALTY_SHOOTOUT": "試合中", "FINISHED": "終了", "AWARDED": "終了",
    "POSTPONED": "延期", "SUSPENDED": "延期", "CANCELLED": "中止",
}


class FetchError(Exception):
    pass


class PartialFetchError(FetchError):
    """Successful competitions have already been saved before this is raised."""

    def __init__(self, failures, successes, changed):
        self.failures = failures
        self.successes = successes
        self.changed = changed
        super().__init__(f"Update incomplete: failed={','.join(failures)}; successful={','.join(successes) or 'none'}; data_saved={changed}")


def team_display(team):
    team_id = team.get("id")
    if team_id is not None and (type(team_id) is not int or team_id < 1):
        raise ValueError("invalid team id")
    english = team.get("name") or "未定"
    if not isinstance(english, str):
        raise ValueError("invalid team name")
    return team_id, english


def normalize(raw, code):
    """Keep API stage/matchday, never infer a round from the date."""
    try:
        status = STATUSES[raw["status"]]
        match_id = raw["id"]
        matchday = raw["matchday"]
        stage = raw["stage"]
        kickoff = raw["utcDate"]
        home_id, home = team_display(raw["homeTeam"])
        away_id, away = team_display(raw["awayTeam"])
        if raw["competition"]["code"] != code:
            raise ValueError("competition mismatch")
        if type(match_id) is not int or not isinstance(stage, str) or not stage:
            raise ValueError("invalid id/stage")
        # Knockout matchdays and dates may be unavailable before the draw.
        if matchday is not None and (type(matchday) is not int or matchday < 1):
            raise ValueError("invalid matchday")
        if code != "CL" and matchday is None:
            raise ValueError("missing league matchday")
        if kickoff is not None:
            parsed = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError("kickoff must be UTC")
            kickoff = parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
        score = {"home": None, "away": None}
        if status == "終了":
            full_time = raw["score"]["fullTime"]
            score = {"home": full_time["home"], "away": full_time["away"]}
            if any(v is not None and (type(v) is not int or v < 0) for v in score.values()):
                raise ValueError("invalid score")
        return {
            "id": match_id, "competition": code, "matchday": matchday,
            "stage": stage, "utcDate": kickoff, "status": status,
            "homeId": home_id, "awayId": away_id,
            "home": home, "away": away, "score": score,
        }
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise FetchError(f"{code}: invalid match data") from exc


def retry_delay(exc, attempt):
    if exc.code == 429 and exc.headers:
        header = exc.headers.get("Retry-After")
        if header is not None:
            try:
                return max(1, min(60, int(str(header).strip())))
            except ValueError:
                pass
    return RETRY_DELAYS[attempt]


def fetch_json(url, api_key, code, label, allow_404=False):
    request = Request(url, headers={"X-Auth-Token": api_key, "Accept": "application/json"})
    prefix = f"{code}: {label}" if label else f"{code}:"
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            with urlopen(request, timeout=40) as response:
                return json.load(response)
        except HTTPError as exc:
            status_code = exc.code
            delay = retry_delay(exc, attempt) if attempt < len(RETRY_DELAYS) else None
            getattr(exc, "close", lambda: None)()
            if allow_404 and status_code == 404:
                return None
            if (status_code == 429 or 500 <= status_code < 600) and delay is not None:
                time.sleep(delay)
                continue
            # Never log request headers, credentials or remote response bodies.
            raise FetchError(f"{prefix} API HTTP {status_code}") from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise FetchError(f"{prefix} request failed ({type(exc).__name__})") from None


def fetch_competition(code, api_key):
    payload = fetch_json(f"{API_URL}/competitions/{code}/matches", api_key, code, "")
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list) or not payload["matches"]:
        raise FetchError(f"{code}: empty/invalid response")
    matches = [normalize(raw, code) for raw in payload["matches"]]
    if len({m["id"] for m in matches}) != len(matches):
        raise FetchError(f"{code}: duplicate match ids")
    return sorted(matches, key=lambda m: (m["utcDate"] or "9999", m["id"]))


def normalize_standings(payload, code):
    context = "competition.code"
    try:
        if payload["competition"]["code"] != code:
            raise ValueError("competition mismatch")
        groups = []
        context = "standings"
        for group_index, standing in enumerate(payload["standings"]):
            group_path = f"standings[{group_index}]"
            context = f"{group_path}.type"
            if standing["type"] != "TOTAL":
                continue
            table = []
            context = f"{group_path}.table"
            for row_index, raw in enumerate(standing["table"]):
                row_path = f"{group_path}.table[{row_index}]"
                row = {}
                for target, source in (("position", "position"), ("played", "playedGames"),
                                       ("won", "won"), ("draw", "draw"), ("lost", "lost"),
                                       ("points", "points"), ("goalsFor", "goalsFor"),
                                       ("goalsAgainst", "goalsAgainst"), ("goalDifference", "goalDifference")):
                    context = f"{row_path}.{source}"
                    value = raw[source]
                    if type(value) is not int:
                        raise ValueError(f"expected integer, got {type(value).__name__}")
                    row[target] = value
                context = f"{row_path}.position"
                if row["position"] < 1:
                    raise ValueError("expected positive position")
                context = f"{row_path}.team.id"
                row["teamId"] = raw["team"]["id"]
                if type(row["teamId"]) is not int or row["teamId"] < 1:
                    raise ValueError("expected positive team ID")
                context = f"{row_path}.team.name"
                row["team"] = raw["team"]["name"]
                if not isinstance(row["team"], str) or not row["team"].strip():
                    raise ValueError("expected nonempty team name")
                context = f"{row_path}.totals"
                if row["played"] != row["won"] + row["draw"] + row["lost"] or row["goalDifference"] != row["goalsFor"] - row["goalsAgainst"]:
                    raise ValueError("inconsistent standings totals")
                table.append(row)
            context = f"{group_path}.table"
            if not table:
                # A response may include an unpopulated stage beside the current table.
                print(f"{code}: {group_path}.table is empty; skipped")
                continue
            if len({row["teamId"] for row in table}) != len(table):
                raise ValueError("duplicate team IDs in standings table")
            duplicate_positions = len(table) - len({row["position"] for row in table})
            if duplicate_positions:
                # Preserve provider ranks; never invent tie-breakers or renumber clubs.
                print(f"{code}: {group_path}.table has {duplicate_positions} repeated position values; API ranks retained")
            context = f"{group_path}.stage"
            groups.append({"label": standing.get("group") or "総合", "stage": standing["stage"],
                           "table": sorted(table, key=lambda row: row["position"])})
        if not groups and code != "CL":
            raise ValueError("no overall standings")
        context = "season.startDate"
        start = payload["season"]["startDate"][:4]
        context = "season.endDate"
        end = payload["season"]["endDate"][:4]
        return {"season": start if start == end else f"{start}/{end[2:]}",
                "source": "https://www.football-data.org/", "groups": groups,
                "status": "available" if groups else "unavailable"}
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        # Only schema paths, internal validation messages and types are logged.
        # Remote response bodies and authentication headers are never printed.
        reason = "required field missing" if isinstance(exc, KeyError) else str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        raise FetchError(f"{code}: invalid standings data at {context} ({reason})") from exc


def fetch_standings(code, api_key):
    payload = fetch_json(f"{API_URL}/competitions/{code}/standings", api_key, code, "standings", allow_404=(code == "CL"))
    if payload is None:
        return {"season": "", "source": "https://www.football-data.org/", "groups": [], "status": "not_applicable"}
    return normalize_standings(payload, code)


def atomic_json(output, data):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def content(value):
    """Ignore publication timestamps when comparing meaningful snapshot content."""
    if isinstance(value, dict):
        return {key: content(item) for key, item in value.items() if key != "updatedAt"}
    if isinstance(value, list):
        return [content(item) for item in value]
    return value


def update(codes, api_key, output=OUTPUT, include_standings=False, status_output=None, now=None):
    output = Path(output)
    status_output = Path(status_output) if status_output else output.with_name("fetch_status.json")
    existing = {}
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8-sig"))
            if not isinstance(existing.get("competitions"), dict) or not isinstance(existing.get("standings", {}), dict) or not isinstance(existing.get("competitionUpdatedAt", {}), dict):
                raise ValueError("invalid existing JSON")
        except (ValueError, AttributeError) as exc:
            raise FetchError("Cannot merge existing JSON; existing file preserved") from exc
    try:
        status = json.loads(status_output.read_text(encoding="utf-8-sig"))
        if status.get("schemaVersion") != 1 or not isinstance(status.get("competitions"), dict):
            raise ValueError("invalid fetch status")
    except (OSError, ValueError, AttributeError):
        status = {"schemaVersion": 1, "competitions": {}}
    def timestamp():
        return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds").replace("+00:00", "Z")

    attempted = timestamp()
    data = copy.deepcopy(existing)
    failures, successes = {}, []
    changed = False
    any_success = False
    api_started = False

    def record(code, parts, error=None, completed=None):
        entries = status["competitions"].setdefault(code, {})
        if not isinstance(entries, dict):
            entries = status["competitions"][code] = {}
        for part in parts:
            entry = entries.get(part, {})
            if not isinstance(entry, dict):
                entry = {}
            entry["lastAttemptAt"] = attempted
            if error:
                entry["error"] = error
            else:
                entry.pop("error", None)
                entry["lastSuccessAt"] = completed
                entry["dataUpdatedAt"] = (data.get("competitionUpdatedAt", {}).get(code) or data.get("updatedAt")) if part == "matches" else data["standings"][code].get("updatedAt")
            entries[part] = entry

    def bind_legacy_versions():
        if not changed:
            # Bind legacy snapshots before the file-wide content time advances.
            versions = data.setdefault("competitionUpdatedAt", {})
            for old_code in existing.get("competitions", {}):
                if existing.get("updatedAt"):
                    versions.setdefault(old_code, existing["updatedAt"])

    def apply_matches(code, matches):
        nonlocal changed
        validate_matches(matches, code)
        matches_changed = content(matches) != content(data.get("competitions", {}).get(code))
        updated = timestamp()
        if matches_changed:
            bind_legacy_versions()
            data.setdefault("competitions", {})[code] = matches
            data.setdefault("competitionUpdatedAt", {})[code] = updated
            data["updatedAt"] = updated
            changed = True
        record(code, ("matches",), completed=updated)
        print(f"{code}: {len(matches)} matches fetched; content {'changed' if matches_changed else 'unchanged'}")

    def apply_standings(code, standing):
        nonlocal changed
        if standing is None:
            raise ValueError("missing standings snapshot")
        validate_standings(standing, code)
        standing_changed = content(standing) != content(data.get("standings", {}).get(code))
        updated = timestamp()
        if standing_changed:
            bind_legacy_versions()
            data.setdefault("standings", {})[code] = {**standing, "updatedAt": updated}
            data["updatedAt"] = updated
            changed = True
        record(code, ("standings",), completed=updated)
        print(f"{code}: {sum(len(group['table']) for group in standing['groups'])} standings rows fetched")

    def format_error(operation, exc):
        # Isolate unexpected parser/schema errors too; never dump remote bodies/headers.
        return str(exc) if isinstance(exc, FetchError) else f"{operation} failed ({type(exc).__name__})"

    for code in dict.fromkeys(codes):
        attempted = timestamp()
        parts = ("matches", "standings") if include_standings else ("matches",)
        part_failures = {}
        if not api_key:
            reason = "FOOTBALL_DATA_API_KEY environment variable is required"
            for part in parts:
                part_failures[part] = reason
            record(code, parts, reason)
            print(f"ERROR {code}: {reason}; keeping previous {code} data", file=sys.stderr)
        else:
            try:
                if api_started:
                    time.sleep(7)
                api_started = True
                operation = "match fetch"
                matches = fetch_competition(code, api_key)
                operation = "match validation"
                apply_matches(code, matches)
            except Exception as exc:
                reason = format_error(operation, exc)
                part_failures["matches"] = reason
                record(code, ("matches",), reason)
                print(f"ERROR {code}: {reason}; keeping previous {code} matches", file=sys.stderr)
            if include_standings:
                try:
                    time.sleep(7)
                    operation = "standings fetch"
                    standing = fetch_standings(code, api_key)
                    operation = "standings validation"
                    apply_standings(code, standing)
                except Exception as exc:
                    reason = format_error(operation, exc)
                    part_failures["standings"] = reason
                    record(code, ("standings",), reason)
                    print(f"ERROR {code}: {reason}; keeping previous {code} standings", file=sys.stderr)

        if len(part_failures) < len(parts):
            any_success = True
        if part_failures:
            failures[code] = "; ".join(dict.fromkeys(part_failures.values()))
        else:
            successes.append(code)

    if changed:
        atomic_json(output, data)
        print(f"Saved JSON: {output}")
    elif any_success:
        print("Successful fetches have no content changes; matches.json left unchanged")
    else:
        print("All requested competitions failed; matches.json left unchanged", file=sys.stderr)
    # This heartbeat is deployed/cached separately and is never committed to Git.
    status["lastAttemptAt"] = attempted
    atomic_json(status_output, status)
    if failures:
        raise PartialFetchError(failures, successes, changed)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("local", "public"), default=os.environ.get("FOOTBALL_SCHEDULE_ENV", "local"))
    parser.add_argument("--competitions", nargs="+", choices=COMPETITIONS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--matches-only", action="store_true", help="Skip European standings requests")
    args = parser.parse_args()
    try:
        allowed = enabled_competitions(args.environment)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Invalid environment configuration ({type(exc).__name__})", file=sys.stderr)
        return 1
    codes = args.competitions or list(allowed)
    if any(code not in allowed for code in codes):
        parser.error(f"Competition is disabled in the {args.environment} environment")
    api_key = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
    try:
        update(list(dict.fromkeys(codes)), api_key, args.output, include_standings=not args.matches_only)
    except (FetchError, OSError) as exc:
        print(str(exc) if isinstance(exc, FetchError) else "Cannot write JSON; update failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

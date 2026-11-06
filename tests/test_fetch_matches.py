"""Offline API contract tests. Fixtures are synthetic, never real fixtures."""

import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_matches as fetcher


def match(code="PL", match_id=1, status="FINISHED", matchday=1, stage="REGULAR_SEASON"):
    return {
        "id": match_id, "competition": {"code": code}, "matchday": matchday,
        "stage": stage, "utcDate": "2026-11-06T20:00:00Z", "status": status,
        "homeTeam": {"id": 900001, "name": "Test Home FC"}, "awayTeam": {"id": 900002, "name": "Test Away AFC"},
        "score": {"fullTime": {"home": 2, "away": 1}},
    }


def response(code="PL"):
    return io.StringIO(json.dumps({"matches": [match(code), match(code, 2, "TIMED", 2)]}))


class FetchTests(unittest.TestCase):
    def test_one_competition_api_to_json(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matches.json"
            with patch.object(fetcher, "urlopen", return_value=response()) as request:
                data = fetcher.update(["PL"], "test-placeholder", output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), data)
            self.assertEqual(data["competitions"]["PL"][0]["score"], {"home": 2, "away": 1})
            self.assertEqual(data["competitions"]["PL"][1]["score"], {"home": None, "away": None})
            self.assertTrue(data["updatedAt"].endswith("Z"))
            self.assertNotIn("test-placeholder", output.read_text(encoding="utf-8"))
            self.assertEqual(request.call_args.args[0].full_url, "https://api.football-data.org/v4/competitions/PL/matches")

    def test_failure_preserves_existing_bytes(self):
        failures = [HTTPError("https://api.football-data.org", 403, "Forbidden", {}, None),
                    HTTPError("https://api.football-data.org", 429, "Rate limited", {}, None)]
        for error in failures:
            with self.subTest(error=error.code), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "matches.json"
                original = json.dumps({"competitions":{"PL":[fetcher.normalize(match(),"PL")]}}).encode()
                output.write_bytes(original)
                with patch.object(fetcher, "urlopen", side_effect=error), self.assertRaises(fetcher.FetchError):
                    fetcher.update(["PL"], "test-placeholder", output)
                self.assertEqual(output.read_bytes(), original)

    def test_unknown_status_and_invalid_round_rejected(self):
        for raw in [dict(match(), status="UNKNOWN"), dict(match(), matchday=None)]:
            with self.assertRaises(fetcher.FetchError):
                fetcher.normalize(raw, "PL")

    def test_all_statuses(self):
        for status, expected in fetcher.STATUSES.items():
            result = fetcher.normalize(match(status=status), "PL")
            self.assertEqual(result["status"], expected)
            if expected != "終了":
                self.assertEqual(result["score"], {"home": None, "away": None})

    def test_empty_response_is_not_written(self):
        with patch.object(fetcher, "urlopen", return_value=io.StringIO('{"matches":[]}')):
            with self.assertRaises(fetcher.FetchError):
                fetcher.fetch_competition("PL", "test-placeholder")

    def test_six_competitions_and_spacing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matches.json"
            with patch.object(fetcher, "urlopen", side_effect=[response(code) for code in fetcher.COMPETITIONS]), patch.object(fetcher.time, "sleep") as sleep:
                data = fetcher.update(fetcher.COMPETITIONS, "test-placeholder", output)
            self.assertEqual(set(data["competitions"]), set(fetcher.COMPETITIONS))
            self.assertEqual(sleep.call_count, 5)
            self.assertTrue(all(call.args == (7,) for call in sleep.call_args_list))

    def test_partial_failure_updates_success_and_keeps_failed_competition(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "matches.json"
            old_bl1 = [fetcher.normalize(match("BL1"),"BL1")]
            output.write_text(json.dumps({"competitions":{"BL1":old_bl1}}),encoding="utf-8")
            with patch.object(fetcher, "urlopen", side_effect=[response("PL"), OSError("network error")]), patch.object(fetcher.time, "sleep"):
                with self.assertRaises(fetcher.FetchError):
                    fetcher.update(["PL","BL1"], "test-placeholder", output)
            saved=json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["competitions"]["BL1"],old_bl1)
            self.assertEqual(len(saved["competitions"]["PL"]),2)

    def test_cl_nullable_knockout_fields(self):
        raw = match("CL", stage="FINAL", matchday=None)
        raw["utcDate"] = None
        result = fetcher.normalize(raw, "CL")
        self.assertIsNone(result["matchday"])
        self.assertIsNone(result["utcDate"])

    def test_missing_key_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"matches.json"
            with patch.dict(fetcher.os.environ, {}, clear=True), patch.object(fetcher.sys, "argv", ["fetch_matches.py","--competitions","PL","--output",str(output)]), patch.object(fetcher,"urlopen") as request:
                self.assertEqual(fetcher.main(), 1)
                request.assert_not_called()
            self.assertFalse(output.exists())

    def test_known_ids_also_keep_english_names(self):
        raw = match("CL")
        raw["homeTeam"] = {"id": 65, "name": "Changed API Spelling FC"}
        raw["awayTeam"] = {"id": 5, "name": "Changed Bayern Spelling"}
        result = fetcher.normalize(raw, "CL")
        self.assertEqual(result["home"], "Changed API Spelling FC")
        self.assertEqual(result["away"], "Changed Bayern Spelling")
        self.assertEqual((result["homeId"], result["awayId"]), (65, 5))

    def test_unknown_ids_keep_english_names(self):
        raw = match()
        raw["homeTeam"] = {"id": 999999, "name": "Manchester City FC"}
        result = fetcher.normalize(raw, "PL")
        self.assertEqual(result["home"], "Manchester City FC")

    def test_english_names_and_ids_reach_json(self):
        raw = match()
        raw["homeTeam"] = {"id": 65, "name": "Manchester City FC"}
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(stream):
            output = Path(directory) / "matches.json"
            with patch.object(fetcher, "urlopen", return_value=io.StringIO(json.dumps({"matches": [raw]}))):
                fetcher.update(["PL"], "test-placeholder", output)
            saved = json.loads(output.read_text(encoding="utf-8"))["competitions"]["PL"][0]
        self.assertEqual(saved["homeId"], 65)
        self.assertEqual(saved["home"], "Manchester City FC")
        self.assertEqual(saved["away"], "Test Away AFC")
        self.assertTrue(stream.getvalue().startswith("PL: 1 matches fetched"))
        self.assertNotIn("[要確認]", stream.getvalue())


if __name__ == "__main__":
    unittest.main()

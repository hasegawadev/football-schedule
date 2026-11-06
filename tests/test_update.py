"""Update orchestration tests: no network and no dependency on real cached data."""

import copy
from contextlib import redirect_stderr
from datetime import datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import fetch_matches as fetcher
from test_fetch_matches import match
from test_standings import standings
from validate_data import validate_data

OLD = "2026-11-01T00:00:00Z"
NOW = datetime.fromisoformat("2026-11-06T00:00:00+00:00")


def matches(code, score=2):
    raw=match(code); raw["score"]["fullTime"]["home"]=score
    return [fetcher.normalize(raw,code)]


def ranking(code, points=7):
    value=fetcher.normalize_standings(standings(code),code)
    value["groups"][0]["table"][0]["points"]=points
    return value


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"matches.json"
        self.status=self.path.with_name("fetch_status.json")
        self.old={"updatedAt":OLD,"competitions":{},"standings":{},"competitionUpdatedAt":{}}
        heartbeat={"schemaVersion":1,"competitions":{}}
        for code in ("PL","CL","SA"):
            self.old["competitions"][code]=matches(code)
            self.old["standings"][code]={**ranking(code),"updatedAt":OLD}
            self.old["competitionUpdatedAt"][code]=OLD
            heartbeat["competitions"][code]={part:{"lastSuccessAt":OLD,"lastAttemptAt":OLD,"dataUpdatedAt":OLD} for part in ("matches","standings")}
        self.path.write_text(json.dumps(self.old,indent=4),encoding="utf-8")
        self.status.write_text(json.dumps(heartbeat),encoding="utf-8")

    def load(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def heartbeat(self):
        return json.loads(self.status.read_text(encoding="utf-8"))

    def test_all_success_saves_valid_snapshots(self):
        with patch.object(fetcher,"fetch_competition",side_effect=lambda c,k:matches(c,3)),patch.object(fetcher,"fetch_standings",side_effect=lambda c,k:ranking(c,9)),patch.object(fetcher.time,"sleep"):
            result=fetcher.update(["PL","CL"],"test-placeholder",self.path,True,now=NOW)
        validate_data(result)
        self.assertEqual(self.load()["competitions"]["PL"][0]["score"]["home"],3)
        self.assertEqual(self.load()["standings"]["CL"]["groups"][0]["table"][0]["points"],9)

    def test_middle_failure_does_not_prevent_later_competition(self):
        def rank(code,key):
            if code=="CL": raise fetcher.FetchError("CL: HTTP 403")
            return ranking(code,9)
        logs=io.StringIO()
        with patch.object(fetcher,"fetch_competition",side_effect=lambda c,k:matches(c,3)),patch.object(fetcher,"fetch_standings",side_effect=rank),patch.object(fetcher.time,"sleep"),redirect_stderr(logs):
            with self.assertRaises(fetcher.PartialFetchError) as raised:
                fetcher.update(["PL","CL","SA"],"test-placeholder",self.path,True,now=NOW)
        saved=self.load()
        self.assertEqual(saved["competitions"]["CL"],self.old["competitions"]["CL"])
        self.assertEqual(saved["standings"]["CL"],self.old["standings"]["CL"])
        self.assertEqual(saved["competitionUpdatedAt"]["CL"],OLD)
        self.assertEqual(saved["competitions"]["SA"][0]["score"]["home"],3)
        self.assertEqual(raised.exception.successes,["PL","SA"])
        self.assertIn("CL: HTTP 403",logs.getvalue())
        status=self.heartbeat()["competitions"]
        self.assertEqual(status["CL"]["matches"]["lastSuccessAt"],OLD)
        self.assertEqual(status["PL"]["standings"]["lastSuccessAt"],"2026-11-06T00:00:00Z")
        validate_data(saved)

    def test_all_failure_preserves_bytes_and_does_not_advance_success(self):
        before=self.path.read_bytes(); modified=self.path.stat().st_mtime_ns
        with patch.object(fetcher,"fetch_competition",side_effect=fetcher.FetchError("HTTP 429")),patch.object(fetcher.time,"sleep"):
            with self.assertRaises(fetcher.PartialFetchError) as error:
                fetcher.update(["PL","CL"],"test-placeholder",self.path,True,now=NOW)
        self.assertFalse(error.exception.changed)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.path.stat().st_mtime_ns,modified)
        status=self.heartbeat()["competitions"]["PL"]["matches"]
        self.assertEqual(status["lastSuccessAt"],OLD)
        self.assertEqual(status["lastAttemptAt"],"2026-11-06T00:00:00Z")
        self.assertIn("429",status["error"])

    def test_unchanged_data_preserves_file_but_confirms_success(self):
        before=self.path.read_bytes(); modified=self.path.stat().st_mtime_ns
        with patch.object(fetcher,"fetch_competition",return_value=matches("PL")),patch.object(fetcher,"fetch_standings",return_value={**ranking("PL"),"updatedAt":"2099-01-01T00:00:00Z"}),patch.object(fetcher.time,"sleep"):
            result=fetcher.update(["PL"],"test-placeholder",self.path,True,now=NOW)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.path.stat().st_mtime_ns,modified)
        self.assertEqual(result["updatedAt"],OLD)
        self.assertEqual(result["standings"]["PL"]["updatedAt"],OLD)
        entry=self.heartbeat()["competitions"]["PL"]["matches"]
        self.assertEqual(entry["lastSuccessAt"],"2026-11-06T00:00:00Z")
        self.assertEqual(entry["dataUpdatedAt"],OLD)

    def test_no_change_and_failure_is_still_a_failed_run(self):
        before=self.path.read_bytes()
        with patch.object(fetcher,"fetch_competition",side_effect=[matches("PL"),fetcher.FetchError("CL: timeout")]),patch.object(fetcher.time,"sleep"):
            with self.assertRaises(fetcher.PartialFetchError) as error:
                fetcher.update(["PL","CL"],"test-placeholder",self.path,now=NOW)
        self.assertEqual(error.exception.successes,["PL"])
        self.assertIn("CL",error.exception.failures)
        self.assertEqual(self.path.read_bytes(),before)

    def test_standings_only_change_keeps_match_content_time(self):
        with patch.object(fetcher,"fetch_competition",return_value=matches("PL")),patch.object(fetcher,"fetch_standings",return_value=ranking("PL",9)),patch.object(fetcher.time,"sleep"):
            fetcher.update(["PL"],"test-placeholder",self.path,True,now=NOW)
        self.assertEqual(self.load()["competitionUpdatedAt"]["PL"],OLD)
        self.assertEqual(self.load()["standings"]["PL"]["updatedAt"],"2026-11-06T00:00:00Z")
        self.assertEqual(self.heartbeat()["competitions"]["PL"]["matches"]["dataUpdatedAt"],OLD)

    def test_invalid_new_data_is_isolated(self):
        invalid=matches("CL"); invalid[0]["score"]["home"]=-1
        with patch.object(fetcher,"fetch_competition",side_effect=[invalid,matches("SA",4)]),patch.object(fetcher.time,"sleep"):
            with self.assertRaises(fetcher.PartialFetchError): fetcher.update(["CL","SA"],"test-placeholder",self.path,now=NOW)
        self.assertEqual(self.load()["competitions"]["CL"],self.old["competitions"]["CL"])
        self.assertEqual(self.load()["competitions"]["SA"][0]["score"]["home"],4)


    def test_matches_only_does_not_confirm_unfetched_standings(self):
        with patch.object(fetcher,"fetch_competition",return_value=matches("PL")):
            fetcher.update(["PL"],"test-placeholder",self.path,now=NOW)
        self.assertEqual(self.heartbeat()["competitions"]["PL"]["standings"]["lastSuccessAt"],OLD)

    def test_legacy_unchanged_snapshot_version_survives_another_change(self):
        del self.old["competitionUpdatedAt"]
        self.path.write_text(json.dumps(self.old),encoding="utf-8")
        with patch.object(fetcher,"fetch_competition",side_effect=[matches("PL"),matches("SA",4)]),patch.object(fetcher.time,"sleep"):
            fetcher.update(["PL","SA"],"test-placeholder",self.path,now=NOW)
        self.assertEqual(self.load()["competitionUpdatedAt"]["PL"],OLD)
        self.assertEqual(self.heartbeat()["competitions"]["PL"]["matches"]["dataUpdatedAt"],OLD)

    def test_atomic_save_failure_never_writes_a_success_heartbeat(self):
        before=self.path.read_bytes(); old_status=self.status.read_bytes()
        with patch.object(fetcher,"fetch_competition",return_value=matches("PL",4)),patch.object(fetcher.os,"replace",side_effect=OSError("disk full")):
            with self.assertRaises(OSError): fetcher.update(["PL"],"test-placeholder",self.path,now=NOW)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.status.read_bytes(),old_status)
        self.assertEqual(list(self.path.parent.glob("*.tmp")),[])

    def test_partial_failure_cli_exit_is_nonzero(self):
        error=fetcher.PartialFetchError({"CL":"failed"},["PL"],True)
        with patch.object(fetcher,"update",side_effect=error),patch.object(fetcher.sys,"argv",["fetch_matches.py"]):
            self.assertEqual(fetcher.main(),1)

    def test_real_cli_all_failure_exit_preserves_snapshot(self):
        before=self.path.read_bytes()
        environment={key:value for key,value in os.environ.items() if key!="FOOTBALL_DATA_API_KEY"}
        result=subprocess.run([sys.executable,"-X","utf8",str(Path(fetcher.__file__)),"--competitions","PL","--output",str(self.path)],
                              env=environment,capture_output=True,text=True,encoding="utf-8",timeout=10)
        self.assertEqual(result.returncode,1)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertIn("All requested competitions failed",result.stderr)
        self.assertEqual(self.heartbeat()["competitions"]["PL"]["matches"]["lastSuccessAt"],OLD)


if __name__=="__main__": unittest.main()

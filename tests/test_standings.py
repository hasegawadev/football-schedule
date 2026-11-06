import io
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_matches as fetcher
from test_fetch_matches import response, match


def standings(code="PL"):
    return {"competition":{"code":code},"season":{"startDate":"2026-08-01","endDate":"2027-05-31"},
        "standings":[{"type":"HOME","stage":"REGULAR_SEASON","table":[]},
                     {"type":"TOTAL","stage":"LEAGUE_STAGE" if code=="CL" else "REGULAR_SEASON","group":None,
                      "table":[{"position":1,"team":{"id":65,"name":"Manchester City FC"},"playedGames":3,
                                "won":2,"draw":1,"lost":0,"points":7,"goalsFor":8,"goalsAgainst":2,"goalDifference":6}]}]}


class StandingTests(unittest.TestCase):
    def test_cl_empty_stage_is_skipped_but_league_phase_is_saved(self):
        raw = standings("CL")
        raw["standings"].insert(0,{"type":"TOTAL","stage":"QUALIFICATION","group":None,"table":[]})
        result = fetcher.normalize_standings(raw,"CL")
        self.assertEqual(len(result["groups"]),1)
        self.assertEqual(result["groups"][0]["stage"],"LEAGUE_STAGE")
        self.assertEqual(result["status"],"available")

    def test_repeated_positions_keep_provider_ranks_and_row_order(self):
        raw = standings("CL")
        table = raw["standings"][1]["table"]
        second = copy.deepcopy(table[0])
        second["team"] = {"id":66,"name":"Manchester United FC"}
        table.append(second)
        result = fetcher.normalize_standings(raw,"CL")["groups"][0]["table"]
        self.assertEqual([row["position"] for row in result],[1,1])
        self.assertEqual([row["teamId"] for row in result],[65,66])

    def test_duplicate_clubs_are_still_rejected(self):
        raw=standings("CL")
        raw["standings"][1]["table"] *= 2
        with self.assertRaisesRegex(fetcher.FetchError,"duplicate team IDs"):
            fetcher.normalize_standings(raw,"CL")

    def test_completely_empty_cl_is_unavailable_not_a_fabricated_table(self):
        raw=standings("CL"); raw["standings"][1]["table"]=[]
        result=fetcher.normalize_standings(raw,"CL")
        self.assertEqual(result["groups"],[])
        self.assertEqual(result["status"],"unavailable")
        raw["competition"]["code"]="PL"
        with self.assertRaises(fetcher.FetchError): fetcher.normalize_standings(raw,"PL")

    def test_six_competitions_are_saved_when_cl_has_repeated_ranks(self):
        replies=[]
        for code in fetcher.COMPETITIONS:
            raw=standings(code)
            if code=="CL":
                second=copy.deepcopy(raw["standings"][1]["table"][0])
                second["team"]={"id":66,"name":"Manchester United FC"}
                raw["standings"][1]["table"].append(second)
                raw["standings"].insert(0,{"type":"TOTAL","stage":"QUALIFICATION","table":[]})
            replies.extend([response(code),io.StringIO(json.dumps(raw))])
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"matches.json"
            with patch.object(fetcher,"urlopen",side_effect=replies),patch.object(fetcher.time,"sleep"):
                saved=fetcher.update(fetcher.COMPETITIONS,"test-placeholder",output,include_standings=True)
            persisted=json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(persisted,saved)
            self.assertEqual(set(persisted["standings"]),set(fetcher.COMPETITIONS))
            self.assertEqual(len(persisted["standings"]["CL"]["groups"][0]["table"]),2)

    def test_api_overall_table_and_cl_stage(self):
        for code in ("PL","CL"):
            result = fetcher.normalize_standings(standings(code),code)
            self.assertEqual(result["season"],"2026/27")
            self.assertEqual(len(result["groups"]),1)
            self.assertEqual(result["groups"][0]["table"][0]["points"],7)
            self.assertEqual(result["groups"][0]["table"][0]["team"],"Manchester City FC")

    def test_bad_totals_rejected(self):
        raw=standings(); raw["standings"][1]["table"][0]["playedGames"]=9
        with self.assertRaises(fetcher.FetchError): fetcher.normalize_standings(raw,"PL")

    def test_cl_errors_identify_the_exact_field_without_dumping_payload(self):
        raw = standings("CL")
        raw["standings"][1]["table"][0]["won"] = None
        raw["private"] = "must-not-appear-in-output"
        with self.assertRaises(fetcher.FetchError) as error:
            fetcher.normalize_standings(raw,"CL")
        self.assertIn("standings[1].table[0].won",str(error.exception))
        self.assertIn("expected integer, got NoneType",str(error.exception))
        self.assertNotIn("must-not-appear",str(error.exception))
        raw = standings("CL")
        del raw["season"]["endDate"]
        with self.assertRaisesRegex(fetcher.FetchError,"season.endDate"):
            fetcher.normalize_standings(raw,"CL")

    def test_every_match_and_table_request_is_spaced(self):
        with tempfile.TemporaryDirectory() as directory:
            replies=[response("PL"),io.StringIO(json.dumps(standings("PL"))),response("CL"),io.StringIO(json.dumps(standings("CL")))]
            with patch.object(fetcher,"urlopen",side_effect=replies),patch.object(fetcher.time,"sleep") as sleep:
                saved=fetcher.update(["PL","CL"],"test-placeholder",Path(directory)/"matches.json",include_standings=True)
            self.assertEqual([call.args for call in sleep.call_args_list],[(7,),(7,),(7,)])
            self.assertEqual(set(saved["standings"]),{"PL","CL"})

    def test_rank_fetch_failure_preserves_existing_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/"matches.json"
            original=json.dumps({"competitions":{"PL":[fetcher.normalize(match(),"PL")]}}).encode()
            output.write_bytes(original)
            with patch.object(fetcher,"urlopen",side_effect=[response(),HTTPError("https://api.football-data.org",403,"Forbidden",{},None)]),patch.object(fetcher.time,"sleep"):
                with self.assertRaises(fetcher.FetchError): fetcher.update(["PL"],"test-placeholder",output,include_standings=True)
            self.assertEqual(output.read_bytes(),original)


    def test_cl_knockout_404_is_not_a_failed_league_table(self):
        error=HTTPError("https://api.football-data.org",404,"Not Found",{},None)
        with patch.object(fetcher,"urlopen",side_effect=error):
            self.assertEqual(fetcher.fetch_standings("CL","test-placeholder")["groups"],[])
        with patch.object(fetcher,"urlopen",side_effect=error):
            with self.assertRaises(fetcher.FetchError): fetcher.fetch_standings("PL","test-placeholder")



if __name__ == "__main__": unittest.main()

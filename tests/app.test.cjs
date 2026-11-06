const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const { buildRounds, initialRound: chooseRound, kickoffText, resultText, buildAllMatches: summarize, groupByDay, shortTeamName, competitionText, displayTeamName, freshnessState } = require("../site/app.js");
const FIXED_NOW = Date.parse("2026-11-06T20:00:00Z");
const initialRound = (rounds, now=FIXED_NOW) => chooseRound(rounds,now);
const buildAllMatches = (competitions, now=FIXED_NOW) => summarize(competitions,now);

function match(id, day, status = "終了", stage = "REGULAR_SEASON") {
  return { id, competition: "PL", matchday: day, stage, status, utcDate: "2026-11-06T20:00:00Z", home: "Test Home", away: "Test Away", score: { home: status === "終了" ? 2 : null, away: status === "終了" ? 1 : null } };
}
const sample = [match(3, 3, "予定"), match(1, 1), match(2, 2, "試合中")];
assert.equal(initialRound(buildRounds(sample, "PL")), 1);
assert.equal(initialRound(buildRounds([match(1, 1), match(2, 2)], "PL")), 1);
assert.equal(initialRound(buildRounds([match(1, 1, "延期"), match(2, 2, "予定")], "PL")), 1);
assert.match(kickoffText(sample[0].utcDate), /11\/7/);
assert.match(kickoffText(sample[0].utcDate), /5:00/);
assert.equal(resultText(match(1, 1)), "2 - 1");
assert.equal(resultText(match(1, 1, "延期")), "延期");
assert.equal(resultText(match(1, 1, "予定")), "vs");

// Exercise the actual page controller with a minimal DOM; no browser required.
class Element {
  constructor() { this.children = []; this.attributes = {}; this.handlers = {}; this.textContent = ""; this.disabled = false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes.flatMap(node => node.fragment ? node.children : [node]); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  click() { if (!this.disabled) this.handlers.click?.(); }
}
function tab(nodes, name) {
  const button = nodes.competitions.children.find(button => button.textContent === name);
  assert.ok(button, `tab exists: ${name}`);
  return button;
}
function matchRows(nodes) {
  return nodes.matches.children.filter(node => node.className.split(" ").includes("match"));
}
async function testController(competitions, expectedTabs, options = {}) {
  const nodes = Object.fromEntries(["competitions", "competition-title", "round-title", "previous", "next", "message", "matches", "updated", "schedule-view", "standings-view", "schedule-panel", "standings-panel", "standings-status", "standings", "freshness-warning", "fetch-confirmed", "site-subtitle"].map(id => [id, new Element()]));
  const document = {
    documentElement:{dataset:{environment:options.environment || "local"}},
    baseURI: "http://localhost:8000/site/", getElementById: id => nodes[id],
    createElement: () => new Element(), createDocumentFragment: () => Object.assign(new Element(), {fragment:true})
  };
  class TestDate extends Date {
    constructor(...args) { super(...(args.length ? args : [options.now ?? FIXED_NOW])); }
    static now() { return options.now ?? FIXED_NOW; }
  }
  const context = vm.createContext({ document, URL, Intl, Date:TestDate, setInterval:options.registerInterval, location: {protocol:options.file ? "file:" : "http:"},
    fetch: async url => {
      if (options.file) throw new Error("file origin blocked");

      if (url.href.endsWith("/data/fetch_status.json")) {
        if (options.statusError) throw new Error("heartbeat unavailable");
        return {ok:!!options.fetchStatus,json:async()=>options.fetchStatus};
      }
      assert.equal(url.href, "http://localhost:8000/data/matches.json");
      return {ok:true, json:async () => ({updatedAt:options.updatedAt || "2026-11-06T20:00:00Z",competitions, standings:options.standings || {},competitionUpdatedAt:options.versions || {}})};
    }
  });
  const source = fs.readFileSync(path.join(__dirname, "../site/app.js"), "utf8");
  vm.runInContext(source.replace('if (typeof document !== "undefined") start();', ""), context);
  await vm.runInContext("start()", context);
  if (options.file) {
    assert.match(nodes.message.textContent, /HTTPサーバー/);
    return;
  }
  assert.equal(nodes.competitions.children.length, expectedTabs);
  if (options.inspect) {
    await options.inspect(nodes);
    return;
  }
  if (!competitions.PL?.length) {
    assert.equal(nodes["round-title"].textContent, "日程未取得");
    assert.equal(nodes.previous.disabled, true);
    assert.equal(nodes.next.disabled, true);
    return;
  }
  assert.equal(nodes["round-title"].textContent, "第2節");
  nodes.previous.click();
  assert.equal(nodes["round-title"].textContent, "第1節");
  assert.equal(nodes.previous.disabled, true);
  assert.equal(matchRows(nodes)[0].children[2].textContent, "2 - 1");
  nodes.next.click(); nodes.next.click();
  assert.equal(nodes["round-title"].textContent, "第3節");
  assert.equal(nodes.next.disabled, true);
  assert.match(nodes.updated.textContent, /11月7日 5:00（JST）/);
  for (const name of ["ブンデスリーガ", "ラ・リーガ", "セリエA", "リーグ・アン", "CL"]) {
    tab(nodes, name).click();
    if (options.onlyPL) assert.equal(matchRows(nodes).length, 0);
    else assert.ok(matchRows(nodes).length);
  }
}

const clMatches = [
  match(9, null, "予定", "FINAL"), match(4, 10, "予定", "PLAYOFFS"),
  match(1, 1, "終了", "LEAGUE_STAGE"), match(3, 9, "予定", "PLAYOFFS"),
  match(2, 8, "終了", "LEAGUE_STAGE"), match(5, 11, "予定", "LAST_16"),
  match(6, 12, "予定", "LAST_16"), match(7, 13, "予定", "QUARTER_FINALS"),
  match(8, 14, "予定", "SEMI_FINALS")
];
const clRounds = buildRounds(clMatches, "CL");
assert.deepEqual(clRounds.map(r => r.label), ["リーグフェーズ第1節", "リーグフェーズ第8節", "プレーオフ", "ベスト16", "準々決勝", "準決勝", "決勝"]);
assert.equal(clRounds[2].matches.length, 2);
assert.equal(clRounds[3].matches.length, 2);
assert.equal(initialRound(clRounds), 2);
assert.equal(buildRounds([], "CL").length, 0);
assert.equal(kickoffText(null), "日時未定");

const six = Object.fromEntries(["PL", "BL1", "PD", "SA", "FL1", "CL"].map(code => [code, code === "CL" ? clMatches : sample]));

const clLabels = [
  ...Array.from({length:8}, (_, i) => `リーグフェーズ第${i + 1}節`),
  "プレーオフ", "ベスト16", "準々決勝", "準決勝", "決勝"
];
const fullCL = [
  ...Array.from({length:8}, (_, i) => match(i + 1, i + 1, i < 4 ? "終了" : "予定", "LEAGUE_STAGE")),
  ...["PLAYOFFS", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS"].flatMap((stage, i) => [
    {...match(20 + i * 2, 9 + i * 2, "予定", stage), utcDate:"2027-02-02T20:00:00Z"},
    {...match(21 + i * 2, 10 + i * 2, "予定", stage), utcDate:"2027-02-09T20:00:00Z"}
  ]),
  {...match(40, null, "予定", "FINAL"), utcDate:null}
].reverse(); // Deliberately unordered input, including different matchdays for both legs.

async function testCLNavigation() {
  assert.deepEqual(buildRounds(fullCL, "CL").map(round => round.label), clLabels);
  const scenarios = [
    ["next league matchday", fullCL, "リーグフェーズ第5節"],
    ["live earlier matchday", fullCL.map(m => m.matchday === 2 ? {...m,status:"試合中"} : m), "リーグフェーズ第2節"],
    ["next playoffs", fullCL.map(m => m.stage === "LEAGUE_STAGE" ? {...m,status:"終了"} : m), "プレーオフ"],
    ["postponement skipped", fullCL.map(m => m.stage === "LEAGUE_STAGE" ? {...m,status:"終了"} : m.stage === "PLAYOFFS" ? {...m,status:"延期"} : m), "ベスト16"],
    ["all finished", fullCL.map(m => ({...m,status:"終了"})), "決勝"]
  ];
  for (const [name, matches, expected] of scenarios) {
    await testController({PL:sample, CL:matches}, 7, {inspect(nodes) {
      tab(nodes, "CL").click();
      assert.equal(nodes["round-title"].textContent, expected);
    }});
    console.log(`CL initial selection (${name}): ${expected} PASS`);
  }
  await testController({PL:sample, CL:fullCL}, 7, {inspect(nodes) {
    tab(nodes, "CL").click();
    for (let i = 4; i > 0; i--) nodes.previous.click();
    assert.equal(nodes.previous.disabled, true);
    assert.equal(nodes["round-title"].textContent, clLabels[0]);
    nodes.previous.click();
    assert.equal(nodes["round-title"].textContent, clLabels[0]);
    for (let i = 1; i < clLabels.length; i++) {
      nodes.next.click();
      assert.equal(nodes["round-title"].textContent, clLabels[i]);
      assert.equal(matchRows(nodes).length, i >= 8 && i < 12 ? 2 : 1);
      if (i >= 8 && i < 12) {
        assert.equal(matchRows(nodes)[0].children[0].dateTime, "2027-02-02T20:00:00Z");
        assert.equal(matchRows(nodes)[1].children[0].dateTime, "2027-02-09T20:00:00Z");
      }
    }
    assert.equal(nodes.next.disabled, true);
    nodes.next.click();
    assert.equal(nodes["round-title"].textContent, "決勝");
    assert.equal(matchRows(nodes)[0].children[0].textContent, "日時未定");
    tab(nodes, "プレミアリーグ").click();
    assert.equal(nodes["round-title"].textContent, "第2節");
    tab(nodes, "CL").click();
    assert.equal(nodes["round-title"].textContent, "決勝");
    for (let i = clLabels.length - 2; i >= 0; i--) {
      nodes.previous.click();
      assert.equal(nodes["round-title"].textContent, clLabels[i]);
    }
    assert.equal(nodes.previous.disabled, true);
  }});
  console.log(`CL forward (12 transitions): ${clLabels.join(" -> ")} PASS`);
  console.log("CL reverse (12 transitions), both-leg grouping/date ordering, boundary buttons and tab position retention: PASS");
}
async function testReadability() {
  for (const [full, short] of [
    ["Manchester United FC", "Manchester United"], ["AFC Bournemouth", "Bournemouth"],
    ["FC Bayern München", "Bayern München"], ["Hull City AFC", "Hull City"],
    ["Example F.C.", "Example"], ["FCExample", "FCExample"], ["AC Milan", "AC Milan"], ["FC", "FC"]
  ]) assert.equal(shortTeamName(full), short);
  const fixtures = [
    {...match(1, 1), home:"Manchester United FC", utcDate:"2026-11-06T14:00:00Z"},
    {...match(2, 1, "予定"), utcDate:"2026-11-06T15:00:00Z"},
    {...match(3, 1, "延期"), utcDate:"2026-11-07T01:00:00Z"},
    {...match(4, 1, "試合中"), utcDate:"2026-11-07T02:00:00Z"},
    {...match(5, 1, "中止"), utcDate:null}
  ];
  const original = JSON.stringify(fixtures);
  assert.deepEqual(groupByDay(fixtures).map(day => day.matches.length), [1, 3, 1]);
  assert.deepEqual(groupByDay(fixtures).map(day => day.label), ["11/6(金)", "11/7(土)", "日時未定"]);
  assert.equal(competitionText(match(1, 10), "PL"), "プレミア・第10節");
  assert.equal(competitionText(match(1, 5, "予定", "LEAGUE_STAGE"), "CL"), "CL・リーグフェーズ第5節");
  assert.equal(competitionText(match(1, 9, "予定", "PLAYOFFS"), "CL"), "CL・プレーオフ");
  await testController({PL:fixtures}, 7, {inspect(nodes) {
    const headings = nodes.matches.children.filter(node => node.className === "day-heading");
    assert.deepEqual(headings.map(node => node.textContent), ["11/6(金)", "11/7(土)", "日時未定"]);
    const rows = matchRows(nodes);
    assert.deepEqual(rows.map(row => row.children[0].textContent), ["23:00", "0:00", "10:00", "11:00", "日時未定"]);
    assert.equal(rows[0].children[1].textContent, "Manchester United");
    assert.equal(rows[0].children[1].title, "Manchester United FC");
    assert.equal(rows[0].children[1].attributes["aria-label"], "Manchester United FC");
    assert.deepEqual(rows.map(row => row.className), ["match match--finished", "match match--scheduled", "match match--postponed", "match match--live", "match match--cancelled"]);
    tab(nodes, "すべて").click();
    assert.ok(matchRows(nodes).every(row => row.children[4].textContent === "プレミア・第1節"));
  }});
  assert.equal(JSON.stringify(fixtures), original);
  console.log("Readability: JST date groups across UTC midnight, time-only rows, short English names/full-name labels, competition/round metadata and status classes PASS");
}
async function testFreshness() {
  const version="2026-11-01T00:00:00Z";
  const base={updatedAt:version,competitionUpdatedAt:{PL:version},competitions:{PL:sample},standings:{PL:{updatedAt:version}}};
  const makeStatus = at => ({schemaVersion:1,competitions:{PL:{matches:{lastSuccessAt:at,dataUpdatedAt:version},standings:{lastSuccessAt:at,dataUpdatedAt:version}}}});
  assert.equal(freshnessState(base,makeStatus("2026-11-06T19:00:00Z"),"PL","schedule",FIXED_NOW).warning,"");
  assert.equal(freshnessState(base,makeStatus("2026-11-05T20:00:01Z"),"PL","schedule",FIXED_NOW).warning,"");
  assert.match(freshnessState(base,makeStatus("2026-11-05T20:00:00Z"),"PL","schedule",FIXED_NOW).warning,/24時間/);
  const failed=makeStatus("2026-11-05T19:00:00Z");
  failed.competitions.PL.matches.lastAttemptAt="2026-11-06T20:00:00Z";
  failed.competitions.PL.matches.error="HTTP 403";
  assert.match(freshnessState(base,failed,"PL","schedule",FIXED_NOW).warning,/24時間/);
  assert.deepEqual(freshnessState(base,null,"PL","schedule",FIXED_NOW),{lastSuccessAt:null,warning:""});
  const mismatched=makeStatus("2026-11-06T19:00:00Z"); mismatched.competitions.PL.matches.dataUpdatedAt="2026-11-02T00:00:00Z";
  assert.deepEqual(freshnessState(base,mismatched,"PL","schedule",FIXED_NOW),{lastSuccessAt:null,warning:""});
  const fresh=makeStatus("2026-11-06T19:00:00Z");
  fresh.competitions.PL.standings.lastSuccessAt="2026-11-05T19:00:00Z";
  assert.equal(freshnessState(base,fresh,"PL","schedule",FIXED_NOW).warning,"");
  assert.match(freshnessState(base,fresh,"PL","standings",FIXED_NOW).warning,/24時間/);
  await testController({PL:sample},7,{updatedAt:version,versions:{PL:version},fetchStatus:makeStatus("2026-11-06T19:00:00Z"),inspect(nodes) {
    assert.equal(nodes["freshness-warning"].hidden,true);
    assert.match(nodes["fetch-confirmed"].textContent,/取得確認：11\/7.*4:00/);
    assert.match(nodes.updated.textContent,/11月1日/);
  }});
  await testController({PL:sample,CL:clMatches},7,{versions:{PL:"2026-11-06T20:00:00Z",CL:version},standings:{CL:{updatedAt:"2026-10-30T00:00:00Z",groups:[]}},inspect(nodes) {
    tab(nodes,"CL").click();
    assert.match(nodes.updated.textContent,/11月1日/);
    nodes["standings-view"].click();
    assert.match(nodes.updated.textContent,/10月30日/);
  }});
  await testController({PL:sample},7,{updatedAt:version,versions:{PL:version},fetchStatus:failed,inspect(nodes) {
    assert.equal(nodes["freshness-warning"].hidden,false);
    assert.match(nodes["freshness-warning"].textContent,/24時間/);
  }});
  await testController({PL:sample},7,{statusError:true,inspect(nodes) {
    assert.ok(matchRows(nodes).length);
    assert.equal(nodes["freshness-warning"].hidden,true);
    assert.equal(nodes["freshness-warning"].textContent,"");
  }});
  const timers=new Map();
  const polling={updatedAt:version,versions:{PL:version},fetchStatus:makeStatus("2026-11-06T19:00:00Z"),registerInterval:(fn,ms)=>timers.set(ms,fn),async inspect(nodes) {
    polling.now=FIXED_NOW+25*3600000;
    timers.get(60000)();
    assert.equal(nodes["freshness-warning"].hidden,false);
    polling.fetchStatus=makeStatus(new Date(polling.now-3600000).toISOString());
    await timers.get(300000)();
    assert.equal(nodes["freshness-warning"].hidden,true);
    polling.statusError=true;
    polling.now+=25*3600000;
    await timers.get(300000)();
    assert.equal(nodes["freshness-warning"].hidden,false);
  }};
  // Interval registration occurs at the end of start(), after the initial render.
  await testController({PL:sample},7,polling);
  console.log("Freshness: 24-hour boundary, unchanged-success heartbeat, failed-attempt isolation, view scope, version mismatch and missing status PASS");
}

async function run() {
 await testController({PL:sample}, 7, {onlyPL:true});
 await testController(six, 7);
 await testController({}, 7);
 await testController({}, 0, {file:true});
 await testCLNavigation();
 await testReadability();
 await testFreshness();
 console.log("European schedule, navigation, results and freshness tests passed");
}
run().catch(error => { console.error(error); process.exitCode = 1; });

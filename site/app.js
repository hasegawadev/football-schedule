"use strict";

const COMPETITIONS = {
  PL: "プレミアリーグ", BL1: "ブンデスリーガ", PD: "ラ・リーガ",
  SA: "セリエA", FL1: "リーグ・アン", CL: "CL"
};
const TABS = { ALL: "すべて", ...COMPETITIONS };
const COMPETITION_LABELS = { PL: "プレミア", BL1: "ブンデス", PD: "ラ・リーガ", SA: "セリエA", FL1: "リーグ・アン", CL: "CL" };
function matchDate(match) {
  return match.utcDate ? new Date(match.utcDate) : match.dateJst ? new Date(`${match.dateJst}T00:00:00+09:00`) : null;
}

function compareMatches(a, b) {
  const key = match => match.utcDate || (match.dateJst ? matchDate(match).toISOString() : "9999");
  return key(a).localeCompare(key(b)) || a.id - b.id || (a.competition || "").localeCompare(b.competition || "");
}

function buildAllMatches(competitions, now = Date.now()) {
  return ["PL", "BL1", "PD", "SA", "FL1", "CL"].flatMap(code => {
    const rounds = buildRounds(competitions[code] || [], code);
    const round = rounds[initialRound(rounds, now)];
    return (round?.matches || []).map(match => ({ ...match, competition: code }));
  })
    .sort(compareMatches);
}

const STAGES = {
  PRELIMINARY_ROUND: [0, "予備予選"], QUALIFICATION: [1, "予選"],
  QUALIFICATION_ROUND_1: [2, "予選1回戦"], QUALIFICATION_ROUND_2: [3, "予選2回戦"],
  QUALIFICATION_ROUND_3: [4, "予選3回戦"], PLAYOFF_ROUND_1: [5, "予選プレーオフ1回戦"],
  PLAYOFF_ROUND_2: [6, "予選プレーオフ2回戦"],
  LEAGUE_STAGE: [10, "リーグフェーズ"], LEAGUE_PHASE: [10, "リーグフェーズ"],
  REGULAR_SEASON: [10, "リーグフェーズ"], GROUP_STAGE: [10, "グループステージ"],
  PLAYOFFS: [20, "プレーオフ"], KNOCKOUT_PHASE_PLAYOFFS: [20, "プレーオフ"],
  LAST_64: [21, "ベスト64"], LAST_32: [22, "ベスト32"], LAST_16: [30, "ベスト16"],
  QUARTER_FINALS: [40, "準々決勝"], SEMI_FINALS: [50, "準決勝"],
  THIRD_PLACE: [55, "3位決定戦"], FINAL: [60, "決勝"]
};

function buildRounds(matches, code = "PL") {
  const groups = new Map();
  for (const match of matches) {
    const isCL = code === "CL";
    const stage = STAGES[match.stage] || [90, match.stage || "ステージ未定"];
    const isLeaguePhase = isCL && stage[0] === 10;
    const key = isCL ? `${match.stage}:${isLeaguePhase ? match.matchday : "all"}` : String(match.matchday);
    const label = isCL ? `${stage[1]}${isLeaguePhase && match.matchday !== null ? `第${match.matchday}節` : ""}` : `第${match.matchday}節`;
    // Both knockout legs belong to one navigable stage, even if matchday differs.
    if (!groups.has(key)) groups.set(key, {
      key, order: isCL ? stage[0] : 0, number: isCL && !isLeaguePhase ? 0 : match.matchday,
      label, matches: []
    });
    groups.get(key).matches.push(match);
  }
  return [...groups.values()].sort((a, b) => a.order - b.order || a.number - b.number || a.key.localeCompare(b.key)).map(round => ({
    ...round,
    matches: round.matches.sort(compareMatches)
  }));
}

function initialRound(rounds, now = Date.now()) {
  // A rescheduled old matchday must not outrank an earlier upcoming fixture.
  const live = [], upcoming = [], undated = [], recent = [];
  let unfinished = false;
  rounds.forEach((round, index) => round.matches.forEach(match => {
    const date = matchDate(match);
    const time = date?.getTime();
    const known = Number.isFinite(time);
    if (["予定", "試合中"].includes(match.status)) {
      unfinished = true;
      if (match.status === "試合中" && (!known || time >= now - 6 * 3600000 && time <= now + 1800000)) live.push([known ? time : now, index]);
      else if (!known) undated.push(index);
      else {
        // Date-only fixtures remain upcoming through the end of their JST day.
        const end = match.utcDate ? time + 3 * 3600000 : time + 24 * 3600000;
        if (match.utcDate ? end >= now : end > now) upcoming.push([time, index]);
      }
    }
    if (known && !["延期", "中止"].includes(match.status)) recent.push([time, index]);
  }));
  for (const candidates of [live, upcoming]) {
    if (candidates.length) return candidates.sort((a,b) => a[0] - b[0] || a[1] - b[1])[0][1];
  }
  if (undated.length) return Math.min(...undated);
  if (unfinished && recent.length) return recent.sort((a,b) => b[0] - a[0] || b[1] - a[1])[0][1];
  const completed = rounds.map((round,index) => round.matches.some(match => match.status === "終了") ? index : -1).filter(index => index >= 0);
  if (completed.length) return completed.at(-1);
  return Math.max(0, rounds.length - 1);
}

function freshnessState(data, status, active, view, now = Date.now()) {
  const codes = active === "ALL" ? Object.keys(COMPETITIONS) : [active];
  const part = view === "standings" ? "standings" : "matches";
  const stale = [], confirmed = [];
  for (const code of codes) {
    const entry = status?.competitions?.[code]?.[part];
    const checked = Date.parse(entry?.lastSuccessAt);
    const version = part === "standings" ? data.standings?.[code]?.updatedAt : data.competitionUpdatedAt?.[code] || data.updatedAt;
    if (Number.isFinite(checked) && checked <= now + 300000 && entry?.dataUpdatedAt === version) {
      confirmed.push(checked);
      if (now - checked >= 24 * 3600000) stale.push(TABS[code]);
    }
  }
  const notices = [];
  if (stale.length) notices.push(`${stale.join("・")}は24時間以上、取得成功を確認できていません。日程・結果が古い可能性があります。`);
  return { lastSuccessAt: confirmed.length === codes.length ? Math.min(...confirmed) : null, warning: notices.join(" ") };
}

const dateFormatter = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", weekday: "short" });
const timeFormatter = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", hour: "numeric", minute: "2-digit", hourCycle: "h23" });
function kickoffText(value) {
  if (!value) return "日時未定";
  const date = new Date(value);
  return `${dateFormatter.format(date)}\n${timeFormatter.format(date)}`;
}

const dayKeyFormatter = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit" });
function groupByDay(matches) {
  const days = new Map();
  for (const match of matches) {
    const date = matchDate(match);
    const key = date ? dayKeyFormatter.format(date) : "unknown";
    if (!days.has(key)) days.set(key, { key, label: date ? dateFormatter.format(date) : "日時未定", matches: [] });
    days.get(key).matches.push(match);
  }
  return [...days.values()];
}

function shortTeamName(name) {
  const parts = name.split(/\s+/);
  const affixes = new Set(["FC", "AFC", "CF", "CFC"]);
  const isAffix = token => affixes.has(token.replace(/\./g, "").toUpperCase());
  while (parts.length > 1 && isAffix(parts[0])) parts.shift();
  while (parts.length > 1 && isAffix(parts.at(-1))) parts.pop();
  return parts.join(" ");
}

function displayTeamName(name, code) {
  return shortTeamName(name);
}

function competitionText(match, code) {
  const label = buildRounds([match], code)[0].label;
  return `${COMPETITION_LABELS[code]}・${label}`;
}

function resultText(match) {
  if (match.status === "終了") {
    return match.score.home !== null && match.score.away !== null
      ? `${match.score.home} - ${match.score.away}` : "結果未取得";
  }
  return { "延期": "延期", "中止": "中止", "試合中": "試合中", "予定": "vs" }[match.status] || match.status;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function start() {
  const byId = id => document.getElementById(id);
  let data;
  try {
    const response = await fetch(new URL("../data/matches.json", document.baseURI), { cache: "no-cache" });
    if (!response.ok) throw new Error("HTTP error");
    data = await response.json();
    if (!data.competitions || !(data.updatedAt === null || Number.isFinite(Date.parse(data.updatedAt)))) throw new Error("Invalid data");
    for (const code of Object.keys(COMPETITIONS)) {
      if (code in data.competitions && !Array.isArray(data.competitions[code])) throw new Error("Invalid competition");
    }
  } catch {
    byId("competition-title").textContent = "データを読み込めませんでした";
    byId("message").textContent = location.protocol === "file:"
      ? "ローカルHTTPサーバーを起動し、http://localhost:8000/site/ を開いてください。"
      : "通信状況と試合データの更新状況を確認し、再読み込みしてください。";
    return;
  }
  async function readFetchStatus() {
    try {
      const response = await fetch(new URL("../data/fetch_status.json", document.baseURI), { cache: "no-cache" });
      if (response.ok) {
        const candidate = await response.json();
        if (candidate.schemaVersion === 1 && candidate.competitions && typeof candidate.competitions === "object") return candidate;
      }
    } catch { /* Keep the previous successful check; do not mark a failed request fresh. */ }
    return null;
  }
  let fetchStatus = await readFetchStatus();
  let active = "PL";
  let activeView = "schedule";
  const allRounds = Object.fromEntries(Object.keys(COMPETITIONS).map(code => [code, buildRounds(data.competitions[code] || [], code)]));
  const allMatches = buildAllMatches(data.competitions);
  allRounds.ALL = allMatches.length ? [{ label: "各大会の次節", matches: allMatches }] : [];
  const positions = Object.fromEntries(Object.entries(allRounds).map(([code, rounds]) => [code, initialRound(rounds)]));
  const buttons = {};
  function renderFreshness() {
    const codes = active === "ALL" ? Object.keys(COMPETITIONS) : [active];
    const contentTimes = codes.map(code => Date.parse(activeView === "standings" ? data.standings?.[code]?.updatedAt : data.competitionUpdatedAt?.[code] || data.updatedAt)).filter(Number.isFinite);
    const contentDate = contentTimes.length ? new Date(Math.max(...contentTimes)) : null;
    const updateDate = contentDate ? new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "long", day: "numeric" }).format(contentDate) : null;
    byId("updated").textContent = contentDate ? `最終更新：${updateDate} ${timeFormatter.format(contentDate)}（JST）` : "最終更新：未記録";
    const state = freshnessState(data, fetchStatus, active, activeView);
    byId("freshness-warning").textContent = state.warning;
    byId("freshness-warning").hidden = !state.warning;
    const date = state.lastSuccessAt === null ? null : new Date(state.lastSuccessAt);
    byId("fetch-confirmed").textContent = date ? `取得確認：${dateFormatter.format(date)} ${timeFormatter.format(date)}（JST）` : "取得確認：日時未確認";
  }
  function renderStandings() {
    const fragment = document.createDocumentFragment();
    const codes = active === "ALL" ? Object.keys(COMPETITIONS) : [active];
    byId("standings-status").textContent = "最新の総合成績です。日程の表示節には連動しません。";
    for (const code of codes) {
      const standing = data.standings?.[code];
      const card = element("section", "standings-card");
      card.append(element("h3", "standings-title", `${COMPETITIONS[code]}${standing?.season ? ` · ${standing.season}` : ""}`));
      if (!standing?.groups?.length) {
        const emptyMessage = standing?.status === "unavailable" ? "取得元から順位表データがまだ提供されていません。"
          : standing && code === "CL" ? "現在のステージに順位表はありません。" : "順位表はまだ取得されていません。";
        card.append(element("p", "standings-empty", emptyMessage));
      }
      for (const group of standing?.groups || []) {
        const wrap = element("div", "table-scroll");
        wrap.tabIndex = 0;
        wrap.setAttribute("role", "region");
        wrap.setAttribute("aria-label", `${COMPETITIONS[code]}の順位表（横スクロール対応）`);
        const table = element("table", "standings-table");
        const groupLabel = code === "CL" && group.label === "総合" ? (STAGES[group.stage]?.[1] || group.label) : group.label;
        table.append(element("caption", "", groupLabel));
        const head = element("thead");
        const header = element("tr");
        const columns = [["順位", "position"], ["クラブ", "team"], ["勝点", "points"], ["試合", "played"],
          ["勝", "won"], ["分", "draw"], ["敗", "lost"], ["得点", "goalsFor"], ["失点", "goalsAgainst"], ["得失差", "goalDifference"]];
        for (const [label, key] of columns) {
          const th = element("th", `col-${key}`, label);
          th.setAttribute("scope", "col");
          header.append(th);
        }
        head.append(header);
        const body = element("tbody");
        for (const row of group.table) {
          const tr = element("tr");
          for (const [, key] of columns) {
            const value = key === "team" ? displayTeamName(row.team, code) : key === "goalDifference" && row[key] > 0 ? `+${row[key]}` : String(row[key]);
            const cell = element(key === "team" ? "th" : "td", `col-${key}`, value);
            if (key === "team") { cell.setAttribute("scope", "row"); cell.title = row.team; }
            tr.append(cell);
          }
          body.append(tr);
        }
        table.append(head, body);
        wrap.append(table);
        card.append(wrap);
      }
      if (standing?.updatedAt) {
        const updated = new Date(standing.updatedAt);
        card.append(element("p", "standings-updated", `順位表更新：${dateFormatter.format(updated)} ${timeFormatter.format(updated)}（JST）`));
      }
      fragment.append(card);
    }
    byId("standings").replaceChildren(fragment);
  }
  function render() {
    renderFreshness();
    const rounds = allRounds[active];
    const position = positions[active];
    const round = rounds[position];
    for (const [code, button] of Object.entries(buttons)) button.setAttribute("aria-pressed", String(code === active));
    byId("competition-title").textContent = TABS[active];
    byId("schedule-panel").hidden = activeView !== "schedule";
    byId("standings-panel").hidden = activeView !== "standings";
    byId("schedule-view").setAttribute("aria-pressed", String(activeView === "schedule"));
    byId("standings-view").setAttribute("aria-pressed", String(activeView === "standings"));
    if (activeView === "standings") { renderStandings(); return; }
    byId("round-title").textContent = round?.label || "日程未取得";
    if (round) byId("round-title").append(element("span", "round-summary", `${round.matches.length}試合・日本時間（JST）`));
    byId("previous").disabled = !round || position === 0;
    byId("next").disabled = !round || position === rounds.length - 1;
    byId("message").textContent = round ? `${round.label}・${round.matches.length}試合 ／ 日本時間（JST）${active === "ALL" ? "・キックオフ順（日時未定は末尾）" : ""}`
      : "日程がまだ取得されていません。";
    byId("message").hidden = !!round;
    const fragment = document.createDocumentFragment();
    for (const day of groupByDay(round?.matches || [])) {
      fragment.append(element("h3", "day-heading", day.label));
      for (const match of day.matches) {
        const state = { "予定": "scheduled", "終了": "finished", "延期": "postponed", "中止": "cancelled", "試合中": "live" }[match.status] || "scheduled";
        const row = element("article", `match match--${state}`);
        const scheduled = state === "scheduled";
        const time = element(scheduled ? "time" : "span", scheduled ? "kickoff" : "kickoff kickoff--status",
          scheduled ? match.utcDate ? timeFormatter.format(new Date(match.utcDate)) : match.dateJst ? "時刻未定" : "日時未定" : match.status);
        if (scheduled && match.utcDate) time.dateTime = match.utcDate;
        const hasScore = state === "finished" && Number.isFinite(match.score.home) && Number.isFinite(match.score.away);
        const result = element("div", "result");
        const homeScore = element("span", "score score--home", state === "finished" ? hasScore ? String(match.score.home) : "—" : "");
        const awayScore = element("span", "score score--away", state === "finished" ? hasScore ? String(match.score.away) : "—" : "");
        if (state === "finished") result.setAttribute("aria-label", resultText(match));
        result.append(homeScore, awayScore);
        const code = active === "ALL" ? match.competition : active;
        const home = element("div", "team home", displayTeamName(match.home, code));
        const away = element("div", "team away", displayTeamName(match.away, code));
        home.replaceChildren(element("span", "team-name", home.textContent));
        away.replaceChildren(element("span", "team-name", away.textContent));
        for (const [team, id] of [[home, match.homeId], [away, match.awayId]]) {
          if (!["PL", "BL1", "PD", "SA", "FL1", "CL"].includes(code) || !Number.isSafeInteger(id) || id <= 0) continue;
          const slot = element("span", "team-emblem");
          const crest = element("img", "team-crest");
          crest.alt = "";
          crest.width = 26;
          crest.height = 26;
          crest.loading = "lazy";
          crest.decoding = "async";
          crest.referrerPolicy = "no-referrer";
          let triedSvg = false;
          crest.addEventListener("error", () => {
            if (!triedSvg) {
              triedSvg = true;
              crest.src = `https://crests.football-data.org/${id}.svg`;
            } else crest.hidden = true;
          });
          crest.src = `https://crests.football-data.org/${id}.png`;
          slot.setAttribute("aria-hidden", "true");
          slot.append(crest);
          team.replaceChildren(slot, team.children[0]);
        }
        if (hasScore && match.score.home !== match.score.away) {
          const homeWon = match.score.home > match.score.away;
          home.className += homeWon ? " team--winner" : " team--loser";
          away.className += homeWon ? " team--loser" : " team--winner";
          homeScore.className += homeWon ? " score--winner" : " score--loser";
          awayScore.className += homeWon ? " score--loser" : " score--winner";
        }
        home.title = match.home;
        away.title = match.away;
        home.setAttribute("aria-label", match.home);
        away.setAttribute("aria-label", match.away);
        row.append(time, home, result, away);
        if (active === "ALL") row.append(element("div", "match-meta", competitionText(match, match.competition)));
        fragment.append(row);
      }
    }
    byId("matches").replaceChildren(fragment);
  }
  for (const [code, name] of Object.entries(TABS)) {
    const button = element("button", "", name);
    button.type = "button";
    button.addEventListener("click", () => { active = code; render(); });
    buttons[code] = button;
    byId("competitions").append(button);
  }
  byId("previous").addEventListener("click", () => { if (positions[active] > 0) { positions[active]--; render(); } });
  byId("next").addEventListener("click", () => { if (positions[active] < allRounds[active].length - 1) { positions[active]++; render(); } });
  byId("schedule-view").addEventListener("click", () => { activeView = "schedule"; render(); });
  byId("standings-view").addEventListener("click", () => { activeView = "standings"; render(); });
  render();
  // Re-evaluate the 24-hour boundary even when the page stays open overnight.
  if (typeof setInterval === "function") {
    setInterval(renderFreshness, 60000);
    setInterval(async () => {
      const latest = await readFetchStatus();
      if (latest) fetchStatus = latest;
      renderFreshness();
    }, 300000);
  }
}

if (typeof document !== "undefined") start();
if (typeof module !== "undefined") module.exports = { buildRounds, initialRound, kickoffText, resultText, buildAllMatches, groupByDay, shortTeamName, competitionText, displayTeamName, freshnessState };

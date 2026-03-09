/**
 * ¿Cómo Votó? - Interactive Frontend
 * ====================================
 * Features:
 *   - Search legislators by name, bloc, province
 *   - Filter by chamber, coalition, year, law name
 *   - Waffle/grid visualization grouped by law
 *   - Law search with per-coalition vote breakdown
 *   - Alignment charts (line + bar)
 *   - Vote history table with pagination
 *   - Copy image / Share to Twitter
 */

// ===========================================================================
//  GLOBALS
// ===========================================================================

let legislatorsData = [];
let lawsData = [];           // loaded from laws_detail.json
let currentSelectedLaw = null;  // currently displayed law in the detail card
let currentDetail = null;
let currentLegKey = null; // The data-key used to load current legislator
let chartAlignment = null;
let chartYearly = null;
let currentVotesPage = 1;
let currentWafflePage = 1;
let loadRequestId = 0; // Guard against stale async loads
const VOTES_PER_PAGE = 25;
const LAWS_PER_PAGE = 10;

const DATA_PATH = "data";

// Widget instance for the multi-year waffle dropdown
let _waffleYearWidget = null;

// ===========================================================================
//  MULTI-SELECT DROPDOWN WIDGET
// ===========================================================================

/**
 * Wraps a hidden <select multiple> with a button+checkbox-panel dropdown.
 * Dispatches a native "change" event on the original select when selections
 * change, so existing event listeners continue to work unchanged.
 * Returns { rebuild } — call rebuild() whenever the select's options change.
 */
function initMultiSelect(selectEl, placeholder = "Todos") {
    if (!selectEl) return null;

    // Avoid double-wrapping
    if (selectEl.parentNode.classList.contains("ms-wrap")) {
        const existing = selectEl.parentNode._msWidget;
        if (existing) return existing;
    }

    const wrap = document.createElement("div");
    wrap.className = "ms-wrap";
    selectEl.parentNode.insertBefore(wrap, selectEl);
    wrap.appendChild(selectEl);
    selectEl.style.display = "none";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ms-btn";
    wrap.appendChild(btn);

    const panel = document.createElement("div");
    panel.className = "ms-panel hidden";
    wrap.appendChild(panel);

    function updateBtn() {
        const sel = Array.from(selectEl.selectedOptions).map(o => o.text);
        btn.textContent = sel.length === 0 ? placeholder : sel.join(", ");
        btn.classList.toggle("ms-active", sel.length > 0);
    }

    function rebuild() {
        panel.innerHTML = "";
        Array.from(selectEl.options).forEach(opt => {
            const lbl = document.createElement("label");
            lbl.className = "ms-option";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = opt.value;
            cb.checked = opt.selected;
            cb.addEventListener("change", () => {
                opt.selected = cb.checked;
                updateBtn();
                selectEl.dispatchEvent(new Event("change", { bubbles: true }));
            });
            lbl.appendChild(cb);
            lbl.appendChild(document.createTextNode("\u00a0" + opt.text));
            panel.appendChild(lbl);
        });
        updateBtn();
    }

    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = !panel.classList.contains("hidden");
        // Close all other open ms-panels first
        document.querySelectorAll(".ms-panel:not(.hidden)").forEach(p => p.classList.add("hidden"));
        panel.classList.toggle("hidden", open);
    });

    document.addEventListener("click", () => panel.classList.add("hidden"));
    panel.addEventListener("click", e => e.stopPropagation());

    rebuild();
    const widget = { rebuild };
    wrap._msWidget = widget;
    return widget;
}

// ===========================================================================
//  SEARCH
// ===========================================================================

function onSearchInput({ requireQuery = true } = {}) {
    const query = document.getElementById("search-input").value.trim().toLowerCase();
    const chamber = document.getElementById("filter-chamber").value;
    const coalition = document.getElementById("filter-coalition").value;
    const province = (document.getElementById("filter-province")?.value || "").trim();

    // Filters alone (no text query) should not open the results dropdown
    // unless explicitly requested (e.g. on focus).
    if (!query && requireQuery) {
        hideSearchResults();
        return;
    }

    let results = legislatorsData;

    if (chamber) {
        results = results.filter((l) => l.c.includes(chamber));
    }
    if (coalition) {
        results = results.filter((l) => l.co === coalition);
    }
    if (province) {
        const pv = province.toLowerCase();
        results = results.filter((l) => (l.p || "").toLowerCase() === pv);
    }
    if (query) {
        const terms = query.split(/\s+/);
        results = results.filter((l) => {
            const searchable = `${l.n} ${l.b} ${l.p}`.toLowerCase();
            return terms.every((t) => searchable.includes(t));
        });
    }

    results.sort((a, b) => (b.tv || 0) - (a.tv || 0));
    results = results.slice(0, 50);

    renderSearchResults(results);
}

function renderSearchResults(results) {
    const container = document.getElementById("search-results");
    container.classList.remove("hidden");

    if (results.length === 0) {
        container.innerHTML = `<div class="search-result-item" style="justify-content:center; cursor:default; color: var(--color-text-secondary);">No se encontraron resultados</div>`;
        return;
    }

    container.innerHTML = results
        .map(
            (l) => `
        <div class="search-result-item" data-key="${l.k}">
            <div class="search-result-name">${highlightMatch(l.n)}</div>
            <div class="search-result-meta">
                ${chamberBadges(l.c)}
                <span class="badge badge-${l.co.toLowerCase()}">${l.co}</span>
                <span class="badge" style="background:#f1f5f9">${l.p || ""}</span>
            </div>
        </div>`
        )
        .join("");

    container.querySelectorAll(".search-result-item[data-key]").forEach((el) => {
        el.addEventListener("click", () => loadLegislatorDetail(el.dataset.key));
    });
}

function chamberBadges(chamberStr) {
    if (!chamberStr) return "";
    const parts = chamberStr.split("+");
    return parts.map((c) => {
        const label = c === "diputados" ? "Dip." : "Sen.";
        return `<span class="badge badge-${c}">${label}</span>`;
    }).join("");
}

function highlightMatch(name) {
    const query = document.getElementById("search-input").value.trim();
    if (!query) return escapeHtml(name);
    const regex = new RegExp(`(${escapeRegex(query)})`, "gi");
    return escapeHtml(name).replace(regex, "<strong>$1</strong>");
}

function hideSearchResults() {
    document.getElementById("search-results").classList.add("hidden");
}

// ===========================================================================
//  LAW SEARCH SECTION (homepage)
// ===========================================================================

function onLawSearchInput() {
    const query = document.getElementById("law-search").value.trim().toLowerCase();
    const yearVal = (document.getElementById("law-year-filter")?.value || "");
    const chamberVal = document.getElementById("law-chamber-filter").value;
    const dropdown = document.getElementById("law-search-results");

    let results = lawsData;

    // When no filters and no query, show notable laws on focus
    const hasFilter = yearVal || chamberVal;
    if (!query && !hasFilter) {
        // Show notable (common_name) laws by default
        results = results.filter((l) => l.cn);
    }

    if (yearVal) {
        results = results.filter((l) => String(l.y) === yearVal);
    }
    if (chamberVal) {
        results = results.filter((l) => l.ch === chamberVal);
    }
    if (query) {
        const terms = query.split(/\s+/);
        results = results.filter((l) => {
            const searchable = (l.n || "").toLowerCase();
            return terms.every((t) => searchable.includes(t));
        });
    }

    results = results.slice(0, 40);

    if (results.length === 0) {
        dropdown.innerHTML = `<div class="law-dropdown-item" style="cursor:default; color:var(--color-text-secondary); text-align:center;">Sin resultados</div>`;
        dropdown.classList.remove("hidden");
        return;
    }

    dropdown.innerHTML = results.map((l, idx) => {
        const notable = l.cn ? `<span class="law-dropdown-notable">⭐</span>` : "";
        const chamberBadge = l.ch === "diputados"
            ? `<span class="badge badge-diputados">Dip.</span>`
            : l.ch === "senadores"
            ? `<span class="badge badge-senadores">Sen.</span>`
            : "";
        const yearBadge = l.y ? `<span class="law-dropdown-year">${l.y}</span>` : "";
        return `
        <div class="law-dropdown-item" data-law-idx="${idx}">
            <span class="law-dropdown-name">${notable}${escapeHtml(l.n)}</span>
            <span class="law-dropdown-meta">${yearBadge} ${chamberBadge}</span>
        </div>`;
    }).join("");

    dropdown.classList.remove("hidden");

    // Store filtered results in a closure for click handlers
    const filteredResults = results;
    dropdown.querySelectorAll(".law-dropdown-item[data-law-idx]").forEach((el) => {
        el.addEventListener("click", () => {
            const law = filteredResults[parseInt(el.dataset.lawIdx)];
            if (law) selectLaw(law);
            dropdown.classList.add("hidden");
        });
    });
}

function selectLaw(law) {
    currentSelectedLaw = law;
    const wrapper = document.getElementById("law-detail-wrapper");
    wrapper.classList.remove("hidden");

    // Title
    const titleEl = document.getElementById("law-detail-title");
    titleEl.textContent = law.n || "Ley";

    // Meta: year, chamber, # votaciones
    const metaEl = document.getElementById("law-detail-meta");
    const chamberLabel = law.ch === "diputados" ? "Diputados" : law.ch === "senadores" ? "Senadores" : "";
    const parts = [];
    if (law.y) parts.push(`<span class="badge">${law.y}</span>`);
    if (chamberLabel) {
        const cls = law.ch === "diputados" ? "badge-diputados" : "badge-senadores";
        parts.push(`<span class="badge ${cls}">${chamberLabel}</span>`);
    }
    if (law.vs && law.vs.length > 1) parts.push(`<span class="badge">${law.vs.length} votaciones</span>`);
    metaEl.innerHTML = parts.join(" ");

    // Body: per-votación coalition breakdown
    const body = document.getElementById("law-detail-body");
    const vs = law.vs || [];

    if (vs.length === 0) {
        body.innerHTML = `<div class="law-detail-empty">No hay datos de votación disponibles.</div>`;
    } else {
        body.innerHTML = vs.map((v, vi) => renderLawVotacion(v, vi, vs.length)).join("");
    }

    // Scroll into view
    wrapper.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderLawVotacion(v, idx, totalCount) {
    const coalitions = [
        { key: "pj",  label: "PJ / UxP",  cls: "bar-pj" },
        { key: "ucr", label: "UCR",       cls: "bar-ucr" },
        { key: "pro", label: "PRO",       cls: "bar-pro" },
        { key: "lla", label: "LLA",       cls: "bar-lla" },
        { key: "cc",  label: "CC - ARI",  cls: "bar-cc" },
        { key: "oth", label: "Otros",     cls: "bar-oth" },
    ];

    // Header: section label + full title
    const sectionLabel = v.tp || "";
    const fullTitle = v.t || "";
    const dateStr = v.d || "";
    const result = (v.r || "").toUpperCase();
    let resultBadge = "";
    if (result.includes("AFIRMATIV")) {
        resultBadge = `<span class="law-result law-result-afirm">Aprobado</span>`;
    } else if (result.includes("NEGATIV")) {
        resultBadge = `<span class="law-result law-result-neg">Rechazado</span>`;
    } else if (result) {
        resultBadge = `<span class="law-result">${escapeHtml(v.r)}</span>`;
    }

    // Source link
    let linkHtml = "";
    const href = v.url || "";
    if (href) {
        linkHtml = `<a class="law-votacion-link" href="${escapeAttr(href)}" target="_blank" title="Ver votación original">🔗</a>`;
    }

    // Build bars for each coalition
    const tot = v.tot || [0, 0, 0, 0];
    const totalVotes = tot[0] + tot[1] + tot[2] + tot[3];

    const barsHtml = coalitions.map((c) => {
        const counts = v[c.key] || [0, 0, 0, 0];
        const a = counts[0], n = counts[1], b = counts[2], u = counts[3];
        const coalTotal = a + n + b + u;

        if (coalTotal === 0) return ""; // skip empty coalitions

        const maxBar = Math.max(totalVotes, 1);
        const pctA = (a / maxBar) * 100;
        const pctN = (n / maxBar) * 100;
        const pctB = (b / maxBar) * 100;
        const pctU = (u / maxBar) * 100;

        // Summary text
        const summaryParts = [];
        if (a) summaryParts.push(`${a} ✓`);
        if (n) summaryParts.push(`${n} ✗`);
        if (b) summaryParts.push(`${b} ○`);
        if (u) summaryParts.push(`${u} —`);
        const summary = summaryParts.join("  ");

        return `
        <div class="law-bar-row" data-party="${c.key}">
            <div class="law-bar-label">${c.label}</div>
            <div class="law-bar-track">
                <div class="law-bar-seg bar-afirm" style="width:${pctA}%"></div>
                <div class="law-bar-seg bar-neg" style="width:${pctN}%"></div>
                <div class="law-bar-seg bar-abst" style="width:${pctB}%"></div>
                <div class="law-bar-seg bar-aus" style="width:${pctU}%"></div>
            </div>
            <div class="law-bar-counts">${summary}</div>
        </div>`;
    }).join("");

    // Total row
    const totA = tot[0], totN = tot[1], totB = tot[2], totU = tot[3];
    const totParts = [];
    if (totA) totParts.push(`${totA} ✓`);
    if (totN) totParts.push(`${totN} ✗`);
    if (totB) totParts.push(`${totB} ○`);
    if (totU) totParts.push(`${totU} —`);

    const totalRow = `
    <div class="law-bar-row law-bar-total">
        <div class="law-bar-label">Total</div>
        <div class="law-bar-track">
            <div class="law-bar-seg bar-afirm" style="width:${(totA / Math.max(totalVotes,1)) * 100}%"></div>
            <div class="law-bar-seg bar-neg" style="width:${(totN / Math.max(totalVotes,1)) * 100}%"></div>
            <div class="law-bar-seg bar-abst" style="width:${(totB / Math.max(totalVotes,1)) * 100}%"></div>
            <div class="law-bar-seg bar-aus" style="width:${(totU / Math.max(totalVotes,1)) * 100}%"></div>
        </div>
        <div class="law-bar-counts">${totParts.join("  ")}</div>
    </div>`;

    // Show separator if multiple votaciones
    const showTitle = totalCount > 1;

    return `
    <div class="law-votacion-block${!showTitle ? " law-votacion-single" : ""}" data-vi="${v.vi != null ? v.vi : ''}">
        ${showTitle ? `
        <div class="law-votacion-header">
            <div class="law-votacion-topline">
                ${sectionLabel ? `<span class="law-votacion-type">${escapeHtml(sectionLabel)}</span>` : ""}
                <span class="law-votacion-date">${escapeHtml(dateStr)}</span>
                ${resultBadge}
                ${linkHtml}
            </div>
            ${fullTitle ? `<div class="law-votacion-fullname">${escapeHtml(fullTitle)}</div>` : ""}
        </div>` : `
        <div class="law-votacion-header law-votacion-header-single">
            <span class="law-votacion-date">${escapeHtml(dateStr)}</span>
            ${resultBadge}
            ${linkHtml}
        </div>`}
        <div class="law-bars-container">
            ${barsHtml}
            ${totalRow}
        </div>
        <div class="law-voter-list" style="display:none"></div>
    </div>`;
}

function shareTwitterLaw() {
    if (!currentSelectedLaw) return;
    const name = currentSelectedLaw.n || "una ley";
    const text = `Mirá cómo votó cada bloque "${name}" en el Congreso Argentino 🗳️`;
    const base = window.location.origin + window.location.pathname;
    const url = encodeURIComponent(base);
    const tweetUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${url}`;
    window.open(tweetUrl, "_blank", "width=600,height=400");
}

// ===========================================================================
//  VOTE DETAIL (per-bar click drill-down)
// ===========================================================================

const _votesYearCache = {};   // { year: { n: [...], v: {...} } }
const _votesYearPromise = {}; // { year: Promise }

const PARTY_LABELS = {
    pj: "PJ / UxP", ucr: "UCR", pro: "PRO",
    lla: "LLA", cc: "CC - ARI", oth: "Otros",
};
const VOTE_TYPE_LABELS = ["Afirmativo", "Negativo", "Abstención", "Ausente"];
const VOTE_TYPE_CLASSES = ["voter-afirm", "voter-neg", "voter-abst", "voter-aus"];
const ALL_PARTY_KEYS = ["pj", "ucr", "pro", "lla", "cc", "oth"];

function loadVotesYear(year) {
    if (_votesYearCache[year]) return Promise.resolve(_votesYearCache[year]);
    if (_votesYearPromise[year]) return _votesYearPromise[year];
    _votesYearPromise[year] = fetch(`${DATA_PATH}/votes/votes_${year}.json`)
        .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(data => { _votesYearCache[year] = data; return data; })
        .catch(e => { console.warn(`Failed to load votes for ${year}`, e); delete _votesYearPromise[year]; return null; });
    return _votesYearPromise[year];
}

function resolveVoterNames(yearData, vi) {
    if (!yearData) return null;
    const entry = yearData.v[String(vi)];
    if (!entry) return null;
    const names = yearData.n;
    const resolved = {};
    for (const pk of ALL_PARTY_KEYS) {
        if (!entry[pk]) continue;
        resolved[pk] = entry[pk].map(arr => arr.map(idx => names[idx]));
    }
    return resolved;
}

function onBarSegmentClick(e) {
    const seg = e.target.closest(".law-bar-seg");
    if (!seg) return;
    if (parseFloat(seg.style.width) < 0.01) return;

    const row = seg.closest(".law-bar-row");
    const block = seg.closest(".law-votacion-block");
    if (!block) return;
    const vi = block.dataset.vi;
    if (vi === "" || vi == null) return;

    const listEl = block.querySelector(".law-voter-list");
    if (!listEl) return;

    const year = currentSelectedLaw && currentSelectedLaw.y;
    if (!year) return;

    const party = row.dataset.party || "all";

    let voteIdx = -1;
    if (seg.classList.contains("bar-afirm")) voteIdx = 0;
    else if (seg.classList.contains("bar-neg")) voteIdx = 1;
    else if (seg.classList.contains("bar-abst")) voteIdx = 2;
    else if (seg.classList.contains("bar-aus")) voteIdx = 3;
    if (voteIdx < 0) return;

    const filterKey = `${party}_${voteIdx}`;
    if (listEl.style.display !== "none" && listEl.dataset.filter === filterKey) {
        listEl.style.display = "none";
        listEl.innerHTML = "";
        listEl.dataset.filter = "";
        return;
    }

    listEl.style.display = "block";
    listEl.dataset.filter = filterKey;
    listEl.innerHTML = `<div class="voter-loading">Cargando…</div>`;

    loadVotesYear(year).then(yearData => {
        if (listEl.dataset.filter !== filterKey) return;
        const detail = resolveVoterNames(yearData, vi);
        if (!detail) {
            listEl.innerHTML = `<div class="voter-loading">No hay datos disponibles.</div>`;
            return;
        }
        renderVoterList(listEl, detail, party, voteIdx);
    });
}

function renderVoterList(listEl, detail, party, voteIdx) {
    const parties = party === "all" ? ALL_PARTY_KEYS : [party];
    const voteLabel = VOTE_TYPE_LABELS[voteIdx];
    const voteCls = VOTE_TYPE_CLASSES[voteIdx];

    // Collect voters grouped by party
    let totalCount = 0;
    const groups = [];
    for (const pk of parties) {
        const names = (detail[pk] && detail[pk][voteIdx]) || [];
        if (names.length === 0) continue;
        const sorted = names.slice().sort((a, b) => a.localeCompare(b, "es"));
        totalCount += sorted.length;
        groups.push({ pk, label: PARTY_LABELS[pk] || pk, names: sorted });
    }

    if (totalCount === 0) {
        listEl.innerHTML = `<div class="voter-loading">Sin legisladores.</div>`;
        return;
    }

    // Header
    const partyTitle = party === "all" ? "Todos" : (PARTY_LABELS[party] || party);
    let html = `<div class="voter-header ${voteCls}">
        <span class="voter-header-label">${escapeHtml(partyTitle)} — ${escapeHtml(voteLabel)}</span>
        <span class="voter-header-count">${totalCount}</span>
        <button class="voter-close" onclick="this.closest('.law-voter-list').style.display='none'" title="Cerrar">✕</button>
    </div>`;

    // Build lookup set from loaded index so we can link known legislators
    const knownKeys = new Set(legislatorsData.map(l => l.k));

    // Body
    html += `<div class="voter-body">`;
    for (const g of groups) {
        if (parties.length > 1) {
            html += `<div class="voter-group-header" data-party="${g.pk}">${escapeHtml(g.label)} <span class="voter-group-count">(${g.names.length})</span></div>`;
        }
        for (const name of g.names) {
            if (knownKeys.has(name)) {
                html += `<div class="voter-item ${voteCls}"><a class="voter-link" href="#" data-key="${escapeAttr(name)}">${escapeHtml(name)}</a></div>`;
            } else {
                html += `<div class="voter-item ${voteCls}">${escapeHtml(name)}</div>`;
            }
        }
    }
    html += `</div>`;

    listEl.innerHTML = html;
}

// Attach bar-click listener via delegation on the law detail body
document.addEventListener("click", function (e) {
    if (e.target.closest(".law-bar-seg")) {
        onBarSegmentClick(e);
    }
    // Voter name → legislator detail
    const voterLink = e.target.closest(".voter-link");
    if (voterLink) {
        e.preventDefault();
        loadLegislatorDetail(voterLink.dataset.key);
    }
});

// ===========================================================================
//  RANKING SECTION
// ===========================================================================

// Ranking 1: Votes
let rvPage = 1, rvPageSize = 5, rvSortCol = "tv", rvSortAsc = false;
// Ranking 2: Alignment
let raPage = 1, raPageSize = 5, raSortCol = "vpj", raSortAsc = false;

function renderRankingTable(prefix, sortCol, asc, columns, cellRenderer, dataSource) {
    const chamberFilter = document.getElementById(prefix + "-chamber")?.value || "";
    const coalitionFilter = document.getElementById(prefix + "-coalition")?.value || "";
    const pageSize = prefix === "rv" ? rvPageSize : raPageSize;
    let page_ref = prefix === "rv" ? { get: () => rvPage, set: v => { rvPage = v; } }
                                    : { get: () => raPage, set: v => { raPage = v; } };

    let filtered = (dataSource || legislatorsData).filter(l => {
        if (l.tv < 100) return false;
        if (chamberFilter && !l.c.includes(chamberFilter)) return false;
        if (coalitionFilter && l.co !== coalitionFilter) return false;
        return true;
    });

    filtered.sort((a, b) => {
        let va = a[sortCol], vb = b[sortCol];
        if (va === null || va === undefined) va = -Infinity;
        if (vb === null || vb === undefined) vb = -Infinity;
        return asc ? va - vb : vb - va;
    });

    const total = filtered.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (page_ref.get() > totalPages) page_ref.set(totalPages);

    const start = (page_ref.get() - 1) * pageSize;
    const pageData = filtered.slice(start, start + pageSize);

    // Pre-compute competition ranks (ties share the same rank)
    const ranks = [];
    for (let i = 0; i < filtered.length; i++) {
        if (i === 0) { ranks.push(1); continue; }
        const cur = filtered[i][sortCol] ?? -Infinity;
        const prev = filtered[i - 1][sortCol] ?? -Infinity;
        ranks.push(cur === prev ? ranks[i - 1] : i + 1);
    }

    const tbody = document.getElementById(prefix + "-tbody");
    const medals = {
        1: '<span class="ranking-medal ranking-medal-gold" title="#1">🥇</span>',
        2: '<span class="ranking-medal ranking-medal-silver" title="#2">🥈</span>',
        3: '<span class="ranking-medal ranking-medal-bronze" title="#3">🥉</span>',
    };
    tbody.innerHTML = pageData.map((l, i) => {
        const rank = ranks[start + i];
        const medal = medals[rank] || '';
        return `<tr>
            <td>${rank} ${medal}</td>
            <td><a class="ranking-name-link" data-key="${escapeAttr(l.k)}">${escapeHtml(l.n)}</a></td>
            <td class="ranking-cell-bloc">${escapeHtml(l.b)}</td>
            ${cellRenderer(l)}
        </tr>`;
    }).join("");

    tbody.querySelectorAll(".ranking-name-link").forEach(el => {
        el.addEventListener("click", (e) => {
            e.preventDefault();
            loadLegislatorDetail(el.dataset.key);
        });
    });

    // Update sort column highlight
    const table = document.getElementById(prefix + "-table");
    table.querySelectorAll(".ranking-sortable").forEach(th => {
        th.classList.toggle("sort-active", th.dataset.col === sortCol);
        const arrow = asc ? " ▲" : " ▼";
        th.textContent = th.textContent.replace(/ [▲▼]$/, "");
        if (th.dataset.col === sortCol) th.textContent += arrow;
    });

    // Pagination
    const pagEl = document.getElementById(prefix + "-pagination");
    if (totalPages <= 1) { pagEl.innerHTML = ""; return; }
    let html = "";
    const curPage = page_ref.get();
    if (curPage > 1) html += `<button data-p="${curPage - 1}">‹</button>`;
    const maxBtns = 7;
    let pStart = Math.max(1, curPage - Math.floor(maxBtns / 2));
    let pEnd = Math.min(totalPages, pStart + maxBtns - 1);
    if (pEnd - pStart < maxBtns - 1) pStart = Math.max(1, pEnd - maxBtns + 1);
    for (let p = pStart; p <= pEnd; p++) {
        html += `<button data-p="${p}" class="${p === curPage ? "active" : ""}">${p}</button>`;
    }
    if (curPage < totalPages) html += `<button data-p="${curPage + 1}">›</button>`;
    pagEl.innerHTML = html;
    pagEl.querySelectorAll("button[data-p]").forEach(btn => {
        btn.addEventListener("click", () => {
            page_ref.set(parseInt(btn.dataset.p, 10));
            if (prefix === "rv") renderRankingVotes();
            else renderRankingAlignment();
        });
    });
}

function renderRankingVotes() {
    const fmt = v => v !== null && v !== undefined ? v : "–";
    const fmtPct = v => v !== null && v !== undefined ? v + "%" : "–";
    renderRankingTable("rv", rvSortCol, rvSortAsc,
        ["tv", "pres", "aus"],
        l => `<td class="ranking-cell-num">${fmt(l.tv)}</td>
              <td class="ranking-cell-num">${fmtPct(l.pres)}</td>
              <td class="ranking-cell-num">${fmt(l.aus)}</td>`
    );
}

const COALITION_LABELS = { PJ: "PJ / UxP", UCR: "UCR / ARI", PRO: "JxC / PRO / UCR", LLA: "LLA / PRO", OTROS: "Otros" };

function renderRankingAlignment() {
    const fmt = v => v !== null && v !== undefined ? v : "–";
    // Build mandato-level rows: one row per legislator × coalition in by_co
    const expanded = [];
    for (const l of legislatorsData) {
        const byCo = l.by_co;
        if (!byCo) continue;
        for (const [co, vals] of Object.entries(byCo)) {
            expanded.push({
                k: l.k,
                n: l.n,
                c: l.c,
                p: l.p,
                b: vals.b || l.b,
                co: co,
                vpj: vals.vpj,
                vucr: vals.vucr,
                vpro: vals.vpro,
                vlla: vals.vlla,
                tv: vals.tv,
            });
        }
    }
    renderRankingTable("ra", raSortCol, raSortAsc,
        ["vpj", "vucr", "vpro", "vlla"],
        l => `<td class="ranking-cell-num">${fmt(l.vpj)}</td>
              <td class="ranking-cell-num">${fmt(l.vucr)}</td>
              <td class="ranking-cell-num">${fmt(l.vpro)}</td>
              <td class="ranking-cell-num">${fmt(l.vlla)}</td>`,
        expanded
    );
}

// Column label maps for export titles
const RANKING_COL_LABELS = {
    tv: "Total de Votaciones", pres: "Presentismo", aus: "Ausencias", abst: "Abstenciones",
    vpj: "Votos con PJ", vucr: "Votos con UCR", vpro: "Votos con PRO", vlla: "Votos con LLA",
};

function buildRankingExportTitle(prefix) {
    const sortCol = prefix === "rv" ? rvSortCol : raSortCol;
    const asc = prefix === "rv" ? rvSortAsc : raSortAsc;
    const colLabel = RANKING_COL_LABELS[sortCol] || sortCol;
    const dir = asc ? "(menor a mayor)" : "(mayor a menor)";
    const chamberEl = document.getElementById(prefix + "-chamber");
    const coalEl = document.getElementById(prefix + "-coalition");
    const chamber = chamberEl?.selectedOptions[0]?.textContent || "";
    const coal = coalEl?.selectedOptions[0]?.textContent || "";
    let subtitle = "";
    if (chamberEl?.value) subtitle += chamber;
    if (coalEl?.value) {
        if (prefix === "ra") {
            // Second ranking: add "Votados/as por una lista de la coalición..." prefix
            subtitle += (subtitle ? " · " : "") + `Votados/as por una lista de la coalición ${coal}`;
        } else {
            subtitle += (subtitle ? " · " : "") + coal;
        }
    }
    return {
        title: `Ranking por ${colLabel} ${dir}`,
        subtitle: subtitle || "Todos los legisladores",
    };
}

async function exportRankingTable(prefix, mode) {
    const table = document.getElementById(prefix + "-table");
    if (!table) return;
    const { title, subtitle } = buildRankingExportTitle(prefix);

    // Build off-screen card — same size/scale as other exports (360px × scale 3 = 1080px output)
    const card = document.createElement("div");
    card.style.cssText = "position:absolute;left:-9999px;top:0;background:#fff;padding:20px;width:520px;font-family:Inter,system-ui,sans-serif;";

    // Header
    const header = document.createElement("div");
    header.style.cssText = "text-align:center;margin-bottom:12px;";
    header.innerHTML = `<div style="font-size:18px;font-weight:700;color:#1e293b;">${escapeHtml(title)}</div>
        <div style="font-size:12px;color:#64748b;margin-top:3px;">${escapeHtml(subtitle)}</div>`;
    card.appendChild(header);

    // Clone table and limit to 5 rows
    const clonedTable = table.cloneNode(true);
    // auto layout so browser sizes data columns to fit header text
    clonedTable.style.cssText = "width:100%;font-size:11px;table-layout:auto;border-collapse:collapse;";

    const ths = clonedTable.querySelectorAll("thead th");
    // Constrain # and Bloque; let Legislador and data cols auto-size
    if (ths[0]) ths[0].style.width = "40px";
    if (ths[2]) { ths[2].style.maxWidth = "72px"; ths[2].style.width = "72px"; }

    clonedTable.querySelectorAll("th, td").forEach(cell => {
        cell.style.padding = "6px 4px";
        cell.style.whiteSpace = "normal";
        cell.style.wordBreak = "break-word";
        cell.style.overflow = "hidden";
        cell.style.maxWidth = "";
    });
    // Header cells don't wrap so each data column is at least as wide as its title
    clonedTable.querySelectorAll("th").forEach(th => { th.style.whiteSpace = "nowrap"; th.style.position = "static"; });
    // Keep legislator name (2nd column) at full size
    clonedTable.querySelectorAll("td:nth-child(2)").forEach(cell => { cell.style.fontSize = "13px"; });
    // Bloque column (3rd) smaller
    clonedTable.querySelectorAll("td:nth-child(3), th:nth-child(3)").forEach(cell => { cell.style.fontSize = "9px"; });
    const rows = clonedTable.querySelectorAll("tbody tr");
    const curPageSize = prefix === "rv" ? rvPageSize : raPageSize;
    const exportLimit = curPageSize <= 10 ? curPageSize : 10;
    for (let i = exportLimit; i < rows.length; i++) rows[i].remove();
    card.appendChild(clonedTable);

    const footer = document.createElement("div");
    footer.style.cssText = "display:flex;justify-content:space-between;margin-top:10px;font-size:11px;color:#94a3b8;";
    footer.innerHTML = `<span>${new Date().toLocaleDateString("es-AR")}</span><span>comovoto.dev.ar</span>`;
    card.appendChild(footer);

    document.body.appendChild(card);

    const btnId = mode === "copy" ? `btn-copy-${prefix}` : `btn-download-${prefix}`;
    const btn = document.getElementById(btnId);
    const originalText = btn.innerHTML;
    const filename = `ranking_${prefix === "rv" ? "votos" : "afinidad"}.png`;

    await captureAndExport({ card, btn, originalText, filename, mode, scale: 3 });
    card.remove();
}

// ===========================================================================
//  LEGISLATOR DETAIL
// ===========================================================================

async function loadLegislatorDetail(nameKey, urlParams) {
    hideSearchResults();

    // Increment request ID to invalidate any in-flight loads
    const thisRequest = ++loadRequestId;

    // Clean up previous detail state before showing new one
    cleanupLegislatorDetail();

    currentLegKey = nameKey;

    // Update URL so the page can be bookmarked / shared.
    // Only push a new state when the URL doesn't already point to this legislator.
    const currentLegInURL = new URLSearchParams(window.location.search).get("leg");
    if (currentLegInURL !== nameKey) {
        const shareParams = new URLSearchParams({ leg: nameKey });
        history.pushState({ leg: nameKey }, "", `?${shareParams}`);
    }

    const detailSection = document.getElementById("legislator-detail");
    detailSection.classList.remove("hidden");
    document.querySelector(".search-section").classList.add("hidden");
    document.getElementById("stats-bar").classList.add("hidden");
    document.getElementById("law-search-section").classList.add("hidden");
    document.getElementById("ranking-section").classList.add("hidden");

    // Show loading state
    document.getElementById("leg-name").textContent = "Cargando...";
    document.getElementById("leg-photo").style.display = "none";

    const safeKey = nameKey.replace(/[^A-Z0-9_]/g, "_").substring(0, 80);
    const url = `${DATA_PATH}/legislators/${safeKey}.json`;

    try {
        const resp = await fetch(url);
        // Check if this request is still the latest one
        if (thisRequest !== loadRequestId) return;
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        currentDetail = await resp.json();
        // Check again after parsing
        if (thisRequest !== loadRequestId) return;
        renderLegislatorDetail(currentDetail);

        // Apply URL-provided filters if this was loaded from a shared link
        if (urlParams) {
            if (urlParams.wy) {
                const wyfEl = document.getElementById("waffle-year-filter");
                if (wyfEl) {
                    const opt = Array.from(wyfEl.options).find(o => o.value === urlParams.wy);
                    if (opt) opt.selected = true;
                }
            }
            if (urlParams.wq) {
                const wlfEl = document.getElementById("waffle-law-filter");
                if (wlfEl) { wlfEl.value = urlParams.wq; }
            }
            if (urlParams.wy || urlParams.wq) {
                currentWafflePage = 1;
                renderWaffle();
            }
        }
    } catch (err) {
        if (thisRequest !== loadRequestId) return;
        console.error("Error loading legislator:", err);
        document.getElementById("leg-name").textContent = "Error al cargar datos";
    }

    window.scrollTo({ top: 0, behavior: "smooth" });
}

/**
 * Thoroughly clean up all legislator detail state to prevent data leaks
 * between different legislator views.
 */
function cleanupLegislatorDetail() {
    // Destroy charts
    if (chartAlignment) { chartAlignment.destroy(); chartAlignment = null; }
    if (chartYearly) { chartYearly.destroy(); chartYearly = null; }

    // Clear global data reference
    currentDetail = null;
    currentLegKey = null;

    // Reset pagination
    currentVotesPage = 1;
    currentWafflePage = 1;

    // Clear DOM elements to prevent stale data from showing
    document.getElementById("leg-name").textContent = "";
    document.getElementById("leg-photo").style.display = "none";
    document.getElementById("leg-chamber").textContent = "";
    document.getElementById("leg-bloc").textContent = "";
    document.getElementById("leg-province").textContent = "";
    document.getElementById("leg-alignment-summary").innerHTML = "";
    const _infoCard = document.getElementById("leg-info-card");
    if (_infoCard) _infoCard.style.display = "none";
    const _alignCard = document.getElementById("leg-alignment-card");
    if (_alignCard) _alignCard.style.display = "none";
    const _statsInline = document.getElementById("leg-stats-inline");
    if (_statsInline) _statsInline.style.display = "none";
    document.getElementById("waffle-card-name").innerHTML = "";
    document.getElementById("waffle-card-meta").innerHTML = "";
    document.getElementById("waffle-card-body").innerHTML = "";

    const wafflePag = document.getElementById("waffle-pagination");
    if (wafflePag) wafflePag.innerHTML = "";

    document.getElementById("votes-tbody").innerHTML = "";
    const votesPag = document.getElementById("votes-pagination");
    if (votesPag) votesPag.innerHTML = "";

    // Reset all filters
    const waffleYearFilter = document.getElementById("waffle-year-filter");
    if (waffleYearFilter) { waffleYearFilter.innerHTML = ""; }
    if (_waffleYearWidget) _waffleYearWidget.rebuild();
    const waffleLawFilter = document.getElementById("waffle-law-filter");
    if (waffleLawFilter) waffleLawFilter.value = "";
    const votesYearFilter = document.getElementById("votes-year-filter");
    if (votesYearFilter) votesYearFilter.innerHTML = '<option value="">Todos los años</option>';
    const votesTypeFilter = document.getElementById("votes-type-filter");
    if (votesTypeFilter) votesTypeFilter.value = "";
    const votesLawFilter = document.getElementById("votes-law-filter");
    if (votesLawFilter) votesLawFilter.value = "";
}

function renderLegislatorDetail(data) {
    // Header with photo
    document.getElementById("leg-name").textContent = data.name;

    // Photo
    const photoEl = document.getElementById("leg-photo");
    if (data.photo) {
        photoEl.src = data.photo;
        photoEl.alt = data.name;
        photoEl.style.display = "block";
        photoEl.onerror = () => { photoEl.style.display = "none"; };
    } else {
        photoEl.style.display = "none";
    }

    const chamberBadge = document.getElementById("leg-chamber");
    const chambers = data.chambers || [data.chamber];
    if (chambers.length > 1) {
        chamberBadge.textContent = "Dip. + Sen.";
        chamberBadge.className = "leg-chamber badge badge-both";
    } else {
        chamberBadge.textContent = chambers[0] === "diputados" ? "Diputado/a" : "Senador/a";
        chamberBadge.className = `leg-chamber badge badge-${chambers[0]}`;
    }

    const blocBadge = document.getElementById("leg-bloc");
    blocBadge.textContent = shortPartyName(data.bloc);
    blocBadge.className = `leg-bloc badge badge-${data.coalition.toLowerCase()}`;

    document.getElementById("leg-province").textContent = data.province;

    // Alignment summary — 3-column era grid (1993–2014 / 2015–2023 / 2024–2026)
    // Rendered into the standalone card below the Mandatos card.
    const alignSummary = document.getElementById("leg-alignment-summary");
    const alignCard    = document.getElementById("leg-alignment-card");
    alignSummary.innerHTML = "";

    const ERA_DEFS = [
        { label: "1993–2014", key: "1993-2014",
          opp: { key: "UCR", label: "UCR / ARI",       cls: "alignment-ucr" } },
        { label: "2015–2023", key: "2015-2023",
          opp: { key: "PRO", label: "JxC / PRO / UCR", cls: "alignment-pro" } },
        { label: "2024–2026", key: "2024-2026",
          opp: { key: "LLA", label: "LLA / PRO",        cls: "alignment-lla" } },
    ];

    const eraAl = data.era_alignment || {};
    // Only show the card if at least one era has data
    const hasAnyEraData = ERA_DEFS.some(era => {
        const ed = eraAl[era.key] || {};
        return ed["PJ"] !== null && ed["PJ"] !== undefined
            || ed[era.opp.key] !== null && ed[era.opp.key] !== undefined;
    });
    if (alignCard) alignCard.style.display = hasAnyEraData ? "block" : "none";

    const gridEl = document.createElement("div");
    gridEl.className = "alignment-grid-3col";
    for (const era of ERA_DEFS) {
        const eraData = eraAl[era.key] || {};
        const pjPct  = eraData["PJ"]  ?? null;
        const oppPct = eraData[era.opp.key] ?? null;
        const fmt    = v => v !== null ? v + "%" : "N/A";
        const col    = document.createElement("div");
        col.className = "alignment-era-col";
        col.innerHTML = `
            <div class="alignment-era-label">${era.label}</div>
            <div class="alignment-card alignment-pj">
                <div class="alignment-label">PJ / FdT / UxP</div>
                <div class="alignment-value">${fmt(pjPct)}</div>
            </div>
            <div class="alignment-card ${era.opp.cls}">
                <div class="alignment-label">${era.opp.label}</div>
                <div class="alignment-value">${fmt(oppPct)}</div>
            </div>
        `;
        gridEl.appendChild(col);
    }
    alignSummary.appendChild(gridEl);

    // Presentismo + terms info card
    const infoCard = document.getElementById("leg-info-card");
    const stats = data.yearly_stats || {};
    const trailingAus = data.trailing_ausente || 0;
    const activeYears = Object.keys(stats).filter((y) => {
        const s = stats[y];
        return (s.AFIRMATIVO||0)+(s.NEGATIVO||0)+(s.ABSTENCION||0)+(s.AUSENTE||0) >= 5;
    });
    let totalV = 0, totalPresent = 0;
    for (const y of activeYears) {
        const s = stats[y];
        totalV       += (s.total || 0);
        totalPresent += (s.AFIRMATIVO||0) + (s.NEGATIVO||0) + (s.ABSTENCION||0);
    }
    // Exclude trailing AUSENTE votes (post-departure absences)
    const effectiveV = totalV - trailingAus;
    const presentismoPct = effectiveV > 0 ? Math.round(totalPresent / effectiveV * 100) : null;
    document.getElementById("leg-presentismo").textContent =
        presentismoPct !== null ? presentismoPct + "\u00a0%" : "N/A";

    const terms = data.terms || [];
    document.getElementById("leg-mandatos-count").textContent = terms.length || "N/A";

    const statsInline = document.getElementById("leg-stats-inline");
    if (statsInline) statsInline.style.display = (presentismoPct !== null || terms.length > 0) ? "flex" : "none";

    const termsList = document.getElementById("leg-terms-list");
    if (terms.length > 0) {
        const chLabel = (ch) => ch === "diputados" ? "Diputado/a" : "Senador/a";
        const chCls   = (ch) => ch === "diputados" ? "badge-diputados" : "badge-senadores";
        const rows = terms.map((t, idx) => {
            const period = t.yf === t.yt ? t.yf : `${t.yf}\u2013${t.yt}`;
            // Per-term presentismo: sum yearly_stats for years within [yf, yt]
            let termV = 0, termPres = 0;
            for (let y = t.yf; y <= t.yt; y++) {
                const s = stats[String(y)];
                if (!s || (s.total||0) < 1) continue;
                termV    += (s.total || 0);
                termPres += (s.AFIRMATIVO||0) + (s.NEGATIVO||0) + (s.ABSTENCION||0);
            }
            // For the last term, exclude trailing post-departure absences
            const termTrail = (idx === terms.length - 1) ? trailingAus : 0;
            const effTermV = termV - termTrail;
            const tPct = effTermV > 0 ? Math.round(termPres / effTermV * 100) + "\u00a0%" : "N/A";
            return `<tr>
                <td><span class="badge ${chCls(t.ch)}">${chLabel(t.ch)}</span></td>
                <td>${period}</td>
                <td>${escapeHtml(t.p || "")}</td>
                <td>${escapeHtml(t.b)}</td>
                <td>${tPct}</td>
            </tr>`;
        }).join("");
        termsList.innerHTML = `<table class="leg-terms-table">
            <thead><tr><th>C\u00e1mara</th><th>Per\u00edodo</th><th>Provincia</th><th>Partido</th><th>Presentismo</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
    } else {
        termsList.innerHTML = "";
    }
    infoCard.style.display = terms.length > 0 ? "block" : "none";

    // Waffle card header — include small portrait next to the politician name
    const waffleNameEl = document.getElementById("waffle-card-name");
    const smallPhoto = data.photo
        ? `<img class="waffle-header-photo" src="${escapeAttr(data.photo)}" alt="">`
        : `<span class="waffle-header-photo no-photo">👤</span>`;
    waffleNameEl.innerHTML = `
        <div class="waffle-header-left">
            ${smallPhoto}
            <div class="waffle-card-name-text">${escapeHtml(data.name)}</div>
        </div>`;

    const chamberLabel = chambers.length > 1 ? "HCD + HCS" : (chambers[0] === "diputados" ? "HCD" : "HCS");
    document.getElementById("waffle-card-meta").innerHTML = `
        <span class="badge badge-${chambers[0]}">${chamberLabel}</span>
        <span class="badge badge-${data.coalition.toLowerCase()}">${shortPartyName(data.bloc)}</span>
    `;

    // Populate waffle year filter (only years that have notable laws)
    const waffleYearFilter = document.getElementById("waffle-year-filter");
    const notableLawYears = [...new Set(
        (data.laws || []).filter((l) => l.notable).map((l) => String(l.year))
    )].sort();
    waffleYearFilter.innerHTML = notableLawYears.map(y => `<option value="${y}">${y}</option>`).join("");
    if (_waffleYearWidget) _waffleYearWidget.rebuild();

    // Reset waffle law filter
    document.getElementById("waffle-law-filter").value = "";

    // Reset waffle page
    currentWafflePage = 1;

    // Render waffle
    renderWaffle();

    // Charts
    const years = Object.keys(data.yearly_stats).sort();
    renderAlignmentChart(data);
    renderYearlyChart(data);

    // Populate votes year filter
    const yearFilter = document.getElementById("votes-year-filter");
    yearFilter.innerHTML = '<option value="">Todos los años</option>';
    for (const y of years) {
        yearFilter.innerHTML += `<option value="${y}">${y}</option>`;
    }
    document.getElementById("votes-type-filter").value = "";
    document.getElementById("votes-law-filter").value = "";

    currentVotesPage = 1;
    renderVotesTable();
}

function showSearchView() {
    document.getElementById("legislator-detail").classList.add("hidden");
    document.querySelector(".search-section").classList.remove("hidden");
    document.getElementById("stats-bar").classList.remove("hidden");
    document.getElementById("law-search-section").classList.remove("hidden");
    document.getElementById("ranking-section").classList.remove("hidden");

    // Clear deep-link params from URL without reload
    if (window.location.search) {
        history.replaceState(null, "", window.location.pathname);
    }

    // Invalidate any in-flight loads
    loadRequestId++;

    // Clean up all detail state
    cleanupLegislatorDetail();
}

// ===========================================================================
//  WAFFLE VISUALIZATION
// ===========================================================================

function renderWaffle() {
    if (!currentDetail) return;

    const wyfEl = document.getElementById("waffle-year-filter");
    const selectedYears = wyfEl
        ? new Set(Array.from(wyfEl.selectedOptions).map(o => o.value).filter(Boolean))
        : new Set();
    const lawFilter = document.getElementById("waffle-law-filter").value.trim().toLowerCase();

    let laws = currentDetail.laws || [];

    // Always filter to notable laws first
    laws = laws.filter((l) => l.notable === true);

    // Apply text filter
    if (lawFilter) {
        laws = laws.filter((l) => l.name.toLowerCase().includes(lawFilter));
    }

    // Apply year filter
    if (selectedYears.size > 0) {
        laws = laws.filter((l) => selectedYears.has(String(l.year)));
    }

    const body = document.getElementById("waffle-card-body");
    const paginationContainer = document.getElementById("waffle-pagination");

    if (laws.length === 0) {
        body.innerHTML = '<div class="waffle-empty">No hay leyes destacadas para los filtros seleccionados</div>';
        if (paginationContainer) paginationContainer.innerHTML = "";
        return;
    }

    // Pagination
    const totalPages = Math.max(1, Math.ceil(laws.length / LAWS_PER_PAGE));
    if (currentWafflePage > totalPages) currentWafflePage = totalPages;
    const start = (currentWafflePage - 1) * LAWS_PER_PAGE;
    const pageLaws = laws.slice(start, start + LAWS_PER_PAGE);

    // Render law rows
    let html = "";
    for (let lawIdx = 0; lawIdx < pageLaws.length; lawIdx++) {
        const law = pageLaws[lawIdx];
        const tiles = law.votes.map((vote, voteIdx) => {
            const isGeneral = vote.g === true;
            const cls = `waffle-tile tile-${vote.v}${isGeneral ? " tile-general" : ""} tile-clickable`;
            const icon = voteIcon(vote.v);
            const label = vote.al || (isGeneral ? "En General" : "");
            const tooltip = label ? `${label}: ${formatVoteShort(vote.v)}` : formatVoteShort(vote.v);
            return `<div class="${cls}" title="${escapeAttr(tooltip)}" data-law-idx="${lawIdx}" data-vote-idx="${voteIdx}">${icon}</div>`;
        }).join("");

        const displayName = escapeHtml(truncate(law.name, 60));
        const yearLabel = law.year ? `<span class="waffle-law-year">${law.year}</span>` : "";

        html += `
        <div class="waffle-law-row">
            <div class="waffle-law-label">
                <span class="waffle-law-name">${displayName}</span>
                ${yearLabel}
            </div>
            <div class="waffle-tiles">${tiles}</div>
        </div>`;
    }

    body.innerHTML = html;

    // Attach click handlers to waffle tiles for popup
    body.querySelectorAll(".tile-clickable").forEach((tile) => {
        tile.addEventListener("click", () => {
            const lIdx = parseInt(tile.dataset.lawIdx);
            const vIdx = parseInt(tile.dataset.voteIdx);
            const law = pageLaws[lIdx];
            if (law && law.votes[vIdx]) {
                showVotePopup(law.name, law.votes[vIdx], law.year);
            }
        });
    });

    // Render waffle pagination
    if (paginationContainer) {
            if (totalPages <= 1) {
            paginationContainer.innerHTML = `<span style="font-size:0.8rem;color:var(--color-text-secondary)">${laws.length} leyes</span>`;
        } else {
            let pHtml = "";
            if (currentWafflePage > 1) {
                pHtml += `<button data-page="${currentWafflePage - 1}">← Ant.</button>`;
            }
            for (let p = 1; p <= totalPages; p++) {
                if (p === 1 || p === totalPages || Math.abs(p - currentWafflePage) <= 2) {
                    pHtml += `<button data-page="${p}" class="${p === currentWafflePage ? "active" : ""}">${p}</button>`;
                } else if (Math.abs(p - currentWafflePage) === 3) {
                    pHtml += `<span style="padding:0.4rem;color:var(--color-text-secondary)">…</span>`;
                }
            }
            if (currentWafflePage < totalPages) {
                pHtml += `<button data-page="${currentWafflePage + 1}">Sig. →</button>`;
            }
            pHtml += `<span style="font-size:0.75rem;color:var(--color-text-secondary);margin-left:0.5rem">${laws.length} leyes</span>`;
            paginationContainer.innerHTML = pHtml;

            paginationContainer.querySelectorAll("button[data-page]").forEach((btn) => {
                btn.addEventListener("click", () => {
                    currentWafflePage = parseInt(btn.dataset.page);
                    renderWaffle();
                    document.getElementById("waffle-section").scrollIntoView({ behavior: "smooth" });
                });
            });
        }
    }
}

function voteIcon(vote) {
    switch (vote) {
        case "AFIRMATIVO": return "✓";
        case "NEGATIVO": return "✗";
        case "ABSTENCION": return "○";
        case "AUSENTE": return "—";
        case "PRESIDENTE": return "⚑";
        default: return "?";
    }
}

// ===========================================================================
//  VOTE INFO POPUP
// ===========================================================================

function showVotePopup(lawName, vote, lawYear) {
    const overlay = document.getElementById("vote-popup-overlay");
    document.getElementById("vote-popup-title").textContent = lawName || "Votación";
    document.getElementById("vote-popup-fullname").textContent = vote.t || vote.al || "—";

    // Try to find the date from the top-level votes if not in law-level vote
    let dateStr = vote.d || "";
    if (!dateStr && vote.vid && vote.ch) {
        const detailData = currentDetail;
        if (detailData) {
            const match = (detailData.votes || []).find(
                (v) => String(v.vid) === String(vote.vid) && v.ch === vote.ch
            );
            if (match) dateStr = match.d || "";
        }
    }
    if (!dateStr && lawYear) dateStr = String(lawYear);
    document.getElementById("vote-popup-date").textContent = dateStr || "—";

    document.getElementById("vote-popup-article").textContent = vote.al || "—";

    const voteEl = document.getElementById("vote-popup-vote");
    voteEl.innerHTML = `<span class="vote-chip vote-${vote.v}">${formatVote(vote.v)}</span>`;

    const linkRow = document.getElementById("vote-popup-link-row");
    const linkEl = document.getElementById("vote-popup-link");
    let href = vote.url || "";
    if (!href && vote.ch === "diputados" && vote.vid) {
        href = `https://votaciones.hcdn.gob.ar/votacion/${vote.vid}`;
    } else if (!href && vote.ch === "senadores" && vote.vid) {
        href = `https://www.senado.gob.ar/votaciones/detalleActa/${vote.vid}`;
    }
    if (href) {
        linkEl.href = href;
        linkRow.style.display = "";
    } else {
        linkRow.style.display = "none";
    }

    overlay.classList.remove("hidden");
}

function hideVotePopup() {
    document.getElementById("vote-popup-overlay").classList.add("hidden");
}

// ===========================================================================
//  SHARE / EXPORT
// ===========================================================================

/** Returns true when the browser is likely a mobile / touch device. */
const isMobile = () =>
    /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent) ||
    window.matchMedia("(pointer: coarse)").matches;

/**
 * Populate an export-card header element with the legislator's photo, name,
 * chamber label, party and province.  Returns the generated HTML string.
 */
function populateExportHeader(headerEl, d) {
    const chambers = d.chambers || [d.chamber];
    const chamberLabel = chambers.length > 1
        ? "Dip. + Sen."
        : chambers[0] === "diputados" ? "Diputado/a" : "Senador/a";
    const photoHtml = d.photo
        ? `<img src="${d.photo}" class="aec-photo" alt="" crossorigin="anonymous">`
        : `<div class="aec-photo-placeholder"></div>`;
    headerEl.innerHTML = `
        <div class="aec-header-inner">
            ${photoHtml}
            <div class="aec-info">
                <div class="aec-name">${escapeHtml(d.name)}</div>
                <div class="aec-meta">${chamberLabel}&ensp;&middot;&ensp;${escapeHtml(shortPartyName(d.bloc))}&ensp;&middot;&ensp;${escapeHtml(d.province)}</div>
            </div>
        </div>`;
}

/**
 * Shared capture-and-export logic used by all simple export-card functions.
 * Handles html2canvas rendering, clipboard/download dispatch (with mobile
 * fallback), button state management, and hiding the card in `finally`.
 *
 * @param {object} opts
 * @param {HTMLElement} opts.card            – the off-screen card element
 * @param {HTMLElement} opts.btn             – the button that triggered the action
 * @param {string}      opts.originalText    – btn.innerHTML to restore afterwards
 * @param {string}      opts.filename        – download filename (without path)
 * @param {'copy'|'download'} opts.mode
 * @param {HTMLElement} [opts.photoContainer] – element containing img.aec-photo to wait for
 */
async function captureAndExport({ card, btn, originalText, filename, mode, photoContainer, scale = 3 }) {
    btn.innerHTML = "⏳ Generando...";
    btn.disabled  = true;

    const mobile = isMobile();

    function triggerDl(blob) {
        const url = URL.createObjectURL(blob);
        const a   = document.createElement("a");
        a.href     = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    try {
        const photoImg = (photoContainer || card).querySelector("img.aec-photo");
        if (photoImg && !photoImg.complete) {
            await new Promise((res) => { photoImg.onload = res; photoImg.onerror = res; });
        }
        const canvas = await html2canvas(card, {
            backgroundColor: "#ffffff", scale, useCORS: true, logging: false,
        });
        const blob = await new Promise((res, rej) =>
            canvas.toBlob((b) => (b ? res(b) : rej(new Error("toBlob failed"))), "image/png"));

        if (mode === "download") {
            triggerDl(blob);
            btn.innerHTML = "✓ Descargado!";
        } else {
            try {
                await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
                btn.innerHTML = "✓ Copiado!";
            } catch (e) {
                console.error("Clipboard write failed:", e);
                btn.innerHTML = "No se pudo copiar";
            }
        }
        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
    } catch (err) {
        console.error("Error exporting card:", err);
        btn.innerHTML = "Error :(";
        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
    } finally {
        card.style.display = "none";
    }
}

/**
 * Render a Chart.js chart to an off-screen canvas at export resolution.
 * Returns a data-URL string (PNG).
 */
function renderChartForExport(chartInstance, opts = {}) {
    const EXPORT_W = 1080;
    const EXPORT_H = 540;
    const offCanvas = document.createElement("canvas");
    offCanvas.width  = EXPORT_W;
    offCanvas.height = EXPORT_H;

    const cfg = chartInstance.config;
    const datasets = cfg.data.datasets.map((ds) => {
        const copy = { ...ds };
        if (opts.pointRadius != null)      copy.pointRadius      = opts.pointRadius;
        if (opts.pointHoverRadius != null)  copy.pointHoverRadius = opts.pointHoverRadius;
        return copy;
    });

    const legendLabels = {
        ...cfg.options.plugins.legend?.labels,
        font: { size: opts.legendFontSize || 22 },
        padding: 20,
    };
    if (opts.legendBoxWidth != null) {
        legendLabels.boxWidth  = opts.legendBoxWidth;
        legendLabels.boxHeight = opts.legendBoxHeight ?? opts.legendBoxWidth;
    }

    const chartOpts = {
        animation: false,
        responsive: false,
        maintainAspectRatio: false,
        layout: cfg.options.layout,
        plugins: {
            legend: { ...cfg.options.plugins.legend, labels: legendLabels },
            tooltip: { enabled: false },
        },
        scales: {
            x: {
                ...cfg.options.scales?.x,
                ticks: { ...cfg.options.scales?.x?.ticks, font: { size: opts.tickFontSize || 20 }, maxRotation: 45, minRotation: 45 },
            },
            y: {
                ...cfg.options.scales?.y,
                ticks: { ...cfg.options.scales?.y?.ticks, font: { size: opts.tickFontSize || 20 } },
            },
        },
    };
    if (opts.interactionMode) chartOpts.interaction = { mode: opts.interactionMode };

    const offChart = new Chart(offCanvas, {
        type: cfg.type,
        data: { labels: cfg.data.labels, datasets },
        options: chartOpts,
    });
    offChart.resize(EXPORT_W, EXPORT_H);
    const dataUrl = offCanvas.toDataURL("image/png", 1);
    offChart.destroy();
    return dataUrl;
}

/**
 * Export a DOM card as a PNG image.
 * @param {string} cardId  - id of the element to capture
 * @param {string} btnId   - id of the button that triggered the action
 * @param {'copy'|'download'} mode
 *   'copy'     → clipboard on desktop; falls back to download on mobile
 *   'download' → always triggers a file download
 */
async function exportCardImage(cardId, btnId, mode = "copy") {
    const card = document.getElementById(cardId);
    const btn  = document.getElementById(btnId);
    const originalText = btn.innerHTML;

    // Clamp the card to 360 CSS-px (→ 1080 px at 3× scale) so the exported
    // image is a crisp 1080-wide share card regardless of viewport width.
    const EXPORT_MAX_W = 360;
    const prevWidth    = card.style.width;
    const prevMaxWidth = card.style.maxWidth;
    card.style.width    = EXPORT_MAX_W + "px";
    card.style.maxWidth = EXPORT_MAX_W + "px";
    card.classList.add("exporting");

    // Fix waffle label column width so all tile columns are left-aligned.
    // Measure every law name with an offscreen canvas, find the widest, and
    // pin every .waffle-law-label to that width before html2canvas renders.
    const lawLabels = card.querySelectorAll(".waffle-law-label");
    if (lawLabels.length > 0) {
        const measCanvas = document.createElement("canvas");
        const measCtx    = measCanvas.getContext("2d");
        // Match the font used by .waffle-law-name inside .exporting
        measCtx.font = "600 0.75rem/1.3 system-ui, sans-serif";
        let maxPx = 0;
        lawLabels.forEach(label => {
            const nameEl = label.querySelector(".waffle-law-name");
            const text   = nameEl ? nameEl.textContent : label.textContent;
            const w = measCtx.measureText(text).width;
            if (w > maxPx) maxPx = w;
        });
        // Add a small padding (6 px) and clamp to the allowed range (80–110 px)
        const labelW = Math.min(110, Math.max(80, Math.ceil(maxPx) + 6));
        lawLabels.forEach(label => {
            label.style.width    = labelW + "px";
            label.style.minWidth = labelW + "px";
            label.style.maxWidth = labelW + "px";
        });
    }

    void card.offsetHeight; // force reflow before capture

    const mobile = isMobile();

    /** Trigger a browser download for a Blob. */
    function triggerDownload(blob) {
        const url = URL.createObjectURL(blob);
        const a   = document.createElement("a");
        a.href     = url;
        a.download = `como_voto_${cardId}.png`;
        a.click();
        URL.revokeObjectURL(url);
    }

    try {
        btn.innerHTML = "⏳ Generando...";
        btn.disabled  = true;

        if (mode === "download") {
            // ── DOWNLOAD MODE ──────────────────────────────────────────────
            // Try CORS-clean render first; fall back to allowTaint for
            // cross-origin photos (tainted canvas is fine for download).
            try {
                const canvas = await html2canvas(card, {
                    backgroundColor: "#ffffff", scale: 3, useCORS: true, logging: false,
                });
                const blob = await new Promise((res, rej) =>
                    canvas.toBlob((b) => (b ? res(b) : rej(new Error("toBlob failed"))), "image/png"));
                triggerDownload(blob);
                btn.innerHTML = "✓ Descargado!";
                setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
            } catch (err) {
                try {
                    const canvas2 = await html2canvas(card, {
                        backgroundColor: "#ffffff", scale: 3,
                        useCORS: false, allowTaint: true, logging: false,
                    });
                    const blob2 = await new Promise((res, rej) =>
                        canvas2.toBlob((b) => (b ? res(b) : rej(new Error("toBlob failed"))), "image/png"));
                    triggerDownload(blob2);
                    btn.innerHTML = "✓ Descargado!";
                    setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
                } catch (err2) {
                    console.error("All attempts to generate image failed:", err2);
                    btn.innerHTML = "Error :(";
                    setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
                }
            }
        } else {
            // ── COPY MODE ──────────────────────────────────────────────────
            // Try html2canvas with CORS (needed for clipboard – tainted canvas
            // cannot be written to clipboard).
            try {
                const canvas = await html2canvas(card, {
                    backgroundColor: "#ffffff", scale: 3, useCORS: true, logging: false,
                });
                const blob = await new Promise((res, rej) =>
                    canvas.toBlob((b) => (b ? res(b) : rej(new Error("toBlob failed"))), "image/png"));

                try {
                    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
                    btn.innerHTML = "✓ Copiado!";
                    setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
                } catch (clipErr) {
                    if (mobile) {
                        // Mobile clipboard is often restricted – fall back to download.
                        console.warn("Clipboard write failed on mobile, falling back to download:", clipErr);
                        triggerDownload(blob);
                        btn.innerHTML = "✓ Descargado!";
                        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
                    } else {
                        // Desktop: surface the error instead of silently downloading.
                        console.error("Clipboard write failed:", clipErr);
                        btn.innerHTML = "Error al copiar";
                        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 3000);
                    }
                }
            } catch (err) {
                // CORS render failed – retry with allowTaint.
                console.warn("html2canvas CORS failed, retrying with allowTaint:", err);
                try {
                    const canvas2 = await html2canvas(card, {
                        backgroundColor: "#ffffff", scale: 3,
                        useCORS: false, allowTaint: true, logging: false,
                    });
                    const blob2 = await new Promise((res, rej) =>
                        canvas2.toBlob((b) => (b ? res(b) : rej(new Error("toBlob failed"))), "image/png"));
                    if (mobile) {
                        // Tainted canvas can't go to clipboard; download instead.
                        triggerDownload(blob2);
                        btn.innerHTML = "✓ Descargado!";
                        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
                    } else {
                        // Desktop: can't copy a tainted canvas – show error.
                        console.error("Cannot copy to clipboard: canvas is tainted by cross-origin image.");
                        btn.innerHTML = "Error al copiar";
                        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 3000);
                    }
                } catch (err2) {
                    console.error("All attempts to generate/export image failed:", err2);
                    btn.innerHTML = "Error :(";
                    setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
                }
            }
        }
    } catch (outerErr) {
        console.error("Unexpected error in exportCardImage:", outerErr);
        btn.innerHTML = "Error :(";
        setTimeout(() => { btn.innerHTML = originalText; btn.disabled = false; }, 2000);
    } finally {
        card.style.width    = prevWidth;
        card.style.maxWidth = prevMaxWidth;
        card.classList.remove("exporting");
        // Remove the fixed widths so the live layout returns to normal
        card.querySelectorAll(".waffle-law-label").forEach(label => {
            label.style.width    = "";
            label.style.minWidth = "";
            label.style.maxWidth = "";
        });
    }
}

// ── Waffle card ─────────────────────────────────────────────────────────────
async function copyWaffleImage()     { await exportCardImage("waffle-card", "btn-copy-image",     "copy"); }
async function downloadWaffleImage() { await exportCardImage("waffle-card", "btn-download-image", "download"); }

// ── Legislator header card ──────────────────────────────────────────────────
async function exportLegHeaderCard(btnId, mode) {
    if (!currentDetail) return;
    const btn      = document.getElementById(btnId);
    const card     = document.getElementById("leg-header-export-card");
    const innerEl  = document.getElementById("leg-header-export-inner");
    const originalText = btn.innerHTML;

    const d = currentDetail;
    const chambers = d.chambers || [d.chamber];
    const chamberLabel = chambers.length > 1
        ? "Dip. + Sen."
        : chambers[0] === "diputados" ? "Diputado/a" : "Senador/a";
    const photoHtml = d.photo
        ? `<img src="${d.photo}" class="aec-photo" alt="" crossorigin="anonymous">`
        : `<div class="aec-photo-placeholder"></div>`;

    const ERA_DEFS_EXP = [
        { label: "1993\u20132014", key: "1993-2014",
          opp: { key: "UCR", label: "UCR / ARI",        cls: "alignment-ucr" } },
        { label: "2015\u20132023", key: "2015-2023",
          opp: { key: "PRO", label: "JxC / PRO / UCR",  cls: "alignment-pro" } },
        { label: "2024\u20132026", key: "2024-2026",
          opp: { key: "LLA", label: "LLA / PRO",         cls: "alignment-lla" } },
    ];
    const eraAl = d.era_alignment || {};
    const alignGridCols = ERA_DEFS_EXP.map((era) => {
        const eraData = eraAl[era.key] || {};
        const pjPct  = eraData["PJ"]  ?? null;
        const oppPct = eraData[era.opp.key] ?? null;
        const fmt    = v => v !== null ? v + "\u00a0%" : "N/A";
        return `<div class="alignment-era-col">
            <div class="alignment-era-label">${era.label}</div>
            <div class="alignment-card alignment-pj">
                <div class="alignment-label">PJ / FdT / UxP</div>
                <div class="alignment-value">${fmt(pjPct)}</div>
            </div>
            <div class="alignment-card ${era.opp.cls}">
                <div class="alignment-label">${era.opp.label}</div>
                <div class="alignment-value">${fmt(oppPct)}</div>
            </div>
        </div>`;
    }).join("");

    // Compute stats for export card
    const expStats = d.yearly_stats || {};
    const expTrailingAus = d.trailing_ausente || 0;
    const expActiveYears = Object.keys(expStats).filter(y => {
        const s = expStats[y];
        return (s.AFIRMATIVO||0)+(s.NEGATIVO||0)+(s.ABSTENCION||0)+(s.AUSENTE||0) >= 5;
    });
    let expTotalV = 0, expTotalPresent = 0;
    for (const y of expActiveYears) {
        const s = expStats[y];
        expTotalV       += (s.total || 0);
        expTotalPresent += (s.AFIRMATIVO||0) + (s.NEGATIVO||0) + (s.ABSTENCION||0);
    }
    const expEffV = expTotalV - expTrailingAus;
    const expPresText   = expEffV > 0 ? Math.round(expTotalPresent / expEffV * 100) + "\u00a0%" : "N/A";
    const expTermsCount = (d.terms || []).length;

    innerEl.innerHTML = `
        <div class="aec-header-inner">
            ${photoHtml}
            <div class="aec-info">
                <div class="aec-name">${escapeHtml(d.name)}</div>
                <div class="aec-meta">${chamberLabel}&ensp;&middot;&ensp;${escapeHtml(shortPartyName(d.bloc))}&ensp;&middot;&ensp;${escapeHtml(d.province)}</div>
                <div class="lhe-stats">
                    <div class="lhe-stat"><span class="lhe-stat-value">${expTermsCount}</span><span class="lhe-stat-label">Mandatos</span></div>
                    <div class="lhe-stat"><span class="lhe-stat-value">${expPresText}</span><span class="lhe-stat-label">Presentismo</span></div>
                </div>
            </div>
        </div>
        <div class="lhe-alignment-title">Alineamiento Político en Votaciones Divididas</div>
        <div class="lhe-alignment-grid alignment-grid-3col">${alignGridCols}</div>`;

    card.style.display = "block";
    void card.offsetHeight;

    await captureAndExport({ card, btn, originalText, filename: "como_voto_alineamiento_coaliciones.png", mode, photoContainer: innerEl });
}
async function copyAlignmentEraImage()     { await exportLegHeaderCard("btn-copy-alignment-era",     "copy"); }
async function downloadAlignmentEraImage() { await exportLegHeaderCard("btn-download-alignment-era", "download"); }

// ── Info card (presentismo + mandatos) ──────────────────────────────────────
async function exportInfoCard(btnId, mode) {
    if (!currentDetail) return;
    const btn       = document.getElementById(btnId);
    const card      = document.getElementById("info-export-card");
    const headerEl  = document.getElementById("info-export-header");
    const contentEl = document.getElementById("info-export-content");
    const originalText = btn.innerHTML;

    populateExportHeader(headerEl, currentDetail);

    // Clone the live stats + terms content into the export card
    const liveStats  = document.querySelector(".leg-info-stats-row");
    const liveTerms  = document.getElementById("leg-terms-list");
    contentEl.innerHTML = "";
    if (liveStats) contentEl.appendChild(liveStats.cloneNode(true));
    if (liveTerms) contentEl.appendChild(liveTerms.cloneNode(true));

    card.style.display = "block";
    void card.offsetHeight;

    await captureAndExport({ card, btn, originalText, filename: "como_voto_mandatos.png", mode, photoContainer: headerEl });
}
async function copyInfoCardImage()     { await exportInfoCard("btn-copy-info-card",     "copy"); }
async function downloadInfoCardImage() { await exportInfoCard("btn-download-info-card", "download"); }



// ── Alignment chart card ────────────────────────────────────────────────────
// We can't simply resize the live chart-card: Chart.js renders onto a canvas
// at a fixed pixel size and html2canvas will capture that raw pixel buffer,
// producing a cut-off image when the wrapper is narrowed. Instead we build a
// dedicated off-screen export card that:
//   1. Embeds the chart via a rendered data-URL image
//   2. Prepends a header with the legislator's photo + name + meta

async function exportAlignmentCard(btnId, mode) {
    if (!chartAlignment || !currentDetail) return;
    const btn  = document.getElementById(btnId);
    const card = document.getElementById("alignment-export-card");
    const headerEl = document.getElementById("alignment-export-header");
    const imgEl    = document.getElementById("alignment-export-img");
    const originalText = btn.innerHTML;

    populateExportHeader(headerEl, currentDetail);

    imgEl.src = renderChartForExport(chartAlignment, {
        legendFontSize: 28, tickFontSize: 24,
        pointRadius: 8, pointHoverRadius: 10,
        legendBoxWidth: 9, legendBoxHeight: 9,
        interactionMode: "none",
    });

    card.style.display = "block";
    void card.offsetHeight;

    await captureAndExport({ card, btn, originalText, filename: "como_voto_alineamiento.png", mode, photoContainer: headerEl });
}

async function copyAlignmentImage()     { await exportAlignmentCard("btn-copy-alignment",     "copy"); }
async function downloadAlignmentImage() { await exportAlignmentCard("btn-download-alignment", "download"); }

async function exportYearlyCard(btnId, mode) {
    if (!chartYearly || !currentDetail) return;
    const btn      = document.getElementById(btnId);
    const card     = document.getElementById("yearly-export-card");
    const headerEl = document.getElementById("yearly-export-header");
    const imgEl    = document.getElementById("yearly-export-img");
    const originalText = btn.innerHTML;

    populateExportHeader(headerEl, currentDetail);

    imgEl.src = renderChartForExport(chartYearly, {
        legendFontSize: 22, tickFontSize: 20,
    });

    card.style.display = "block";
    void card.offsetHeight;

    await captureAndExport({ card, btn, originalText, filename: "como_voto_votaciones.png", mode, photoContainer: headerEl });
}

async function copyYearlyImage()     { await exportYearlyCard("btn-copy-yearly",     "copy"); }
async function downloadYearlyImage() { await exportYearlyCard("btn-download-yearly", "download"); }

/**
 * Build a shareable URL pointing to the current legislator view,
 * optionally including the active waffle year / text filters.
 */
function buildShareUrl() {
    const base = window.location.origin + window.location.pathname;
    const params = new URLSearchParams();
    if (currentLegKey) params.set("leg", currentLegKey);
    const wy = document.getElementById("waffle-year-filter");
    const wyVals = wy ? Array.from(wy.selectedOptions).map(o => o.value).filter(Boolean) : [];
    if (wyVals.length > 0) params.set("wy", wyVals[0]);
    const wq = document.getElementById("waffle-law-filter");
    if (wq && wq.value.trim()) params.set("wq", wq.value.trim());
    const qs = params.toString();
    return qs ? `${base}?${qs}` : base;
}

function shareTwitter() {
    if (!currentDetail) return;
    const name = currentDetail.name;
    const text = `Mirá cómo votó ${name} en el Congreso Argentino 🗳️`;
    const url = encodeURIComponent(buildShareUrl());
    const tweetUrl = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${url}`;
    window.open(tweetUrl, "_blank", "width=600,height=400");
}

// ===========================================================================
//  CHARTS
// ===========================================================================

function fullYearRange(data) {
    const stats = data.yearly_stats || {};
    // Only include years where the legislator cast at least 5 votes
    return Object.keys(stats)
        .map(Number)
        .filter((y) => {
            const s = stats[String(y)];
            return (s.AFIRMATIVO || 0) + (s.NEGATIVO || 0) + (s.ABSTENCION || 0) + (s.AUSENTE || 0) >= 5;
        })
        .sort((a, b) => a - b)
        .map(String);
}

function renderAlignmentChart(data) {
    if (chartAlignment) chartAlignment.destroy();

    const ctx = document.getElementById("chart-alignment").getContext("2d");
    const years = fullYearRange(data);

    if (years.length === 0) {
        ctx.font = "14px Inter";
        ctx.fillStyle = "#6b7280";
        ctx.textAlign = "center";
        ctx.fillText("Sin datos de alineamiento", ctx.canvas.width / 2, ctx.canvas.height / 2);
        return;
    }

    const pjData = years.map((y) => data.yearly_alignment[y]?.PJ ?? null);
    const ucrData = years.map((y) => data.yearly_alignment[y]?.UCR ?? null);
    const proData = years.map((y) => data.yearly_alignment[y]?.PRO ?? null);
    const llaData = years.map((y) => data.yearly_alignment[y]?.LLA ?? null);

    // Centralized point sizing so legend markers match plotted points
    const POINT_RADIUS = 4;
    const POINT_HOVER_RADIUS = 6;
    const DATASET_BORDER_WIDTH = 2.5;
    // Legend box should roughly match the visual point size; keep it small.
    const legendBox = Math.max(6, Math.round(POINT_RADIUS * 1.6));

    chartAlignment = new Chart(ctx, {
        type: "line",
        data: {
            labels: years,
            datasets: [
                {
                    label: "PJ / UxP / FdT",
                    data: pjData,
                    borderColor: "#1e88e5",
                    backgroundColor: "rgba(30, 136, 229, 0.08)",
                    borderWidth: 2.5,
                    pointStyle: 'circle',
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    tension: 0.3,
                    fill: false,
                    spanGaps: true,
                    clip: false,
                },
                    {
                        label: "UCR / ARI",
                        data: ucrData,
                        borderColor: "#ef4444",
                        backgroundColor: "rgba(239,68,68,0.06)",
                        borderWidth: 2.5,
                        pointStyle: 'circle',
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        tension: 0.3,
                        fill: false,
                        spanGaps: true,
                        clip: false,
                    },
                {
                    label: "JxC / PRO / UCR",
                    data: proData,
                    borderColor: "#f9a825",
                    backgroundColor: "rgba(249, 168, 37, 0.08)",
                    borderWidth: 2.5,
                    pointStyle: 'circle',
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    tension: 0.3,
                    fill: false,
                    spanGaps: true,
                    clip: false,
                },
                {
                    label: "LLA / PRO",
                    data: llaData,
                    borderColor: "#7b1fa2",
                    backgroundColor: "rgba(123, 31, 162, 0.08)",
                    borderWidth: 2.5,
                    pointStyle: 'circle',
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    tension: 0.3,
                    fill: false,
                    spanGaps: true,
                    clip: false,
                },
            ],
        },
            options: {
                layout: { padding: { top: 14 } },
            responsive: true,
            maintainAspectRatio: false,
                plugins: {
                legend: {
                    position: "bottom",
                    labels: { usePointStyle: true, padding: 15, boxWidth: 6, boxHeight: 6, font: { size: 12 } },
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y !== null ? ctx.parsed.y + "%" : "N/A"}`,
                    },
                },
            },
                scales: {
                y: {
                    min: 0,
                    max: 100,
                    ticks: {
                        stepSize: 10,
                        callback: (v) => (typeof v === "number" && v % 10 === 0 ? v + "%" : ""),
                        font: { size: 11 },
                    },
                    grid: { color: "rgba(0,0,0,0.05)" },
                },
                x: {
                    ticks: { font: { size: 11 }, autoSkip: false, maxRotation: 45, minRotation: 45 },
                    grid: { display: false },
                },
            },
            interaction: { mode: "index", intersect: false },
        },
    });
}

function renderYearlyChart(data) {
    if (chartYearly) chartYearly.destroy();

    const ctx = document.getElementById("chart-yearly").getContext("2d");
    const years = fullYearRange(data);

    if (years.length === 0) {
        ctx.font = "14px Inter";
        ctx.fillStyle = "#6b7280";
        ctx.textAlign = "center";
        ctx.fillText("Sin datos", ctx.canvas.width / 2, ctx.canvas.height / 2);
        return;
    }

    chartYearly = new Chart(ctx, {
        type: "bar",
        data: {
            labels: years,
            datasets: [
                {
                    label: "Afirmativo",
                    data: years.map((y) => data.yearly_stats[y]?.AFIRMATIVO || 0),
                    backgroundColor: "#22c55e",
                },
                {
                    label: "Negativo",
                    data: years.map((y) => data.yearly_stats[y]?.NEGATIVO || 0),
                    backgroundColor: "#ef4444",
                },
                {
                    label: "Abstención",
                    data: years.map((y) => data.yearly_stats[y]?.ABSTENCION || 0),
                    backgroundColor: "#f59e0b",
                },
                {
                    label: "Ausente",
                    data: years.map((y) => data.yearly_stats[y]?.AUSENTE || 0),
                    backgroundColor: "#94a3b8",
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "bottom",
                    labels: { usePointStyle: true, padding: 15, font: { size: 12 } },
                },
            },
            scales: {
                x: {
                    stacked: true,
                    grid: { display: false },
                    ticks: { font: { size: 11 }, autoSkip: false, maxRotation: 45, minRotation: 45 },
                },
                y: {
                    stacked: true,
                    beginAtZero: true,
                    ticks: { font: { size: 11 } },
                    grid: { color: "rgba(0,0,0,0.05)" },
                },
            },
        },
    });
}

// ===========================================================================
//  VOTES TABLE
// ===========================================================================

function renderVotesTable() {
    if (!currentDetail) return;

    const yearFilter = document.getElementById("votes-year-filter").value;
    const typeFilter = document.getElementById("votes-type-filter").value;
    const lawFilter = document.getElementById("votes-law-filter").value.trim().toLowerCase();

    let votes = currentDetail.votes || [];

    if (yearFilter) {
        votes = votes.filter((v) => String(v.yr) === yearFilter);
    }
    if (typeFilter) {
        votes = votes.filter((v) => v.v === typeFilter);
    }
    if (lawFilter) {
        votes = votes.filter((v) => {
            const searchable = `${v.ln || ""} ${v.t || ""}`.toLowerCase();
            return searchable.includes(lawFilter);
        });
    }

    // Sort by date descending
    votes.sort((a, b) => {
        const da = parseArgDate(a.d);
        const db = parseArgDate(b.d);
        return db - da;
    });

    // Pagination
    const totalPages = Math.max(1, Math.ceil(votes.length / VOTES_PER_PAGE));
    if (currentVotesPage > totalPages) currentVotesPage = totalPages;
    const start = (currentVotesPage - 1) * VOTES_PER_PAGE;
    const pageVotes = votes.slice(start, start + VOTES_PER_PAGE);

    const tbody = document.getElementById("votes-tbody");
    tbody.innerHTML = pageVotes
        .map(
            (v) => {
                // compute source link if available
                let linkHtml = "";
                const href = v.url || (v.ch === "diputados" && v.vid ? `https://votaciones.hcdn.gob.ar/votacion/${v.vid}` : null);
                if (href) {
                    linkHtml = `<a class="vote-link" href="${escapeAttr(href)}" target="_blank" title="Ver votación original">🔗</a>`;
                }
                // determine which opposition coalition applies for this vote's year
                const yr = v.yr || null;
                const oppKey = yr === null ? null : (yr <= 2014 ? 'UCR' : (yr <= 2023 ? 'JxC' : 'LLA'));

                const pjCell = `<span class="vote-chip vote-${v.pj}">${formatVote(v.pj)}</span>`;
                const ucrCell = (oppKey === 'UCR' && v.ucr) ? `<span class="vote-chip vote-${v.ucr}">${formatVote(v.ucr)}</span>` : `<span class="vote-chip vote-na">-</span>`;
                const jxcCell = (oppKey === 'JxC' && v.pro) ? `<span class="vote-chip vote-${v.pro}">${formatVote(v.pro)}</span>` : `<span class="vote-chip vote-na">-</span>`;
                const llaCell = (oppKey === 'LLA' && v.lla) ? `<span class="vote-chip vote-${v.lla}">${formatVote(v.lla)}</span>` : `<span class="vote-chip vote-na">-</span>`;

                return `
        <tr>
            <td style="white-space:nowrap">${escapeHtml(v.d || "")}</td>
            <td>
                <div class="vote-title">${escapeHtml(v.ln || v.t || "")}</div>
                ${v.al ? `<div class="vote-article">${escapeHtml(v.al)}</div>` : ""}
            </td>
            <td class="vote-source-cell">${linkHtml}</td>
            <td><span class="vote-chip vote-${v.v}">${formatVote(v.v)}</span></td>
            <td>${pjCell}</td>
            <td>${ucrCell}</td>
            <td>${jxcCell}</td>
            <td>${llaCell}</td>
        </tr>`;
            }
        )
        .join("");

    renderPagination(totalPages, votes.length);
}

function renderPagination(totalPages, totalItems) {
    const container = document.getElementById("votes-pagination");
    if (totalPages <= 1) {
        container.innerHTML = `<span style="font-size:0.8rem;color:var(--color-text-secondary)">${totalItems} votaciones</span>`;
        return;
    }

    let html = "";

    if (currentVotesPage > 1) {
        html += `<button data-page="${currentVotesPage - 1}">← Ant.</button>`;
    }

    for (let p = 1; p <= totalPages; p++) {
        if (p === 1 || p === totalPages || Math.abs(p - currentVotesPage) <= 2) {
            html += `<button data-page="${p}" class="${p === currentVotesPage ? "active" : ""}">${p}</button>`;
        } else if (Math.abs(p - currentVotesPage) === 3) {
            html += `<span style="padding:0.4rem;color:var(--color-text-secondary)">…</span>`;
        }
    }

    if (currentVotesPage < totalPages) {
        html += `<button data-page="${currentVotesPage + 1}">Sig. →</button>`;
    }

    html += `<span style="font-size:0.75rem;color:var(--color-text-secondary);margin-left:0.5rem">${totalItems} votaciones</span>`;

    container.innerHTML = html;

    container.querySelectorAll("button[data-page]").forEach((btn) => {
        btn.addEventListener("click", () => {
            currentVotesPage = parseInt(btn.dataset.page);
            renderVotesTable();
            document.querySelector(".votes-section").scrollIntoView({ behavior: "smooth" });
        });
    });
}

// ===========================================================================
//  UTILITIES
// ===========================================================================

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function truncate(str, maxLen) {
    if (!str) return "";
    return str.length > maxLen ? str.substring(0, maxLen - 1) + "…" : str;
}

// Shorten long party/bloc names for display (e.g. "Frente de Izquierda..." -> "FIT-U")
function shortPartyName(name) {
    if (!name) return "";
    const n = name.trim();

    const aliases = [
        { re: /frente\s+de\s+izquierda.*unidad/i, short: "FIT-U" },
        { re: /frente\s+de\s+izquierda/i, short: "FIT" },
        { re: /frente\s+de\s+todos/i, short: "FdT" },
    ];

    for (const a of aliases) {
        if (a.re.test(n)) return a.short;
    }

    // If the name is short already, return as-is
    if (n.length <= 18) return n;

    // Build an acronym from significant words
    const stopwords = new Set(["y", "de", "la", "los", "del", "el", "para", "por", "en", "con"]);
    const parts = n.split(/\s+/).filter(Boolean);
    const significant = parts.filter((w) => !stopwords.has(w.toLowerCase()));
    let acronym = significant.slice(0, 3).map((w) => w[0].toUpperCase()).join("");

    // If last word contains 'unidad', append -U (common in FIT-U)
    const last = parts[parts.length - 1].toLowerCase();
    if (last.includes("unidad") && !acronym.endsWith("U")) acronym = acronym + "-U";

    return acronym || n.substring(0, 12).toUpperCase();
}

function debounce(fn, ms) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn.apply(this, args), ms);
    };
}

function formatVote(v) {
    const map = {
        AFIRMATIVO: "✓ Afirm.",
        NEGATIVO: "✗ Neg.",
        ABSTENCION: "○ Abst.",
        AUSENTE: "— Aus.",
        PRESIDENTE: "⚑ Pres.",
        "N/A": "—",
    };
    return map[v] || v || "—";
}

function formatVoteShort(v) {
    const map = {
        AFIRMATIVO: "Afirmativo",
        NEGATIVO: "Negativo",
        ABSTENCION: "Abstención",
        AUSENTE: "Ausente",
        PRESIDENTE: "Presidente",
    };
    return map[v] || v || "";
}

function parseArgDate(dateStr) {
    if (!dateStr) return 0;
    const match = dateStr.match(/(\d{2})\/(\d{2})\/(\d{4})/);
    if (match) {
        return new Date(
            parseInt(match[3]),
            parseInt(match[2]) - 1,
            parseInt(match[1])
        ).getTime();
    }
    return new Date(dateStr).getTime() || 0;
}


// -------------------------------------------------------------------------
// Initialization: load stats and legislators index, wire basic UI events
// -------------------------------------------------------------------------
(async function initApp() {
    try {
        const sresp = await fetch(`${DATA_PATH}/stats.json`);
        if (sresp.ok) {
            const stats = await sresp.json();
            const legsEl = document.getElementById("stat-legislators");
            const votEl = document.getElementById("stat-votaciones");
            const yrsEl = document.getElementById("stat-years");
            const updEl = document.getElementById("stat-updated");

            if (legsEl) legsEl.textContent = stats.total_legislators ?? "-";
            const totalVot = (stats.total_votaciones_diputados || 0) + (stats.total_votaciones_senadores || 0);
            if (votEl) votEl.textContent = totalVot || "-";
            const dipYears = stats.years_diputados || [];
            const senYears = stats.years_senadores || [];
            if (yrsEl) {
                const dipStr = dipYears.length ? `${dipYears[0]}\u2013${dipYears[dipYears.length - 1]}` : "-";
                const senStr = senYears.length ? `${senYears[0]}\u2013${senYears[senYears.length - 1]}` : "-";
                yrsEl.innerHTML = `<small style="font-size:0.72em;line-height:1.5;display:block">Dip.&nbsp;${dipStr}<br>Sen.&nbsp;${senStr}</small>`;
            }
            if (updEl) updEl.textContent = stats.last_updated ? new Date(stats.last_updated).toLocaleString("es-AR", { hour12: false }) : "-";
        } else {
            console.warn("Could not load stats.json", sresp.status);
        }
    } catch (err) {
        console.error("Error loading stats.json:", err);
    }

    try {
        const lresp = await fetch(`${DATA_PATH}/legislators.json`);
        if (lresp.ok) {
            legislatorsData = await lresp.json();
        } else {
            console.warn("Could not load legislators.json", lresp.status);
        }
    } catch (err) {
        console.error("Error loading legislators.json:", err);
    }

    // Load laws detail data for the law search section
    try {
        const lawResp = await fetch(`${DATA_PATH}/laws_detail.json`);
        if (lawResp.ok) {
            lawsData = await lawResp.json();
            // Populate year filter
            const years = [...new Set(lawsData.map((l) => l.y).filter(Boolean))].sort();
            const lawYearFilter = document.getElementById("law-year-filter");
            if (lawYearFilter) {
                lawYearFilter.innerHTML = '<option value="">Todos</option>' +
                    years.map(y => `<option value="${y}">${y}</option>`).join("");
            }
        } else {
            console.warn("Could not load laws_detail.json", lawResp.status);
        }
    } catch (err) {
        console.error("Error loading laws_detail.json:", err);
    }

    // Wire search and basic controls
    const sin = document.getElementById("search-input");
    if (sin) sin.addEventListener("input", debounce(onSearchInput, 250));
    if (sin) sin.addEventListener("focus", () => onSearchInput({ requireQuery: false }));

    // Hide results on Escape or when focus leaves the search box.
    // Use a mousedown guard so clicking a result item isn't swallowed by blur.
    const searchResults = document.getElementById("search-results");
    let searchResultsMousedown = false;
    if (searchResults) {
        searchResults.addEventListener("mousedown", () => { searchResultsMousedown = true; });
        searchResults.addEventListener("mouseup",   () => { searchResultsMousedown = false; });
    }
    if (sin) {
        sin.addEventListener("blur", () => {
            if (!searchResultsMousedown) hideSearchResults();
        });
        sin.addEventListener("keydown", (e) => {
            if (e.key === "Escape") { hideSearchResults(); sin.blur(); }
        });
    }
    const clearBtn = document.getElementById("clear-search");
    if (clearBtn) clearBtn.addEventListener("click", () => { document.getElementById("search-input").value = ""; hideSearchResults(); });
    const chamberSel = document.getElementById("filter-chamber");
    if (chamberSel) chamberSel.addEventListener("change", onSearchInput);
    const coalitionSel = document.getElementById("filter-coalition");
    if (coalitionSel) coalitionSel.addEventListener("change", onSearchInput);

    const backBtn = document.getElementById("back-btn");
    if (backBtn) backBtn.addEventListener("click", showSearchView);

    // Wire law search controls
    const lawSearchInput = document.getElementById("law-search");
    if (lawSearchInput) lawSearchInput.addEventListener("input", debounce(onLawSearchInput, 200));
    if (lawSearchInput) lawSearchInput.addEventListener("focus", () => {
        // On focus, show filtered results (even without text, if filters are set)
        onLawSearchInput();
    });

    // Dismiss law dropdown on Escape / click-outside
    const lawDropdown = document.getElementById("law-search-results");
    let lawDropdownMousedown = false;
    if (lawDropdown) {
        lawDropdown.addEventListener("mousedown", () => { lawDropdownMousedown = true; });
        lawDropdown.addEventListener("mouseup",   () => { lawDropdownMousedown = false; });
    }
    if (lawSearchInput) {
        lawSearchInput.addEventListener("blur", () => {
            if (!lawDropdownMousedown && lawDropdown) lawDropdown.classList.add("hidden");
        });
        lawSearchInput.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && lawDropdown) { lawDropdown.classList.add("hidden"); lawSearchInput.blur(); }
        });
    }
    // Close when clicking anywhere outside the search box or its dropdown
    // (covers the case where dropdown was opened by a filter change, not by focus)
    document.addEventListener("click", (e) => {
        const lawBox = lawSearchInput?.closest(".law-search-wrapper") || lawSearchInput;
        if (!lawBox?.contains(e.target) && !lawDropdown?.contains(e.target)) {
            lawDropdown?.classList.add("hidden");
        }
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && lawDropdown && !lawDropdown.classList.contains("hidden")) {
            lawDropdown.classList.add("hidden");
        }
    });

    const lawYearFilterEl = document.getElementById("law-year-filter");
    if (lawYearFilterEl) lawYearFilterEl.addEventListener("change", onLawSearchInput);
    const lawChamberFilterEl = document.getElementById("law-chamber-filter");
    if (lawChamberFilterEl) lawChamberFilterEl.addEventListener("change", onLawSearchInput);

    // Wire law card share / copy / download buttons
    const btnCopyLaw = document.getElementById("btn-copy-law");
    if (btnCopyLaw) btnCopyLaw.addEventListener("click", () => exportCardImage("law-detail-card", "btn-copy-law", "copy"));
    const btnDownloadLaw = document.getElementById("btn-download-law");
    if (btnDownloadLaw) btnDownloadLaw.addEventListener("click", () => exportCardImage("law-detail-card", "btn-download-law", "download"));
    const btnShareLaw = document.getElementById("btn-share-law-tw");
    if (btnShareLaw) btnShareLaw.addEventListener("click", shareTwitterLaw);

    // Wire waffle filters
    const waffleLawFilter = document.getElementById("waffle-law-filter");
    if (waffleLawFilter) waffleLawFilter.addEventListener("input", debounce(() => { currentWafflePage = 1; renderWaffle(); }, 200));
    const waffleYearFilter = document.getElementById("waffle-year-filter");
    if (waffleYearFilter) waffleYearFilter.addEventListener("change", () => { currentWafflePage = 1; renderWaffle(); });
    _waffleYearWidget = initMultiSelect(waffleYearFilter, "Todos");

    // Wire province filter (was missing)
    const provinceSel = document.getElementById("filter-province");
    if (provinceSel) provinceSel.addEventListener("change", onSearchInput);

    // Wire ranking controls
    function wireRanking(prefix, getSort, setSort, getAsc, setAsc, getPageSize, setPageSize, getPage, setPage, renderFn) {
        const sortEl = document.getElementById(prefix + "-sort");
        const orderEl = document.getElementById(prefix + "-order");
        const chamberEl = document.getElementById(prefix + "-chamber");
        const coalitionEl = document.getElementById(prefix + "-coalition");
        const pagesizeEl = document.getElementById(prefix + "-pagesize");
        function onChange() { setPage(1); renderFn(); }
        if (sortEl) sortEl.addEventListener("change", () => { setSort(sortEl.value); onChange(); });
        if (orderEl) orderEl.addEventListener("change", () => { setAsc(orderEl.value === "asc"); onChange(); });
        if (chamberEl) chamberEl.addEventListener("change", onChange);
        if (coalitionEl) coalitionEl.addEventListener("change", onChange);
        if (pagesizeEl) pagesizeEl.addEventListener("change", () => { setPageSize(parseInt(pagesizeEl.value, 10)); onChange(); });
        const table = document.getElementById(prefix + "-table");
        if (table) table.querySelectorAll(".ranking-sortable").forEach(th => {
            th.addEventListener("click", () => {
                const col = th.dataset.col;
                if (getSort() === col) {
                    setAsc(!getAsc());
                    if (orderEl) orderEl.value = getAsc() ? "asc" : "desc";
                } else {
                    setSort(col);
                    setAsc(false);
                    if (sortEl) sortEl.value = col;
                    if (orderEl) orderEl.value = "desc";
                }
                setPage(1);
                renderFn();
            });
        });
        renderFn();
    }
    wireRanking("rv",
        () => rvSortCol, v => { rvSortCol = v; }, () => rvSortAsc, v => { rvSortAsc = v; },
        () => rvPageSize, v => { rvPageSize = v; }, () => rvPage, v => { rvPage = v; },
        renderRankingVotes);
    wireRanking("ra",
        () => raSortCol, v => { raSortCol = v; }, () => raSortAsc, v => { raSortAsc = v; },
        () => raPageSize, v => { raPageSize = v; }, () => raPage, v => { raPage = v; },
        renderRankingAlignment);

    // Wire ranking export buttons
    document.getElementById("btn-copy-rv")?.addEventListener("click", () => exportRankingTable("rv", "copy"));
    document.getElementById("btn-download-rv")?.addEventListener("click", () => exportRankingTable("rv", "download"));
    document.getElementById("btn-copy-ra")?.addEventListener("click", () => exportRankingTable("ra", "copy"));
    document.getElementById("btn-download-ra")?.addEventListener("click", () => exportRankingTable("ra", "download"));

    // Wire votes table filters (were missing)
    const votesYearFilter = document.getElementById("votes-year-filter");
    if (votesYearFilter) votesYearFilter.addEventListener("change", () => { currentVotesPage = 1; renderVotesTable(); });
    const votesTypeFilter = document.getElementById("votes-type-filter");
    if (votesTypeFilter) votesTypeFilter.addEventListener("change", () => { currentVotesPage = 1; renderVotesTable(); });
    const votesLawFilter = document.getElementById("votes-law-filter");
    if (votesLawFilter) votesLawFilter.addEventListener("input", debounce(() => { currentVotesPage = 1; renderVotesTable(); }, 250));

    // Populate initial small search result if desired (empty/hidden)
    hideSearchResults();

    // Handle browser back/forward navigation
    window.addEventListener("popstate", (e) => {
        const p = new URLSearchParams(window.location.search);
        const key = p.get("leg");
        if (key) {
            loadLegislatorDetail(key, {
                wy: p.get("wy") || "",
                wq: p.get("wq") || "",
            });
        } else {
            showSearchView();
        }
    });

    // Deep-link: if URL contains ?leg=KEY, auto-load that legislator
    const urlParams = new URLSearchParams(window.location.search);
    const legParam = urlParams.get("leg");
    if (legParam) {
        loadLegislatorDetail(legParam, {
            wy: urlParams.get("wy") || "",
            wq: urlParams.get("wq") || "",
        });
    }
    // Wire waffle/legislator detail share + copy buttons

    // Stamp today's date on all export card footers once at load time
    const _exportDateStr = new Date().toISOString().slice(0, 10);
    ["lhe-export-date", "align-export-date", "yearly-export-date", "info-export-date"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.textContent = _exportDateStr;
    });

    // Wire all export card button groups (copy / download / share)
    [
        { copy: "btn-copy-image",          download: "btn-download-image",          share: "btn-share-tw",               copyFn: copyWaffleImage,          downloadFn: downloadWaffleImage },
        { copy: "btn-copy-alignment-era",   download: "btn-download-alignment-era", share: "btn-share-alignment-era-tw", copyFn: copyAlignmentEraImage,    downloadFn: downloadAlignmentEraImage },
        { copy: "btn-copy-info-card",       download: "btn-download-info-card",     share: "btn-share-info-card-tw",     copyFn: copyInfoCardImage,        downloadFn: downloadInfoCardImage },
        { copy: "btn-copy-alignment",       download: "btn-download-alignment",     share: "btn-share-alignment-tw",     copyFn: copyAlignmentImage,       downloadFn: downloadAlignmentImage },
        { copy: "btn-copy-yearly",          download: "btn-download-yearly",        share: "btn-share-yearly-tw",        copyFn: copyYearlyImage,          downloadFn: downloadYearlyImage },
    ].forEach(({ copy, download, share, copyFn, downloadFn }) => {
        const c = document.getElementById(copy);     if (c) c.addEventListener("click", copyFn);
        const d = document.getElementById(download); if (d) d.addEventListener("click", downloadFn);
        const s = document.getElementById(share);    if (s) s.addEventListener("click", shareTwitter);
    });

    // Wire vote popup close handlers
    const popupOverlay = document.getElementById("vote-popup-overlay");
    const popupClose = document.getElementById("vote-popup-close");
    if (popupClose) popupClose.addEventListener("click", hideVotePopup);
    if (popupOverlay) popupOverlay.addEventListener("click", (e) => {
        if (e.target === popupOverlay) hideVotePopup();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") hideVotePopup();
    });
})();

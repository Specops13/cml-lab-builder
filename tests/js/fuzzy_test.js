// Ranking tests + benchmark for cmllab/web/static/fuzzy.js (run by tests/test_library_search.py with node).
//   node tests/js/fuzzy_test.js <library/index.json> [<topics vocabulary json>]   -> prints JSON {failures, bench}
"use strict";
const path = require("path");
const F = require(path.join(__dirname, "../../cmllab/web/static/fuzzy.js"));
const idx = require(path.resolve(process.argv[2]));
if (process.argv[3]) F.library.labels = Object.fromEntries(require(path.resolve(process.argv[3])).map((t) => [t.id, t.label]));
const items = F.library.addCourses(idx.items.map((x) => Object.assign({}, x)));
const recs = items.map(F.library.record);
const ids = (q) => F.search(q, recs).map((r) => items[r.i].id);
const failures = [];
const expect = (cond, msg) => { if (!cond) failures.push(msg); };
const top = (q, id, n = 1) => { const r = ids(q); expect(r.slice(0, n).includes(id), `${JSON.stringify(q)}: ${id} not in top ${n}: ${r.slice(0, 5)}`); };

// Dylan's examples
top("evpn mpls", "19-evpn-mpls");
top("vrf lit", "08-vrf-lite");
top("ospf stb", "ospf-multiarea-stub", 2);
for (const id of ["14-multicast-pim-sm", "15-multicast-bsr-ssm"]) top("mcast", id, 3);
// typos (transposition, missing letter, wrong letter)
top("mutlicast", "14-multicast-pim-sm", 3);
top("redistrbution", "13-redistribution");
top("etherchanel", "02-etherchannel");
top("hsrp", "06-hsrp");
// lab ids, blueprint items, node types / platforms, courses
top("17-mpls", "17-mpls-l3vpn");
top("3.1.b", "02-etherchannel");
top("nexus", "18-evpn-vxlan", 2);
top("nxosv9000", "20-evpn-vxlan-superspine", 2);
top("superspine", "20-evpn-vxlan-superspine");
top("data center", "data-center");
expect(ids("eigrp").length >= 2 && ids("eigrp").every((x) => /eigrp|routing|redistribution/.test(x) || true), "eigrp finds labs");
// topic tags (3.2.0): searchable by label
top("monitoring", "10-ntp-syslog-snmp", 2);
top("troubleshooting ospf", "troubleshoot-ospf-7node", 2);
top("walkthrough data center", "18-evpn-vxlan", 3);
top("gre ipsec", "09-gre-ipsec");
expect(ids("monitoring").includes("11-ipsla-tracking"), "monitoring topic -> 11: " + ids("monitoring").slice(0, 5));
// ANDed words; nonsense finds nothing; case/punctuation-insensitive
expect(ids("xyzzy").length === 0, "xyzzy should match nothing: " + ids("xyzzy"));
expect(ids("evpn xyzzy").length === 0, "every word must match");
expect(JSON.stringify(ids("VRF-Lite")) === JSON.stringify(ids("vrf lite")), "case and punctuation");
expect(ids("").length === 0 && ids("   ").length === 0, "empty query -> no search");
// whole word in the title beats a scattered subsequence
const r = F.search("bgp", recs); expect(items[r[0].i].id === "05-bgp-ebgp-ibgp", "bgp -> 05 first: " + ids("bgp").slice(0, 3));
// highlight marks the matched characters and escapes HTML
const h = F.search("vrf lit", recs)[0].hits;
expect(F.highlight(items[F.search("vrf lit", recs)[0].i].title, h.title).includes("<mark>VRF</mark>"), "highlight VRF: " + F.highlight(items[F.search("vrf lit", recs)[0].i].title, h.title));
expect(F.highlight("a<b>&", [1]) === "a<mark>&lt;</mark>b&gt;&amp;", "escape: " + F.highlight("a<b>&", [1]));
expect(F.editDistance("mutlicast", "multicast", 2) === 1, "transposition = 1 edit");

// benchmark: ~300 items (the library x11 with distinct ids/titles), every prefix of some queries = one keystroke each
const big = [];
for (let k = 0; k < 11; k++) for (const it of items) big.push(Object.assign({}, it, {id: `${it.id}-${k}`, title: `${it.title} ${k ? "variant " + k : ""}`}));
const t0 = process.hrtime.bigint();
const bigRecs = big.map(F.library.record);
const prepMs = Number(process.hrtime.bigint() - t0) / 1e6;
const queries = ["evpn mpls", "vrf lit", "ospf stb", "mcast", "mutlicast pim", "redistrbution", "nexus vxlan", "3.2.b", "monitoring", "data center"];
const typeAll = (rs, sink) => { for (const q of queries) for (let i = 1; i <= q.length; i++) {
  const s = process.hrtime.bigint(); F.search(q.slice(0, i), rs); if (sink) sink.push(Number(process.hrtime.bigint() - s) / 1e6); } };
typeAll(big.map(F.library.record));          // JIT warm-up on a separate copy (its own cache)
const times = [];
typeAll(bigRecs, times);                     // measured: every query typed once, a keystroke at a time
times.sort((a, b) => a - b);
const bench = {items: big.length, keystrokes: times.length, prepare_ms: +prepMs.toFixed(2),
  mean_ms: +(times.reduce((a, b) => a + b, 0) / times.length).toFixed(3), p95_ms: +times[Math.floor(times.length * 0.95)].toFixed(3),
  max_ms: +times[times.length - 1].toFixed(3)};
const examples = {};
for (const q of ["evpn mpls", "vrf lit", "ospf stb", "mcast", "mutlicast", "nexus"]) examples[q] = ids(q).slice(0, 3);
console.log(JSON.stringify({failures, bench, examples}));

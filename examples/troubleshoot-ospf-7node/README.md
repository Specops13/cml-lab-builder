# Troubleshooting: Branch-2 Cannot Reach the Data-Center Server

ENCOR 350-401 blueprint 3.2.b (OSPFv2). Seven IOL routers in a multi-area enterprise design:
EDGE, CORE1 and CORE2 in area 0, DIST1 and DIST2 as ABRs, BR1 in area 1, BR2 in area 2.
Everything is pre-configured. One fault was introduced, and Branch-2 users can't reach the server at 10.100.0.10.

Import: drag this file onto the ENCOR Lab Builder Labs page, or run
`python -m encorlab import troubleshoot-ospf-7node.encorlab`. The lab uses 7 of your 20 nodes.

Grading: live checks cover the broken adjacency, the routes in both directions and the ping, plus guard checks
(no static routes, design unchanged, other adjacencies still FULL). Config checks cover the root-cause fix.
Hints 1-3 are progressive: open them one at a time with *Show hint*.

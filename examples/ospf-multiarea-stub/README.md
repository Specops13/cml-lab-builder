# OSPFv2 Multi-Area: ABR Summarization and a Totally Stubby Area

ENCOR 350-401 blueprint 3.2.b. Four IOL routers (R1-R2-R3-R4). Area 0: R1/R2. Area 1 (totally stubby): R2/R3/R4.
R2 is the ABR and summarizes 172.16.0.0-172.16.3.255 into 172.16.0.0/22.

Import: drag this .encorlab file onto the ENCOR Lab Builder catalog page, or run
`python -m encorlab import ospf-multiarea-stub.encorlab`.

Grading: 8 live checks (adjacencies FULL, summary on R1, only a default route in area 1, ping)
and 9 config checks (router-id, area 0 link, stub/no-summary, range).

# UNOC v3 Roadmap (Source-of-Truth)

## 0) Decision
- `MASTER_SPEC_UNOC_LITE.md` ist als High-Level-Grundgerüst nützlich, aber **nicht mehr ausreichend** als Hauptanforderung.
- Ab jetzt ist diese Roadmap der operative Source-of-Truth für Umsetzung.
- Empfehlung: `MASTER_SPEC_UNOC_LITE.md` zunächst **nicht löschen**, sondern als `ARCHIVE` behandeln, bis alle offenen Themen aus den Fachdokus in Tasks umgesetzt/abgenommen sind.

## 1) Arbeitsregeln

### 1.1 Status
- `OPEN`: noch nicht begonnen
- `IN_PROGRESS`: in Arbeit
- `BLOCKED`: externes Hindernis
- `DONE`: umgesetzt + akzeptiert
- `DEFERRED`: bewusst verschoben

### 1.2 Builder-Update-Format (pro Task)
Jeder erledigte oder blockierte Task bekommt direkt unter `Builder Log` einen kurzen Eintrag:

```md
- Date: YYYY-MM-DD
- Outcome: DONE | BLOCKED | PARTIAL
- Implemented: <kurz was wirklich umgesetzt wurde>
- Issues: <Fehler/Limitierungen oder "none">
- Dependencies/Next: <welcher Task jetzt nötig ist>
```

### 1.3 Definition of Done (global)
- API-Verhalten entspricht Doku + Fehlercodes.
- Socket-Events entsprechen Contract.
- UI ist auf API/Socket statt Mock-State.
- `npm run lint`, `npm test`, `npm run build` grün.
- Task enthält Builder-Log-Eintrag.

## 2) Traceability (keine Informationsverluste)
- `01_overview_and_domain_model.md` -> TASK-001..004, TASK-053..066
- `02_provisioning_model.md` -> TASK-005..008, TASK-067..081
- `03_ipam_and_status.md` -> TASK-009..012, TASK-082..096
- `031_IPAM-Architecture-Future.md` -> TASK-097..103
- `04_links_and_batch.md` -> TASK-013..016, TASK-104..116
- `04_signal_budget_and_overrides.md` -> TASK-017..019, TASK-117..128
- `05_realtime_and_ui_model.md` -> TASK-020..023, TASK-129..140
- `06_future_extensions_and_catalog.md` -> TASK-024..029, TASK-141..152
- `07_container_model_and_ui.md` -> TASK-030..032, TASK-153..162
- `08_ports.md` -> TASK-033..035, TASK-163..168
- `09_cockpit_nodes.md` -> TASK-036..038, TASK-169..174
- `10_interfaces_and_addresses.md` -> TASK-039..041, TASK-175..180
- `11_traffic_engine_and_congestion.md` -> TASK-042..044, TASK-181..186
- `12_testing_and_performance_harness.md` -> TASK-045..048, TASK-187..192
- `13_api_reference.md` -> TASK-049..052, TASK-193..198
- `ARCHITECTURE.md` -> TASK-199..202
- `14_commands_playbook.md` -> TASK-203..206

## 3) Task Backlog

### Foundation & Domain

#### [TASK-001] Domain Canonical Model vereinheitlichen
- Status: OPEN
- Sources: 01
- Ziel: Einheitliche Device/Link/Port/Network-Typen (inkl. OLT, Splitter, ONU, Switch) in Backend, Frontend und DB.
- Scope:
  - Einheitliche DeviceType-Mapping-Regeln (legacy ONT/SPLITTER etc. -> kanonische Typen).
  - DB/DTO/Frontend-Typen synchronisieren.
- Akzeptanz:
  - Keine widersprüchlichen Typbezeichner im Laufzeitpfad.
- Depends on: none
- Builder Log:

#### [TASK-002] Optical Grundattribute modellieren
- Status: OPEN
- Sources: 01
- Ziel: tx_power, sensitivity, insertion_loss, link length/fiber loss konsistent erfassen.
- Scope:
  - Schema-/Payload-Felder für optische Berechnung.
  - Fallback-Defaults dokumentiert.
- Akzeptanz:
  - Optische Berechnung nutzt definierte Attribute statt Hardcode-only.
- Depends on: TASK-001
- Builder Log:

#### [TASK-003] Determinismus-Regeln durchziehen
- Status: OPEN
- Sources: 01, 05
- Ziel: reproduzierbare Reihenfolgen/IDs/Sortierung verhindern UI-Sprünge.
- Scope:
  - deterministische Sortierung für Listen/Topologie.
  - Event-Reihenfolge und Versionsfelder.
- Akzeptanz:
  - gleiche Eingaben erzeugen reproduzierbare Ausgabe.
- Depends on: TASK-001
- Builder Log:

#### [TASK-004] Authoritative Backend-Prinzip absichern
- Status: OPEN
- Sources: 01
- Ziel: Backend als autoritative Quelle für Persistenz + Topologiezustand.
- Scope:
  - keine dauerhafte fachliche Divergenz zwischen Client-Mock und Serverzustand.
- Akzeptanz:
  - Reload zeigt identischen persisted Zustand.
- Depends on: TASK-001
- Builder Log:

#### [TASK-053] Vollständige Device-Taxonomie abbilden
- Status: OPEN
- Sources: 01
- Ziel: Alle in `01` definierten Gerätetypen technisch führen (Backbone Gateway, Core Router, Edge Router, OLT, AON Switch, POP, CORE_SITE, ODF, NVT, Splitter, HOP, ONT, Business ONT, AON CPE).
- Scope:
  - Kanonische Typen in Schema, API-DTO, UI-Mapping und Validierung.
  - Keine stillen Typ-Drops/Umbenennungen ohne Migrationspfad.
- Akzeptanz:
  - Jeder Typ ist erstellbar/lesbar und korrekt klassifiziert.
- Depends on: TASK-001
- Builder Log:

#### [TASK-054] Rollenklassen + Fähigkeitsmatrix erzwingen
- Status: OPEN
- Sources: 01
- Ziel: `active`, `passive_inline`, `passive_container`, `special` inkl. Provisioning/Container/AlwaysOnline/HostsChildren-Flags.
- Scope:
  - Maschinenlesbare Capability-Matrix.
  - Laufzeitvalidierungen auf Matrixbasis.
- Akzeptanz:
  - Regelverstöße werden deterministisch abgewiesen.
- Depends on: TASK-053
- Builder Log:

#### [TASK-055] Container-Beziehungsregeln (01-Level) absichern
- Status: OPEN
- Sources: 01
- Ziel: POP/CORE_SITE als Gruppierungsgrenzen, keine Link-Endpunkte, Parent-Relation für aktive Geräte.
- Scope:
  - API/Service-Regeln für Parent-Assignment und Endpoint-Validierung.
  - Aggregation sink semantics ohne Pfadteilnahme.
- Akzeptanz:
  - Container können nicht als Link-Endpunkte verbunden werden.
- Depends on: TASK-053, TASK-030
- Builder Log:

#### [TASK-056] IPAM-Poolset aus 01 vollständig umsetzen
- Status: OPEN
- Sources: 01, 03
- Ziel: `core_mgmt`, `ont_mgmt`, `aon_mgmt`, `cpe_mgmt`, `olt_mgmt`, `noc_tools` plus `/31` p2p-Track.
- Scope:
  - Deterministische Zuordnung pro Gerätetyp.
  - Idempotente Provisioning-Allokation.
- Akzeptanz:
  - Pools werden gemäß Matrix verwendet, inkl. CPE/NOC.
- Depends on: TASK-009, TASK-053
- Builder Log:

#### [TASK-057] `/31` p2p IPAM für Router-Links ergänzen
- Status: OPEN
- Sources: 01
- Ziel: Router-zu-Router Punkt-zu-Punkt-Adressierung mit /31 Pool.
- Scope:
  - Reservierung, Vergabe, Freigabe, Konfliktprüfung.
  - Routing/Interface-Contract Integration.
- Akzeptanz:
  - Core/Edge Router p2p links erhalten deterministische /31-Adressen.
- Depends on: TASK-056, TASK-039
- Builder Log:

#### [TASK-058] L2/L3 Fallback-Pipeline spezifikationsgetreu
- Status: OPEN
- Sources: 01
- Ziel: Primär graph traversal, fallback forwarding bei fehlendem passable path.
- Scope:
  - Gemeinsame `is_link_passable` Logik.
  - Fallback-Path-Synthese + Observability.
- Akzeptanz:
  - Fehlende Primärpfade führen nicht zu hartem Traffic-Abbruch.
- Depends on: TASK-013, TASK-025
- Builder Log:

#### [TASK-059] Link-Typregeln inkl. logischer Uplink-Varianten
- Status: OPEN
- Sources: 01, 02, 04_links
- Ziel: Zugriffsuplinks im logischen Graph, aber außerhalb optischer Dämpfungsberechnung.
- Scope:
  - Link-Kategorien für optical-vs-logical treatment.
  - Validierung und Engine-Integration.
- Akzeptanz:
  - Optical loss berechnet nur optische Segmente; dependency graph sieht zulässige logische Uplinks.
- Depends on: TASK-013, TASK-018
- Builder Log:

#### [TASK-060] Realtime Outbox/Dispatcher/Heartbeat robust machen
- Status: OPEN
- Sources: 01, 05
- Ziel: Bounded coalescing queue, single dispatcher, heartbeat cleanup.
- Scope:
  - Burst-Schutz und per-device coalescing.
  - Verbindungsbereinigung bei stale peers.
- Akzeptanz:
  - Unter Last kein ungebremstes Queue-Wachstum.
- Depends on: TASK-020
- Builder Log:

#### [TASK-061] Optical-Recompute Hooks bei Mutationen
- Status: OPEN
- Sources: 01
- Ziel: Recompute-Anstoß bei Device/Link/Patch-Änderungen mit betroffenen ONTs.
- Scope:
  - Hook points für relevante Mutationspfade.
  - Delta-Events statt Full Refresh.
- Akzeptanz:
  - Optische Werte aktualisieren gezielt nach Mutationen.
- Depends on: TASK-018, TASK-020
- Builder Log:

#### [TASK-062] Hardware-Auswahl bei Device-Creation
- Status: OPEN
- Sources: 01, 06
- Ziel: Modellauswahl beim Erstellen + sichere Defaults für headless/test.
- Scope:
  - UI selection flow.
  - Backend Übernahme der Modell-Defaults.
- Akzeptanz:
  - Gerät wird mit gewähltem Modell und passenden Default-Interfaces erzeugt.
- Depends on: TASK-024, TASK-021
- Builder Log:

#### [TASK-063] Effective Capacity Dual-Field Contract
- Status: OPEN
- Sources: 01
- Ziel: Beide Kapazitätsfelder im Device-Contract parallel bereitstellen (nested + flattened).
- Scope:
  - API response shaping.
  - Backward/forward compatibility tests.
- Akzeptanz:
  - Beide Felder vorhanden und konsistent.
- Depends on: TASK-049
- Builder Log:

#### [TASK-064] Router Cockpit Capacity Rendering-Regeln
- Status: OPEN
- Sources: 01, 09
- Ziel: `TotCap` Anzeige mit klaren current/max Rundungs-/Einheitenregeln.
- Scope:
  - upstream-basierte Utilization-Konsistenz.
  - optional combined-throughput Darstellung klar getrennt.
- Akzeptanz:
  - Keine widersprüchliche Kapazitätsanzeige im Cockpit.
- Depends on: TASK-063, TASK-037
- Builder Log:

#### [TASK-065] DEGRADED-vs-DOWN Traffic Semantik
- Status: OPEN
- Sources: 01
- Ziel: Verkehrsgenerierung/Aggregation abhängig vom Status exakt gemäß Spezifikation.
- Scope:
  - ONT/Business ONT block in DEGRADED/DOWN.
  - AON CPE Ausnahmepfad.
  - Infrastructure aggregate behavior in DEGRADED.
- Akzeptanz:
  - Traffic-Engine Verhalten entspricht Statussemantik in allen genannten Klassen.
- Depends on: TASK-025, TASK-010
- Builder Log:

#### [TASK-066] Interfaces/Optical Details Panels vollständig anbinden
- Status: OPEN
- Sources: 01, 08, 10
- Ziel: Details Tabs (Overview/Interfaces/Optical) mit Live-Summary + on-demand Interfaces.
- Scope:
  - Polling/Push-Strategie für Port occupancy.
  - Fetch-on-demand Interfaces/addresses.
- Akzeptanz:
  - Tabs zeigen konsistente Live-Daten ohne Hard-Refresh.
- Depends on: TASK-033, TASK-041, TASK-021
- Builder Log:

### Provisioning

#### [TASK-005] Provisioning State Machine umsetzen
- Status: OPEN
- Sources: 02
- Ziel: `Created -> Validated -> Provisioned -> Active/Offline` inkl. Transition-Regeln.
- Scope:
  - Provision/Deprovision-Endpunkte.
  - Statuswechsel mit Validierung.
- Akzeptanz:
  - illegale State-Transitions werden mit 4xx blockiert.
- Depends on: TASK-001, TASK-004
- Builder Log:

#### [TASK-006] Provision Matrix + Dependency Checks
- Status: OPEN
- Sources: 02
- Ziel: Regeln pro Gerätetyp (Provisionable, Required Parent, Upstream Dependency).
- Scope:
  - ONU benötigt gültigen OLT-Pfad.
  - Passive Geräte nicht provisionierbar.
- Akzeptanz:
  - Verstöße liefern definierte Fehlercodes.
- Depends on: TASK-005
- Builder Log:

#### [TASK-007] Provisioning-Fehlercodes normieren
- Status: OPEN
- Sources: 02, 05
- Ziel: `DEVICE_NOT_FOUND`, `INVALID_PARENT`, `ALREADY_PROVISIONED`, `MISSING_DEPENDENCY` etc.
- Scope:
  - einheitlicher Error Payload + HTTP Mapping.
- Akzeptanz:
  - API liefert konsistente Fehlercodes laut Doku.
- Depends on: TASK-005
- Builder Log:

#### [TASK-008] Batch-Provisioning vorbereiten
- Status: OPEN
- Sources: 02
- Ziel: Grundlage für OLT-/ONU-Massenprovisionierung.
- Scope:
  - Transaktions- und Validierungsstrategie definieren/implementieren.
- Akzeptanz:
  - dokumentierter und getesteter Batch-Flow (mind. MVP Stub).
- Depends on: TASK-006
- Builder Log:

#### [TASK-067] Provisioning-Transaktion 6-Phasen-Flow
- Status: OPEN
- Sources: 02
- Ziel: Pre-Validation -> Interface-Realization -> IPAM -> Status-Phase1 -> Optical-Hook -> Delta-Events als definierter Flow.
- Scope:
  - Klare Trennung transaktionaler und post-commit Schritte.
  - Deterministische Reihenfolge.
- Akzeptanz:
  - Provisioning folgt exakt dokumentierter Ausführungssequenz.
- Depends on: TASK-005
- Builder Log:

#### [TASK-068] Parent/Container-Regeln pro Gerätetyp (strict)
- Status: OPEN
- Sources: 02
- Ziel: OLT/AON parent optional aber nur POP; Router ohne Parent; Endpoint-parent-Regeln durchsetzen.
- Scope:
  - Typ-spezifische Parent-Policy.
  - 422/400 Fehlerpfade.
- Akzeptanz:
  - Ungültige Parent-Konfigurationen werden korrekt abgewiesen.
- Depends on: TASK-006, TASK-030
- Builder Log:

#### [TASK-069] Interface-Realization bei Provisioning
- Status: OPEN
- Sources: 02
- Ziel: Management-Interface Erzeugung mit Uniqueness-Garantien.
- Scope:
  - Duplicate-Schutz (`DUPLICATE_MGMT_INTERFACE`).
  - p2p-Uplink Realization als separater späterer Flow.
- Akzeptanz:
  - Pro provisioniertem Device genau eine gültige Mgmt-Schnittstelle.
- Depends on: TASK-005, TASK-039
- Builder Log:

#### [TASK-070] Concurrency Guard für Provisioning-Races
- Status: OPEN
- Sources: 02
- Ziel: Parallele Provisioning-Versuche führen zu genau einem Erfolg.
- Scope:
  - optimistic/pessimistic guard Strategie.
  - eindeutiger Konflikt-Response.
- Akzeptanz:
  - Race-Test zeigt single-winner Verhalten.
- Depends on: TASK-067
- Builder Log:

#### [TASK-071] Async Post-Commit Recompute Pipeline
- Status: OPEN
- Sources: 02
- Ziel: Status/Optical recompute nach Commit mit nachvollziehbarer Latenzsemantik.
- Scope:
  - post-commit job hooks.
  - eventual-consistency Hinweis im API-Vertrag.
- Akzeptanz:
  - Provisioned-Flag kann vor Finalstatus erscheinen, aber deterministisch nachziehen.
- Depends on: TASK-067, TASK-061
- Builder Log:

#### [TASK-072] Provisioning Error-Code Contract (vollständig)
- Status: OPEN
- Sources: 02
- Ziel: Mapping für `INVALID_PROVISION_PATH`, `ALREADY_PROVISIONED`, `POOL_EXHAUSTED`, `DUPLICATE_MGMT_INTERFACE`, `CONTAINER_REQUIRED`.
- Scope:
  - HTTP-Status und Error-Payload standardisieren.
  - Negative Tests pro Code.
- Akzeptanz:
  - Jeder definierte Fehlercode reproduzierbar testbar.
- Depends on: TASK-007, TASK-045
- Builder Log:

#### [TASK-073] Dry-Run Provision Endpoint
- Status: OPEN
- Sources: 02
- Ziel: `?dry_run=1` liefert geplante Operationen ohne Mutation.
- Scope:
  - prospective dependency/ip/interface preview.
  - no-write guarantee.
- Akzeptanz:
  - Dry-Run erzeugt identisches Ergebnisprofil wie echte Provision ohne DB-Änderung.
- Depends on: TASK-067
- Builder Log:

#### [TASK-074] Provision Matrix API für UI-Hints
- Status: OPEN
- Sources: 02
- Ziel: `GET /api/provision/matrix` als maschinenlesbarer Regel-Contract.
- Scope:
  - Device-type rules, parent constraints, dependency hints.
  - kompatibel mit UI Creation/Validation hints.
- Akzeptanz:
  - Frontend kann Provisioning-Hinweise vollständig aus Endpoint beziehen.
- Depends on: TASK-006
- Builder Log:

#### [TASK-075] Batch-Provision mit Dependency-Ordering
- Status: OPEN
- Sources: 02
- Ziel: Mehrere Devices in geordneter Sequenz provisionieren (topological ordering).
- Scope:
  - dependency sort.
  - partial-failure Strategie (all-or-nothing oder report-mode).
- Akzeptanz:
  - Batch-Provisioning dokumentiert und testbar mit Abhängigkeitsketten.
- Depends on: TASK-008, TASK-067
- Builder Log:

#### [TASK-076] Deprovision-Policy (MVP-deferred zu implementierbar)
- Status: OPEN
- Sources: 02
- Ziel: deprovision semantics inkl. optional IP reclamation und Folge-Recompute.
- Scope:
  - state rollback rules.
  - reclamation policy toggle.
- Akzeptanz:
  - Deprovision verlässlich und ohne orphaned state.
- Depends on: TASK-005, TASK-009
- Builder Log:

#### [TASK-077] Link Rules L1-L9 als Runtime-Validator
- Status: OPEN
- Sources: 02
- Ziel: Detaillierte L1..L9 Endpoint-Regeln inkl. L6A/L6B maschinenlesbar validieren.
- Scope:
  - Rule table in code/constants.
  - reject/allow behavior + error paths.
- Akzeptanz:
  - Jede L-Regel hat mind. einen positiven/negativen Test.
- Depends on: TASK-013, TASK-059
- Builder Log:

#### [TASK-078] Container-Endpoint-Invariant technisch erzwingen
- Status: OPEN
- Sources: 02
- Ziel: POP/CORE_SITE nie als Link-Endpunkte zulassen.
- Scope:
  - validator + tests + error contract.
- Akzeptanz:
  - Container-endpoint link attempts liefern deterministischen Fehler.
- Depends on: TASK-055, TASK-077
- Builder Log:

#### [TASK-079] Provisioning Observability (Logs + Metrics)
- Status: OPEN
- Sources: 02
- Ziel: `provision.start/success/failure` strukturierte Logs + Counters.
- Scope:
  - success/failure counters by type/reason.
  - optional duration metric.
- Akzeptanz:
  - Provisioning-Fluss ist in Logs/Metriken nachvollziehbar.
- Depends on: TASK-067
- Builder Log:

#### [TASK-080] Runtime-Flags Governance für Provisioning-Kontext
- Status: OPEN
- Sources: 02
- Ziel: dokumentierte Flag-Werte und Effektgrenzen (strict-only etc.) im Codepfad verankern.
- Scope:
  - removed/planned flags korrekt behandelt.
  - dev/prod behavior eindeutig.
- Akzeptanz:
  - keine impliziten, undokumentierten Feature-Flags im Provisioning-Verhalten.
- Depends on: TASK-003
- Builder Log:

#### [TASK-081] Provisioning Testmatrix erweitern
- Status: OPEN
- Sources: 02
- Ziel: Unit+Integration+Race+Performance-Mindestmatrix aus Doku als verpflichtende Tests.
- Scope:
  - dependency table tests.
  - strict sequence tests.
  - concurrency winner test.
- Akzeptanz:
  - alle in 02 geforderten Mindesttests automatisiert vorhanden.
- Depends on: TASK-045, TASK-070
- Builder Log:

### IPAM & Status

#### [TASK-009] Lazy IPAM implementieren
- Status: OPEN
- Sources: 03
- Ziel: Next-Available-IP pro Pool bei Provisionierung.
- Scope:
  - Pool-Mapping nach Gerätetyp.
  - Nebenläufigkeitsschutz.
- Akzeptanz:
  - keine Doppelvergabe bei parallelen Requests.
- Depends on: TASK-005
- Builder Log:

#### [TASK-010] Statusmodell erweitern
- Status: OPEN
- Sources: 03
- Ziel: `DRAFT`, `PROVISIONED`, `ONLINE`, `OFFLINE`, `ERROR` fachlich nutzbar machen.
- Scope:
  - Statusfeld + API-Antworten + UI-Darstellung.
- Akzeptanz:
  - Statuswerte und Übergänge sind konsistent.
- Depends on: TASK-005
- Builder Log:

#### [TASK-011] Downstream-Statuspropagation
- Status: OPEN
- Sources: 03
- Ziel: Upstream-Ausfall propagiert auf abhängige Geräte.
- Scope:
  - BFS/DFS über Topologie.
  - Recovery-Pfad bei Wiederherstellung.
- Akzeptanz:
  - Statuskaskade wird korrekt emittiert und angezeigt.
- Depends on: TASK-010, TASK-020
- Builder Log:

#### [TASK-012] Status/IPAM Endpoints ergänzen
- Status: OPEN
- Sources: 03, 13
- Ziel: `/api/ipam/pools`, `/api/devices/:id/status`, manuelle Status-API.
- Akzeptanz:
  - Endpoints vorhanden, validiert und getestet.
- Depends on: TASK-009, TASK-010
- Builder Log:

#### [TASK-082] IPAM Pool Contract vervollständigen
- Status: OPEN
- Sources: 03
- Ziel: Vollständige Poolmenge (`core/olt/aon/ont/cpe/noc/p2p`) als stabiler Contract inkl. Status pro Pool.
- Scope:
  - role->pool mapping zentralisieren.
  - dokumentierte CIDR-Strategie je Umgebung.
- Akzeptanz:
  - Pool-Contract ist in API/Code/Doku konsistent.
- Depends on: TASK-009, TASK-056
- Builder Log:

#### [TASK-083] VRF-basierte IP Uniqueness-Regeln
- Status: OPEN
- Sources: 03
- Ziel: `(prefix_id, ip)` und `(vrf_id, ip)` constraints fachlich und technisch absichern.
- Scope:
  - migrations/constraints/indexes.
  - negative tests zu VRF-prefix collision cases.
- Akzeptanz:
  - Keine unzulässigen Doppelbelegungen innerhalb Prefix/VRF.
- Depends on: TASK-009
- Builder Log:

#### [TASK-084] Management Interface Naming/Uniqueness Standard
- Status: OPEN
- Sources: 03
- Ziel: `mgmt0` als deterministischer Standard, exakt eine mgmt-Schnittstelle je provisioniertes aktives Device.
- Scope:
  - interface creation conventions.
  - duplicate prevention.
- Akzeptanz:
  - Keine Mehrfach-mgmt-Interfaces in validen Flows.
- Depends on: TASK-069
- Builder Log:

#### [TASK-085] /31 P2P Addressing Semantik
- Status: OPEN
- Sources: 03
- Ziel: Pairing-Regeln für p2p_uplink und lexikografische lower-ip Vergabe.
- Scope:
  - pair lifecycle bei link create/delete.
  - deterministic assignment function.
- Akzeptanz:
  - gleiche Endpoint-Reihenfolge ergibt immer gleiche /31-Zuordnung.
- Depends on: TASK-057
- Builder Log:

#### [TASK-086] Pool Exhaustion & Recovery Verhalten
- Status: OPEN
- Sources: 03
- Ziel: `POOL_EXHAUSTED` plus klare Recovery-Strategie (ops-visible).
- Scope:
  - error payload detail.
  - utilization telemetry hooks.
- Akzeptanz:
  - Exhaustion ist reproduzierbar, diagnostizierbar und testabgedeckt.
- Depends on: TASK-072, TASK-079
- Builder Log:

#### [TASK-087] Status Semantics pro Device-Klasse
- Status: OPEN
- Sources: 03
- Ziel: strikte effektive Statusregeln je Klasse (always_online, router, olt/aon, leaf, passive).
- Scope:
  - evaluator policy table.
  - no false-positive UP states for strict classes.
- Akzeptanz:
  - Klassenregeln sind deterministisch und testbar.
- Depends on: TASK-010, TASK-053
- Builder Log:

#### [TASK-088] Shared Passability Predicate erzwingen
- Status: OPEN
- Sources: 03
- Ziel: ein gemeinsames `is_link_passable` für dependency/status/traffic.
- Scope:
  - central predicate module.
  - remove divergent local checks.
- Akzeptanz:
  - gleiche Linkzustände führen in allen Engines zu gleichem Traversalverhalten.
- Depends on: TASK-013, TASK-087
- Builder Log:

#### [TASK-089] Traffic Gating nach Upstream-Viability
- Status: OPEN
- Sources: 03
- Ziel: leaf traffic suppression bei fehlender upstream viability.
- Scope:
  - gate conditions in traffic engine.
  - diagnostics-backed gating reason.
- Akzeptanz:
  - Keine fiktiven Flüsse bei broken upstream.
- Depends on: TASK-025, TASK-088
- Builder Log:

#### [TASK-090] Diagnostics Contract (`upstream_l3_ok`, chain, reason_codes)
- Status: OPEN
- Sources: 03
- Ziel: stabiler Diagnostik-Contract für Backend und UI.
- Scope:
  - reason code vocabulary.
  - serialization and API exposure.
- Akzeptanz:
  - Diagnosefelder konsistent über relevante Endpoints/Events verfügbar.
- Depends on: TASK-087, TASK-012
- Builder Log:

#### [TASK-091] Event Ordering & Coalescing Semantik
- Status: OPEN
- Sources: 03, 05
- Ziel: Reihenfolge optical/link -> signal -> status, Override-Events immediate.
- Scope:
  - coalescing window config.
  - order guarantees under burst.
- Akzeptanz:
  - Event-Reihenfolge ist deterministisch und contract-getestet.
- Depends on: TASK-020, TASK-060
- Builder Log:

#### [TASK-092] Hybrid Accelerator Track (optional) spezifizieren
- Status: OPEN
- Sources: 03
- Ziel: Optionaler externer Propagation-Accelerator mit Fallback-Garantien.
- Scope:
  - source tagging (`native`/`accelerator`).
  - parity tests and rollback strategy.
- Akzeptanz:
  - Optionaler Accelerator ohne Semantik-Drift betreibbar.
- Depends on: TASK-087, TASK-046
- Builder Log:

#### [TASK-093] Status/IPAM Observability Baseline
- Status: OPEN
- Sources: 03
- Ziel: Strukturierte Logs + Kernmetriken für status/ipam Pfade.
- Scope:
  - duration/failure/affected counters.
  - pool utilization metrics by pool key.
- Akzeptanz:
  - Operations kann Ursachen und Engpässe ohne Code-Debugging erkennen.
- Depends on: TASK-079
- Builder Log:

#### [TASK-094] IPAM Concurrency Testpaket
- Status: OPEN
- Sources: 03
- Ziel: Race-sichere Allokation unter Parallelität automatisiert absichern.
- Scope:
  - parallel provisioning stress tests.
  - deterministic allocation assertions.
- Akzeptanz:
  - keine Doppelvergabe in Paralleltests.
- Depends on: TASK-070, TASK-083
- Builder Log:

#### [TASK-095] Status Evaluator Regression Suite
- Status: OPEN
- Sources: 03
- Ziel: Policy-Tests für alle Klassen + Override + passability alignment.
- Scope:
  - table-driven evaluator tests.
  - reason-code stability checks.
- Akzeptanz:
  - Statusregeln regressionssicher über Releases.
- Depends on: TASK-087, TASK-090
- Builder Log:

#### [TASK-096] Realtime Contract Tests für Status/Signal
- Status: OPEN
- Sources: 03, 13
- Ziel: Event payload/order/coalescing für status/signal Updates automatisiert prüfen.
- Scope:
  - websocket test harness.
  - ordering assertions.
- Akzeptanz:
  - Contract-Brüche schlagen CI fehl.
- Depends on: TASK-091, TASK-046
- Builder Log:

#### [TASK-097] Future IPAM Approach A (Multi-Region Static) vorbereiten
- Status: OPEN
- Sources: 031
- Ziel: Region-dimension für Prefix/Device mit fallback-kompatibler Suche.
- Scope:
  - schema extension plan.
  - region-aware prefix selection algorithm.
- Akzeptanz:
  - klarer, migrationssicherer Plan für region-aware provisioning.
- Depends on: TASK-082
- Builder Log:

#### [TASK-098] Future IPAM Approach B (Hierarchical) blueprint
- Status: OPEN
- Sources: 031
- Ziel: Region->Site->POP Prefix-Selection und hierarchy-aware allocation konzeptionieren.
- Scope:
  - location model draft.
  - prefix inheritance / nearest-specific strategy.
- Akzeptanz:
  - umsetzbarer Architekturentwurf mit Risiken und Migration.
- Depends on: TASK-097
- Builder Log:

#### [TASK-099] Future IPAM Approach C (Auto-Expansion) guardrails
- Status: OPEN
- Sources: 031
- Ziel: Supernet-carving mit utilization threshold plus race-safe guardrails.
- Scope:
  - expansion trigger strategy.
  - anti-fragmentation constraints.
- Akzeptanz:
  - auto-expand design mit klaren safety checks vorhanden.
- Depends on: TASK-082
- Builder Log:

#### [TASK-100] IPAM Evolution Comparison + Decision Gate
- Status: OPEN
- Sources: 031
- Ziel: A/B/C anhand Komplexität, Skalierung, Migrationsrisiko und Ops-Overhead verbindlich bewerten.
- Scope:
  - decision matrix in engineering governance.
  - trigger criteria for switching approach.
- Akzeptanz:
  - dokumentierte Architekturentscheidung mit Revisionspfad.
- Depends on: TASK-097, TASK-098, TASK-099
- Builder Log:

#### [TASK-101] Multi-Region Migration Plan (No-Downtime) konkretisieren
- Status: OPEN
- Sources: 031
- Ziel: schrittweiser Rollout (schema, backfill, seed, provisioning update, validation).
- Scope:
  - rollout checklist and rollback plan.
  - compatibility with legacy null-region records.
- Akzeptanz:
  - operativ ausführbarer Migrationsplan vorhanden.
- Depends on: TASK-097, TASK-100
- Builder Log:

#### [TASK-102] Prefix Utilization Monitoring & Alerts
- Status: OPEN
- Sources: 031
- Ziel: utilization-based monitoring per pool/region/location.
- Scope:
  - telemetry dimensions.
  - threshold alert definitions.
- Akzeptanz:
  - vor Exhaustion existieren verlässliche Frühwarnungen.
- Depends on: TASK-093, TASK-097
- Builder Log:

#### [TASK-103] External IPAM Sync Evaluation (NetBox-Track)
- Status: OPEN
- Sources: 031
- Ziel: Schnittstelle zu externen IPAM-Systemen evaluieren (optional future integration).
- Scope:
  - sync model (source of truth, conflict resolution).
  - security and operational impact assessment.
- Akzeptanz:
  - fundierte Entscheidungsgrundlage für/gegen externe IPAM-Integration.
- Depends on: TASK-100
- Builder Log:

### Links & Batch

#### [TASK-013] Link Rules erzwingen
- Status: OPEN
- Sources: 02, 04_links
- Ziel: no self-loop, Port-Unicity, Typkompatibilität, optionale Zyklusregeln.
- Akzeptanz:
  - ungültige Links werden zuverlässig abgewiesen.
- Depends on: TASK-001
- Builder Log:

#### [TASK-014] Link CRUD vollständig
- Status: OPEN
- Sources: 04_links, 13
- Ziel: `GET/POST/PATCH/DELETE /api/links` inkl. Attribut-Updates (distance/fiber/meta).
- Akzeptanz:
  - alle CRUD-Pfade inkl. 4xx/404 sauber.
- Depends on: TASK-013
- Builder Log:

#### [TASK-015] Batch Link Create (atomic)
- Status: OPEN
- Sources: 04_links
- Ziel: `POST /api/links/batch` transaktional.
- Akzeptanz:
  - bei Einzelfehler Rollback der gesamten Batch.
- Depends on: TASK-013
- Builder Log:

#### [TASK-016] Batch Link Delete
- Status: OPEN
- Sources: 04_links
- Ziel: `POST /api/links/batch/delete`.
- Akzeptanz:
  - deterministische Löschantwort + Events.
- Depends on: TASK-014
- Builder Log:

#### [TASK-104] Link Domain Contract stabilisieren
- Status: OPEN
- Sources: 04_links
- Ziel: Vollständiges Feldmodell (`status`, `effective_status`, `admin_override_status`, `link_type`, `metadata`) über API/DB/UI konsistent machen.
- Scope:
  - contract schema alignment.
  - deterministic serialization.
- Akzeptanz:
  - Link payloads sind über alle Endpoints konsistent.
- Depends on: TASK-014
- Builder Log:

#### [TASK-105] Interface-Kompatibilitätsvalidator
- Status: OPEN
- Sources: 04_links
- Ziel: Self-link, uniqueness, role compatibility, device compatibility technisch erzwingen.
- Scope:
  - zentraler validator für single + batch.
  - standardisierte Fehlercodes.
- Akzeptanz:
  - alle Regelverstöße liefern konsistente 4xx Fehler.
- Depends on: TASK-013
- Builder Log:

#### [TASK-106] Container Endpoint Hard-Block im Link-Flow
- Status: OPEN
- Sources: 04_links
- Ziel: `POP/CORE_SITE` als Link-Endpunkte konsequent verhindern.
- Scope:
  - validation path for create/update/batch.
  - explicit error contract.
- Akzeptanz:
  - Container-endpoint links sind unmöglich in allen APIs.
- Depends on: TASK-078
- Builder Log:

#### [TASK-107] Link Override API + Async Propagation
- Status: OPEN
- Sources: 04_links
- Ziel: `/api/links/:id/override` inkl. nicht-blockierender Propagation.
- Scope:
  - async job envelope.
  - event correlation id support.
- Akzeptanz:
  - Override-Änderungen werden zuverlässig propagiert ohne UI-Blockierung.
- Depends on: TASK-019, TASK-020
- Builder Log:

#### [TASK-108] Effective Link Status Engine
- Status: OPEN
- Sources: 04_links, 03
- Ziel: precedence `admin > endpoint down/degraded > computed up`.
- Scope:
  - endpoint-state integration.
  - optical relevance integration for fiber paths.
- Akzeptanz:
  - `effective_status` folgt deterministisch der Prioritätslogik.
- Depends on: TASK-017, TASK-088
- Builder Log:

#### [TASK-109] Batch Create Partial-Failure Contract
- Status: OPEN
- Sources: 04_links
- Ziel: `created_link_ids`, `failed_links[]`, counters, `duration_ms`, `request_id`, `backend`.
- Scope:
  - stable response shape.
  - index-based failure mapping.
- Akzeptanz:
  - Client kann Teilfehler ohne Ambiguität verarbeiten.
- Depends on: TASK-015
- Builder Log:

#### [TASK-110] Batch Delete Partial-Failure Contract
- Status: OPEN
- Sources: 04_links
- Ziel: deterministische Rückgabe für gelöschte/nicht gefundene Links im Batch.
- Scope:
  - `deleted_link_ids` + failure details.
  - response counters and backend source.
- Akzeptanz:
  - Batch delete liefert reproduzierbare und vollständige Ergebnisdaten.
- Depends on: TASK-016
- Builder Log:

#### [TASK-111] Dry-Run No-Write Guarantee (Batch)
- Status: OPEN
- Sources: 04_links
- Ziel: `dry_run=true` validiert vollständig ohne Persistenzänderung.
- Scope:
  - transaction guard / no-commit path.
  - tests for no side effects.
- Akzeptanz:
  - DB bleibt unverändert bei Dry-Run, Ergebnisreport vollständig.
- Depends on: TASK-109
- Builder Log:

#### [TASK-112] Batch Health and Backend Capability Endpoint
- Status: OPEN
- Sources: 04_links
- Ziel: `/api/batch/health` mit `status/backend/available/version`.
- Scope:
  - health contract for native/accelerator/fallback.
  - operational visibility for batch path.
- Akzeptanz:
  - health endpoint spiegelt echte batch processing capability.
- Depends on: TASK-109
- Builder Log:

#### [TASK-113] Optional Accelerator/Fallback Parity für Batch
- Status: OPEN
- Sources: 04_links
- Ziel: optionaler externer Batch-Service ohne Semantikdrift ggü. native path.
- Scope:
  - parity tests across backends.
  - response field `backend` governance.
- Akzeptanz:
  - gleiche Inputs erzeugen gleiche fachliche Outcomes unabhängig vom Backend.
- Depends on: TASK-092, TASK-109, TASK-110
- Builder Log:

#### [TASK-114] Link Event Envelope Standardisieren
- Status: OPEN
- Sources: 04_links, 05, 13
- Ziel: `link.created/deleted/updated/status_changed` + `batch.completed` mit correlation/timestamp.
- Scope:
  - event schema and ordering policy.
  - single and batch operation event consistency.
- Akzeptanz:
  - Eventverträge sind stabil und testbar.
- Depends on: TASK-020, TASK-096
- Builder Log:

#### [TASK-115] Link Batch Performance SLOs
- Status: OPEN
- Sources: 04_links
- Ziel: messbare Latenz-/Durchsatzziele für single vs batch link operations.
- Scope:
  - benchmark scenarios (small/medium/large batches).
  - alert thresholds for regression.
- Akzeptanz:
  - Performance-Regressionen werden automatisch erkannt.
- Depends on: TASK-047, TASK-109
- Builder Log:

#### [TASK-116] `/api` vs `/api/v1` Kompatibilitätsstrategie
- Status: OPEN
- Sources: 04_links
- Ziel: eindeutiger Canonical-Path (`/api`) + optionale Aliaspolitik für Legacy-Routen.
- Scope:
  - route compatibility matrix.
  - deprecation messaging and tests.
- Akzeptanz:
  - keine widersprüchlichen Contracts zwischen v1 und canonical paths.
- Depends on: TASK-049
- Builder Log:

### Optical Budget & Overrides

#### [TASK-017] Status-Precedence implementieren
- Status: OPEN
- Sources: 04_signal
- Ziel: `adminOverride > upstream failure > optical signal > operational`.
- Akzeptanz:
  - precedence wird im Backend nachvollziehbar angewendet.
- Depends on: TASK-010, TASK-011
- Builder Log:

#### [TASK-018] Optical Budget Engine erweitern
- Status: OPEN
- Sources: 01, 03, 04_signal
- Ziel: Rx = Tx - Sum(Losses), inkl. Splitter/Fiber/Connector.
- Akzeptanz:
  - nachvollziehbare Berechnungswerte pro ONU.
- Depends on: TASK-002
- Builder Log:

#### [TASK-019] Admin Overrides für Device/Link
- Status: OPEN
- Sources: 04_signal
- Ziel: PATCH Override für Geräte/Links + sichtbare Wirkung.
- Akzeptanz:
  - Override überschreibt normale Berechnung bis Rücknahme.
- Depends on: TASK-017
- Builder Log:

#### [TASK-117] Zentralen Status-Service als einzige Wahrheit erzwingen
- Status: OPEN
- Sources: 04_signal
- Ziel: Effektiver Gerätestatus wird ausschließlich im zentralen Status-Service berechnet, ohne parallele Nebenlogik.
- Scope:
  - one-path evaluation in backend services.
  - ONT-Regel `signal_status=NO_SIGNAL -> DOWN` verbindlich integrieren.
- Akzeptanz:
  - keine divergierenden Statuswerte zwischen Endpoints/Events.
- Depends on: TASK-017, TASK-087
- Builder Log:

#### [TASK-118] Deterministische OLT-Path-Resolution (Dijkstra + Tie-Break)
- Status: OPEN
- Sources: 04_signal
- Ziel: Pro ONT genau ein stabiler Upstream-OLT-Pfad über Dijkstra mit deterministischen Tie-Breakern.
- Scope:
  - weight = `length_km * attenuation_db_per_km`.
  - tie-break chain inkl. `path_signature`.
- Akzeptanz:
  - gleiche Topologie erzeugt reproduzierbar denselben ONT-Pfad.
- Depends on: TASK-018, TASK-003
- Builder Log:

#### [TASK-119] Optical Loss Komponenten vollständig berechnen
- Status: OPEN
- Sources: 04_signal
- Ziel: Gesamtattenuation aus Linkverlusten + passiven insertion losses korrekt summieren.
- Scope:
  - splitter loss via insertion loss field.
  - receive power + margin aus Tx/Attenuation/Sensitivity.
- Akzeptanz:
  - Rx/Margin sind nachvollziehbar und konsistent pro ONT.
- Depends on: TASK-118
- Builder Log:

#### [TASK-120] Signal-Klassifikation + Schwellenwerte standardisieren
- Status: OPEN
- Sources: 04_signal
- Ziel: `OK/WARNING/CRITICAL/NO_SIGNAL` exakt nach Marginschwellen bewerten.
- Scope:
  - boundary-safe comparisons.
  - unresolved path => `NO_SIGNAL`.
- Akzeptanz:
  - Schwellenübergänge sind deterministisch und testbar.
- Depends on: TASK-119
- Builder Log:

#### [TASK-121] Signal/Event Emission Gating umsetzen
- Status: OPEN
- Sources: 04_signal, 05
- Ziel: `deviceSignalUpdated` nur bei Statuswechsel, Grenzwertwechsel oder `>=0.1 dB` Delta; danach ggf. `deviceStatusUpdated`.
- Scope:
  - coalesced emission window.
  - strict ordering signal before status.
- Akzeptanz:
  - Eventflut wird reduziert ohne fachliche Informationsverluste.
- Depends on: TASK-120, TASK-091
- Builder Log:

#### [TASK-122] Optical Recompute Trigger-Matrix implementieren
- Status: OPEN
- Sources: 04_signal, 04_links
- Ziel: Recompute bei allen relevanten Mutationen (Link create/delete/update, Medium, insertion loss, OLT Tx, ONT sensitivity, Provisioning).
- Scope:
  - trigger hooks in mutation paths.
  - correlation metadata für Folgeevents.
- Akzeptanz:
  - relevante Änderungen aktualisieren Signalwerte ohne manuelle Rebuilds.
- Depends on: TASK-061, TASK-119
- Builder Log:

#### [TASK-123] Cache-Invalidierung im Optical Resolver robust machen
- Status: OPEN
- Sources: 04_signal
- Ziel: Topologie-/Optical-Caches werden bei relevanten Änderungen sicher invalidiert (MVP global).
- Scope:
  - shared invalidation for graph + resolver cache.
  - correctness-first full ONT recompute baseline.
- Akzeptanz:
  - keine stale path/signal Ergebnisse nach Mutationen.
- Depends on: TASK-122
- Builder Log:

#### [TASK-124] Fiber-Type Source-of-Truth als API bereitstellen
- Status: OPEN
- Sources: 04_signal
- Ziel: Faserkatalog (`SMF_G652D`, `SMF_G657A1`, `SMF_G657A2`, `MMF_OM3`, `MMF_OM4`) versioniert im Backend und via API verfügbar.
- Scope:
  - `GET /api/optical/fiber-types`.
  - UI liest Optionen ausschließlich aus API.
- Akzeptanz:
  - keine hardcodierten Fiber-Listen im Client.
- Depends on: TASK-049
- Builder Log:

#### [TASK-125] Optical Parameter Validation + Fehlercodes vervollständigen
- Status: OPEN
- Sources: 04_signal, 13
- Ziel: Negative Längen/Insertion-Loss und ungültige Fiber-Typen liefern normierte Fehlercodes.
- Scope:
  - `ATTENUATION_PARAM_INVALID`, `FIBER_TYPE_INVALID`.
  - validation path für single + batch Mutationen.
- Akzeptanz:
  - Eingabefehler werden konsistent als 4xx mit Code zurückgegeben.
- Depends on: TASK-045, TASK-124
- Builder Log:

#### [TASK-126] Override-Konflikt-Diagnostik einführen
- Status: OPEN
- Sources: 04_signal
- Ziel: Bei erzwungenem `UP` trotz fehlender Signal-/Pfadvoraussetzungen `OVERRIDE_CONFLICT` sichtbar emittieren/loggen.
- Scope:
  - conflict detection in status evaluation.
  - diagnostic event payload contract.
- Akzeptanz:
  - Override-Konflikte sind transparent, nicht still maskiert.
- Depends on: TASK-019, TASK-121
- Builder Log:

#### [TASK-127] Signal Payload Contract (voll + compact) absichern
- Status: OPEN
- Sources: 04_signal, 13
- Ziel: Event-Payload für Signalwerte stabilisieren, inkl. compact mode und API-Fallback für Pfaddetails.
- Scope:
  - full payload with path segments.
  - compact high-frequency payload + detail endpoint consistency.
- Akzeptanz:
  - Clients können beide Modi deterministisch verarbeiten.
- Depends on: TASK-050, TASK-121
- Builder Log:

#### [TASK-128] Signal/Override Test- und Observability-Baseline
- Status: OPEN
- Sources: 04_signal, 12
- Ziel: Mindesttestkorridor plus Metriken/Logs für optical recompute, Klassifikationswechsel und Override-Konflikte.
- Scope:
  - tests: path determinism, thresholds, event ordering, cache invalidation, override precedence.
  - metrics/logs: `optical_recompute_duration_ms`, `signal_status_changes_total`, `override_conflicts_total`.
- Akzeptanz:
  - Regressionen im Signal-/Override-Pfad werden früh erkannt.
- Depends on: TASK-046, TASK-047, TASK-123, TASK-126
- Builder Log:

### Real-time & UI Contract

#### [TASK-020] Socket-Event-Vertrag fixieren
- Status: OPEN
- Sources: 05, 13
- Ziel: konsistente Eventnamen/Payloads (`device:*`, `link:*`, status/signal/metrics).
- Akzeptanz:
  - dokumentierte Eventliste entspricht tatsächlich gesendeten Events.
- Depends on: TASK-004
- Builder Log:

#### [TASK-021] Zustand-Store Actions finalisieren
- Status: OPEN
- Sources: 05
- Ziel: API+Socket-Updatepfade ohne Polling-Drift.
- Akzeptanz:
  - CRUD-Operationen werden korrekt im Canvas reflektiert.
- Depends on: TASK-020
- Builder Log:

#### [TASK-022] UI Interaction Model (Select/Move/Link/Pan/Context)
- Status: OPEN
- Sources: 05
- Ziel: Interaktionen gemäß Modell inkl. Persistierung nach Drop.
- Akzeptanz:
  - keine inkonsistente Position/Link-Anlage nach User-Aktionen.
- Depends on: TASK-021
- Builder Log:

#### [TASK-023] Fehlercode-UI (Toast/Panel)
- Status: OPEN
- Sources: 05
- Ziel: standardisierte Backend-Fehler sichtbar und verständlich im UI.
- Akzeptanz:
  - definierte Error Codes werden als klare UI-Meldung dargestellt.
- Depends on: TASK-007
- Builder Log:

#### [TASK-129] Socket Envelope + `topo_version` Gap Recovery absichern
- Status: OPEN
- Sources: 05, 13
- Ziel: Einheitlicher Event-Envelope mit monotonic `topo_version` und verpflichtendem Client-Resync bei Versionslücken.
- Scope:
  - envelope fields (`type`, `kind`, `payload`, `topo_version`, `correlation_id`, `ts`).
  - gap detection policy in frontend store.
- Akzeptanz:
  - verpasste Events führen deterministisch zu Topology-Resync statt stiller Drift.
- Depends on: TASK-020, TASK-051
- Builder Log:

#### [TASK-130] Realtime Coalescing Window technisch konsolidieren
- Status: OPEN
- Sources: 05
- Ziel: Coalescing per `(event_type,id)` mit deterministic flush-order pro Tick/Window.
- Scope:
  - last-write-wins policy.
  - bounded memory behavior under bursts.
- Akzeptanz:
  - keine Event-Duplikatflut bei hoher Änderungsrate.
- Depends on: TASK-060, TASK-091
- Builder Log:

#### [TASK-131] Event Ordering Contract für Create/Derived Flows
- Status: OPEN
- Sources: 05, 04_signal
- Ziel: Reihenfolge `create -> derived signal/status` sowie `optical/link updates -> signal -> status` erzwingen.
- Scope:
  - ordering assertions in emitter pipeline.
  - contract tests for mixed mutation windows.
- Akzeptanz:
  - UI sieht konsistente Zwischenzustände ohne Reihenfolge-Rennen.
- Depends on: TASK-121, TASK-129
- Builder Log:

#### [TASK-132] Frontend Store Reconciliation ohne Polling-Drift
- Status: OPEN
- Sources: 05
- Ziel: Store verarbeitet API-Responses + Socket-Events idempotent und konfliktarm.
- Scope:
  - optimistic update rollback policy.
  - correlation-aware merge strategy.
- Akzeptanz:
  - wiederholte/reordered Events erzeugen keinen inkonsistenten Canvas-Zustand.
- Depends on: TASK-021, TASK-129
- Builder Log:

#### [TASK-133] Bulk Device Creation UX-Contract vervollständigen
- Status: OPEN
- Sources: 05
- Ziel: Bulk-Modal inkl. Accessibility, Parent-Regeln, Undo und Layout-Persistenz robust machen.
- Scope:
  - modal validation and keyboard flow.
  - undo window with operation-scoped rollback.
- Akzeptanz:
  - Bulk Create ist reproduzierbar, barrierearm und rücknehmbar.
- Depends on: TASK-022, TASK-030
- Builder Log:

#### [TASK-134] Ports Summary API + UI Occupancy Rendering finalisieren
- Status: OPEN
- Sources: 05, 08
- Ziel: `/api/ports/summary/:device_id` vollständig gemäß Rollenregeln umsetzen und im Detailpanel korrekt darstellen.
- Scope:
  - counting semantics for ACCESS/UPLINK/PON/MANAGEMENT.
  - UI badges from endpoint contract.
- Akzeptanz:
  - Portnutzung entspricht fachlichen Zählregeln in allen Gerätetypen.
- Depends on: TASK-033, TASK-034
- Builder Log:

#### [TASK-135] Optical Detail Panels (Link/Passive/OLT/ONT) contract-safe anbinden
- Status: OPEN
- Sources: 05, 04_signal
- Ziel: Bearbeitungs- und Analysepanels mit validierten Feldern, Save-Strategie und On-Demand Path-Details.
- Scope:
  - link medium/length edit + inline validation.
  - passive insertion loss, OLT tx power, ONT analysis panel.
- Akzeptanz:
  - Panel-Aktionen erzeugen erwartete Patches und konsistente Delta-Updates.
- Depends on: TASK-124, TASK-127
- Builder Log:

#### [TASK-136] Container Link-Proxy UX + Server-Hard-Block synchronisieren
- Status: OPEN
- Sources: 05, 07
- Ziel: Containerklick in Link-Mode öffnet Child-Selector; Backend blockiert Container-Endpunkte weiterhin strikt.
- Scope:
  - eligible child filtering by link rules.
  - explicit failure rendering for invalid endpoint attempts.
- Akzeptanz:
  - Nutzer kann keine semantisch invaliden Container-Links erstellen.
- Depends on: TASK-055, TASK-106
- Builder Log:

#### [TASK-137] Cockpit-Type Mapping als stabilen Renderer-Contract fixieren
- Status: OPEN
- Sources: 05, 09
- Ziel: Gerätetyp->Cockpit-Komponente dauerhaft konsistent halten, inkl. Container/Passive Klassen.
- Scope:
  - mapping registry with test coverage.
  - render layering invariants (containers background, children/links foreground).
- Akzeptanz:
  - gleiche Gerätetypen rendern über Releases hinweg ohne Mapping-Drift.
- Depends on: TASK-036, TASK-053
- Builder Log:

#### [TASK-138] Router TotCap Rendering + Capacity-Feldkompatibilität absichern
- Status: OPEN
- Sources: 05, 01, 13
- Ziel: Dual-field capacity contract stabil bedienen und Cockpit-Anzeige konsistent runden/einheiten.
- Scope:
  - flattened vs nested fallback rules.
  - deterministic display formatting (`current/max`).
- Akzeptanz:
  - keine widersprüchliche Kapazitätsanzeige im Router-Cockpit.
- Depends on: TASK-063, TASK-064
- Builder Log:

#### [TASK-139] Link Animation und Congestion-Hysterese UI-seitig robust machen
- Status: OPEN
- Sources: 05, 11
- Ziel: Nutzungsbasierte Linkanimation + hysterese-basierte Congestion-Indikatoren ohne Flicker.
- Scope:
  - animation gating/speed caps/tab-visibility pause.
  - threshold-crossing updates for device/link/GPON segments.
- Akzeptanz:
  - visuelle Zustände bleiben stabil bei schwankender Last.
- Depends on: TASK-043, TASK-044
- Builder Log:

#### [TASK-140] Fehlercode-Source-of-Truth + UI-Mapping durchziehen
- Status: OPEN
- Sources: 05, 13
- Ziel: Zentral definierte Error-Codes inkl. HTTP-Status und UI-Darstellung ohne doppelte Codepfade.
- Scope:
  - backend enum governance.
  - frontend mapping table for toast/panel with action hints.
- Akzeptanz:
  - neue Fehlercodes werden einmalig definiert und end-to-end korrekt angezeigt.
- Depends on: TASK-023, TASK-072
- Builder Log:

### Catalog, Simulation, Future Tracks

#### [TASK-024] Hardware Catalog integrieren
- Status: OPEN
- Sources: 06
- Ziel: Modell-Defaults (txPower, sensitivity, ports, fiber types) aus Katalog beziehen.
- Akzeptanz:
  - Provisioning/Optical Services nutzen Katalogwerte als Fallback.
- Depends on: TASK-002
- Builder Log:

#### [TASK-025] Deterministische Traffic Engine
- Status: OPEN
- Sources: 06, 11
- Ziel: tick-basierte, deterministische Metrikgeneration + Aggregation.
- Akzeptanz:
  - `/api/metrics/snapshot` + `device:metrics` liefern konsistente Strukturen.
- Depends on: TASK-020
- Builder Log:

#### [TASK-026] Cockpit Data Pipeline stabilisieren
- Status: OPEN
- Sources: 06, 09
- Ziel: SVG-/Cockpit-Updates performant (batch/rAF/throttle).
- Akzeptanz:
  - keine Render-Thrashing-Probleme bei Last.
- Depends on: TASK-025
- Builder Log:

#### [TASK-027] Extended Smart-Cockpit Konventionen
- Status: OPEN
- Sources: 06 (Sektion 16.x)
- Ziel: Konstanten, Color Scales, Render Debug Overlay, Delta-Handling.
- Akzeptanz:
  - zentrale Farb-/Konfigurationsquelle, dokumentierte Edge-Case-Strategie.
- Depends on: TASK-026
- Builder Log:

#### [TASK-028] Physics Engine Track markieren (ON HOLD)
- Status: DEFERRED
- Sources: 06 (Sektion 17)
- Ziel: klare Abgrenzung, dass D3-force Track aktuell nicht MVP-Blocker ist.
- Akzeptanz:
  - explizit deferred mit Re-Entry-Kriterien.
- Depends on: none
- Builder Log:

#### [TASK-029] Ring Protection Track markieren (Placeholder)
- Status: DEFERRED
- Sources: 06 (Sektion 19)
- Ziel: Spezifikation als zukünftiger Track ohne MVP-Blockade.
- Akzeptanz:
  - priorisierte Backlog-Notiz + offene Entscheidungen dokumentiert.
- Depends on: none
- Builder Log:

#### [TASK-141] Catalog Manifest + Integrity Pipeline produktiv absichern
- Status: OPEN
- Sources: 06
- Ziel: Manifest-basierter Ladevorgang mit `schema_version`-Prüfung und sha256-Integritätschecks.
- Scope:
  - startup validation flow.
  - strict-vs-dev mode failure policy.
- Akzeptanz:
  - fehlerhafte/inkonsistente Katalogdaten werden deterministisch erkannt.
- Depends on: TASK-024
- Builder Log:

#### [TASK-142] Catalog Schema + Indexing Contract vervollständigen
- Status: OPEN
- Sources: 06
- Ziel: Einheitliches Entry-Schema und stabile Indizes (`by_catalog_id`, `by_device_type`, `by_vendor_model`).
- Scope:
  - runtime validators for entry fields.
  - deterministic sort policy for API outputs.
- Akzeptanz:
  - Katalogabfragen liefern reproduzierbare und typvalidierte Ergebnisse.
- Depends on: TASK-141
- Builder Log:

#### [TASK-143] Override Merge Governance (Allowlist/Immutables)
- Status: OPEN
- Sources: 06
- Ziel: Nur erlaubte numerische Override-Felder mutierbar; Identitätsfelder strikt immutable.
- Scope:
  - reject unknown catalog ids.
  - explicit error details for forbidden overrides.
- Akzeptanz:
  - Overrides verändern niemals `catalog_id/device_type/vendor/model/version`.
- Depends on: TASK-142
- Builder Log:

#### [TASK-144] Catalog Service API im Backend konsolidieren
- Status: OPEN
- Sources: 06
- Ziel: Service-Funktionen (`getModel`, defaults, `listFiberTypes`, `computeCatalogHash`) als zentrale Backend-Schnittstelle.
- Scope:
  - single source service used by provisioning/optical paths.
  - no duplicate ad-hoc loaders in feature modules.
- Akzeptanz:
  - alle Fachpfade lesen Katalogdaten über dieselbe Service-Abstraktion.
- Depends on: TASK-142
- Builder Log:

#### [TASK-145] Catalog REST Contract + Versionierte Response-Formen
- Status: OPEN
- Sources: 06, 13
- Ziel: `/api/catalog/hardware` und `/api/catalog/hardware/:catalog_id` stabilisieren, inkl. deterministischer Sortierung.
- Scope:
  - list/detail response schema.
  - optional pagination governance without contract drift.
- Akzeptanz:
  - API entspricht Doku 1:1 und bleibt abwärtskompatibel.
- Depends on: TASK-049, TASK-144
- Builder Log:

#### [TASK-146] Provisioning Defaults Resolution Order technisch erzwingen
- Status: OPEN
- Sources: 06, 02
- Ziel: Auflösungsreihenfolge `device override -> catalog default -> fallback` konsistent implementieren.
- Scope:
  - persisted effective fields + catalog linkage.
  - `modified_from_catalog` semantik.
- Akzeptanz:
  - Geräte übernehmen Defaults korrekt, ohne implizite Silent-Overrides.
- Depends on: TASK-067, TASK-143
- Builder Log:

#### [TASK-147] Catalog Determinism + Hash/Startup Observability
- Status: OPEN
- Sources: 06
- Ziel: Stabiler `catalog_hash` und startup observability (counts, override diffs, failures).
- Scope:
  - structured logs for startup catalog state.
  - metrics (`catalog_entries_total`, load failures).
- Akzeptanz:
  - Katalogzustand ist reproduzierbar und operational sichtbar.
- Depends on: TASK-141
- Builder Log:

#### [TASK-148] Traffic Simulation Tick Engine deterministisch umsetzen
- Status: OPEN
- Sources: 06, 11
- Ziel: Tick-basierte Engine mit konfigurierbarem Intervall und deterministischer Leaf-Generierung.
- Scope:
  - seed/device/tick deterministic PRNG.
  - strict online-leaf gating policy.
- Akzeptanz:
  - identische Inputs liefern identische Tick-Serien.
- Depends on: TASK-025
- Builder Log:

#### [TASK-149] Metrics Diff/Versioning + Backpressure Contract
- Status: OPEN
- Sources: 06, 05
- Ziel: Delta-Emission anhand Epsilon/Bucket-Regeln und Versionierung, inkl. Queue-Collapse bei Backpressure.
- Scope:
  - per-device version increment policy.
  - latest-only metrics collapse strategy.
- Akzeptanz:
  - unter Last bleibt Realtime stabil ohne fachliche Drift.
- Depends on: TASK-130, TASK-148
- Builder Log:

#### [TASK-150] Snapshot-Recovery nach Reconnect/Version-Gaps
- Status: OPEN
- Sources: 06, 05
- Ziel: `GET /api/metrics/snapshot` als baseline reset bei reconnect oder `topo_version` gap.
- Scope:
  - full snapshot response with capacities.
  - client replacement strategy before delta resume.
- Akzeptanz:
  - Reconnect führt nicht zu inkonsistenten Metric-Stores.
- Depends on: TASK-129, TASK-149
- Builder Log:

#### [TASK-151] Sim Observability + Health Endpoint verankern
- Status: OPEN
- Sources: 06
- Ziel: Laufzeitmetriken und `GET /api/sim/status` als Betriebsgrundlage für Simulation.
- Scope:
  - tick duration/changes/skips metrics.
  - health payload with interval and tick state.
- Akzeptanz:
  - Simulation ist im Betrieb transparent überwachbar.
- Depends on: TASK-148
- Builder Log:

#### [TASK-152] Deferred Tracks Re-Entry Kriterien formalisieren
- Status: OPEN
- Sources: 06
- Ziel: Für Physics/Ring/Remote-Catalog Tracks klare Eintrittsbedingungen, Abhängigkeiten und Exit-Kriterien definieren.
- Scope:
  - re-entry checklist per deferred track.
  - architecture decision notes per track.
- Akzeptanz:
  - deferred Themen können später ohne Scope-Chaos wieder aufgenommen werden.
- Depends on: TASK-028, TASK-029
- Builder Log:

### Container Model

#### [TASK-030] Container-Datenmodell (parent/children)
- Status: OPEN
- Sources: 07
- Ziel: Container (`POP`, `CORE_SITE`) + Parent-Regeln + Cycle-Schutz.
- Akzeptanz:
  - gültige Hierarchien, keine Self/Loop-Zyklen.
- Depends on: TASK-001
- Builder Log:

#### [TASK-031] Container-UI Interaktionen
- Status: OPEN
- Sources: 07
- Ziel: Drag in/out, Expand/Collapse, Group-Nodes.
- Akzeptanz:
  - Parent-Zuweisung wird über API persistiert.
- Depends on: TASK-030, TASK-022
- Builder Log:

#### [TASK-032] Container Aggregates + Link Proxy UX
- Status: OPEN
- Sources: 07
- Ziel: Health/Capacity Aggregation + Zielauswahl bei Link auf Container.
- Akzeptanz:
  - Link-Proxied Flow erzeugt korrekten Link auf Child.
- Depends on: TASK-031
- Builder Log:

#### [TASK-153] Container Parent-Policy serverseitig lückenlos erzwingen
- Status: OPEN
- Sources: 07, 02
- Ziel: `POP/CORE_SITE` parent-null, `OLT/AON_SWITCH` optional mit erlaubtem Parent, ONT/CPE nie als Parent.
- Scope:
  - all create/update/provision endpoints apply same parent validator.
  - deterministic validation errors on policy violations.
- Akzeptanz:
  - keine inkonsistenten Parent-Relationen in DB/API.
- Depends on: TASK-030, TASK-068
- Builder Log:

#### [TASK-154] Container Cycle-Guard (self/indirect) technisch absichern
- Status: OPEN
- Sources: 07
- Ziel: Self-parenting und indirekte Parent-Loops zuverlässig blockieren.
- Scope:
  - ancestry traversal checks with bounded complexity.
  - regression tests for multi-step reparent scenarios.
- Akzeptanz:
  - zyklische Containerbeziehungen sind unmöglich.
- Depends on: TASK-153
- Builder Log:

#### [TASK-155] Drag-and-Drop Reparenting mit robustem Rollback
- Status: OPEN
- Sources: 07, 05
- Ziel: UI-Reparenting via `parent_container_id` patch mit klarer optimistic/rollback-Strategie.
- Scope:
  - valid/invalid target visualization.
  - failed mutation rollback without stale selection state.
- Akzeptanz:
  - fehlgeschlagene Reparents hinterlassen keinen inkonsistenten Canvas-State.
- Depends on: TASK-031, TASK-132
- Builder Log:

#### [TASK-156] Slot-Snapping und Containment deterministisch stabilisieren
- Status: OPEN
- Sources: 07
- Ziel: Slot-Anker als UX-Hilfe plus Containment ohne Layout-Jitter oder Geometrie-Drift.
- Scope:
  - anchor snapping thresholds.
  - pinned-node and edge-clamp rules.
- Akzeptanz:
  - wiederholte Layout-Interaktionen bleiben visuell stabil/reproduzierbar.
- Depends on: TASK-155
- Builder Log:

#### [TASK-157] Container Link-Proxy Selector End-to-End härten
- Status: OPEN
- Sources: 07, 04_links
- Ziel: Klick auf Container im Link-Mode öffnet validen Child-Selector und erzeugt Link auf reales Child.
- Scope:
  - eligible-child filtering by link rules.
  - empty-target handling (`No valid targets in container`).
- Akzeptanz:
  - Container-Proxy-Flow verhindert dead-end Link-Interaktionen.
- Depends on: TASK-136, TASK-105
- Builder Log:

#### [TASK-158] Container Endpoint Hard-Block API-weit garantieren
- Status: OPEN
- Sources: 07, 04_links
- Ziel: Container als direkte Link-Endpunkte in allen Link-APIs (single/batch/update) strikt verbieten.
- Scope:
  - validation consistency across endpoint variants.
  - error-code normalization for container endpoint attempts.
- Akzeptanz:
  - direkte Container-Links sind technisch unmöglich.
- Depends on: TASK-106, TASK-077
- Builder Log:

#### [TASK-159] Container Aggregate Read-Model (Health/Traffic/Occupancy)
- Status: OPEN
- Sources: 07, 11
- Ziel: Deterministische Container-Rollups für Cockpit-Anzeige mit Health-Precedence `DOWN > DEGRADED > UP`.
- Scope:
  - child-status aggregation.
  - traffic and occupancy summaries from stores/endpoints.
- Akzeptanz:
  - Container-Cockpits zeigen konsistente Aggregatwerte ohne Semantikdrift.
- Depends on: TASK-032, TASK-139
- Builder Log:

#### [TASK-160] `deviceContainerChanged` Event-Contract + Ordering absichern
- Status: OPEN
- Sources: 07, 05
- Ziel: Reparent-Events mit nullable `parent_container_id` stabil und in definierter Reihenfolge emittieren.
- Scope:
  - payload schema checks.
  - ordering tests within mixed mutation windows.
- Akzeptanz:
  - Clients können Containeränderungen idempotent und gap-safe verarbeiten.
- Depends on: TASK-129, TASK-131
- Builder Log:

#### [TASK-161] Pathfinding/Status/Optical Container-Invarianten erzwingen
- Status: OPEN
- Sources: 07, 03, 04_signal
- Ziel: Container-Mitgliedschaft darf Graph, Passability oder Optical Pfadberechnung fachlich nicht verändern.
- Scope:
  - graph projection excludes containers.
  - regression checks for reparent-only topology mutations.
- Akzeptanz:
  - Reparenting ändert keine Link-/Path-/Signal-Semantik außer explizit spezifizierten UI-Rollups.
- Depends on: TASK-118, TASK-088
- Builder Log:

#### [TASK-162] Container Error/404 Contract und UI-Darstellung vereinheitlichen
- Status: OPEN
- Sources: 07, 13
- Ziel: Einheitliche Fehlerantworten für invalid parent, stale ids, container endpoint violations und konsistente UI-Meldungen.
- Scope:
  - canonical error code mapping to toasts/panels.
  - 404/4xx behavior harmonization.
- Akzeptanz:
  - Nutzer erhält in allen Container-Flows klare, einheitliche Fehlerrückmeldungen.
- Depends on: TASK-140, TASK-158
- Builder Log:

### Ports

#### [TASK-033] Port Summary API fachlich erweitern
- Status: OPEN
- Sources: 08, 13
- Ziel: Occupancy/Capacity pro Port (nicht nur rohe Ports).
- Akzeptanz:
  - `GET /api/ports/summary/:deviceId` liefert UI-taugliche Summary.
- Depends on: TASK-013
- Builder Log:

#### [TASK-034] ONT-List Endpoint für Port/Container Views
- Status: OPEN
- Sources: 08
- Ziel: `GET /api/ports/ont-list/:deviceId`.
- Akzeptanz:
  - korrekte ONT-Listen nach Topologie.
- Depends on: TASK-033
- Builder Log:

#### [TASK-035] Port-Caching mit topologyVersion
- Status: OPEN
- Sources: 08
- Ziel: performante Summary-Berechnung mit klarer Invalidation.
- Akzeptanz:
  - Recompute nur bei relevanten Topologieänderungen.
- Depends on: TASK-033
- Builder Log:

#### [TASK-163] Port Summary Contract normieren (single + bulk)
- Status: OPEN
- Sources: 08, 13
- Ziel: Einheitliche aggregate-by-role Semantik für `GET /api/ports/summary/:device_id` und Bulk-Variante.
- Scope:
  - stable summary fields (`device_id,total,by_role`).
  - deterministic unknown-id/partial behavior in bulk path.
- Akzeptanz:
  - single- und bulk-summary liefern konsistente, vorhersehbare Payloads.
- Depends on: TASK-033, TASK-049
- Builder Log:

#### [TASK-164] Occupancy-Regeln pro Port-Rolle fachlich vollständig durchziehen
- Status: OPEN
- Sources: 08
- Ziel: Normative Occupancy-Berechnung für `PON/ACCESS/UPLINK/TRUNK` inklusive Management-Exklusion.
- Scope:
  - per-role counting rules as shared backend logic.
  - edge-case handling for empty/legacy role data.
- Akzeptanz:
  - Occupancy-Werte entsprechen in allen Rollen der Spezifikation.
- Depends on: TASK-033, TASK-118
- Builder Log:

#### [TASK-165] Capacity-Herkunft und Fallbacks pro Rolle absichern
- Status: OPEN
- Sources: 08, 10
- Ziel: Kapazitätswerte reproduzierbar aus Profil/Interface-Feldern ableiten und sauber nullen wenn unbekannt.
- Scope:
  - PON profile-based capacity mapping.
  - non-PON persisted capacity fallback strategy.
- Akzeptanz:
  - UI erhält konsistente `capacity`-Werte ohne implizite Schätzungen.
- Depends on: TASK-039, TASK-163
- Builder Log:

#### [TASK-166] Ports-Cache + Locking unter Last robust machen
- Status: OPEN
- Sources: 08
- Ziel: `(topology_version,device_id)`-Caching mit per-key lock/dogpile-schutz und sauberer Invalidation.
- Scope:
  - TTL tuning for polling.
  - topology bump invalidation correctness.
- Akzeptanz:
  - hohe Polling-Last erzeugt keine redundante Recompute-Stürme.
- Depends on: TASK-035, TASK-123
- Builder Log:

#### [TASK-167] Polling-/Rate-Limit Governance für Port-Endpunkte
- Status: OPEN
- Sources: 08, 05
- Ziel: Polling-Cadence, Offscreen-Suspend und `429`-Handling für UI/Backend harmonisieren.
- Scope:
  - frontend suspend/resume policy.
  - backend throttling behavior and headers.
- Akzeptanz:
  - Port-UI bleibt responsiv ohne Endpoint-Überlastung.
- Depends on: TASK-132, TASK-166
- Builder Log:

#### [TASK-168] Ports Testpaket (Backend + Frontend) erweitern
- Status: OPEN
- Sources: 08, 12
- Ziel: Occupancy-, Cache-, Bulk- und Rendering-Regressionen automatisiert absichern.
- Scope:
  - backend tests for role occupancy and invalidation.
  - frontend tests for grouped render/polling behavior.
- Akzeptanz:
  - Ports-Verhalten bleibt stabil über Topologie- und Laständerungen.
- Depends on: TASK-045, TASK-166
- Builder Log:

### Cockpit Nodes

#### [TASK-036] Cockpit-Komponentenstrukturen aufbauen
- Status: OPEN
- Sources: 09
- Ziel: Router/OLT/ONT/Passive Cockpit Components + Wrapper.
- Akzeptanz:
  - Mapping DeviceRole -> Component implementiert.
- Depends on: TASK-026
- Builder Log:

#### [TASK-037] Port Matrix + Signal Gauge im UI
- Status: OPEN
- Sources: 09
- Ziel: OLT Matrix und ONU Signalanzeige gemäß Spezifikation.
- Akzeptanz:
  - Cockpit zeigt Status/Metrics/Ports korrekt.
- Depends on: TASK-036, TASK-033
- Builder Log:

#### [TASK-038] Cockpit Performance Hardening
- Status: OPEN
- Sources: 09
- Ziel: `React.memo`, stabile Props, Update-Throttling.
- Akzeptanz:
  - kein unnötiges Re-Rendern bei unveränderten Daten.
- Depends on: TASK-036
- Builder Log:

#### [TASK-169] DeviceType->Cockpit Mapping Registry fixieren
- Status: OPEN
- Sources: 09
- Ziel: Vollständige, getestete Mapping-Tabelle inkl. Fallback `GenericCockpit`.
- Scope:
  - canonical mapping for active/passive/container classes.
  - unknown-type fallback contract.
- Akzeptanz:
  - jeder Gerätetyp wird deterministisch der korrekten Cockpit-Komponente zugeordnet.
- Depends on: TASK-036, TASK-053
- Builder Log:

#### [TASK-170] Cockpit Props Normalization und Optionality-Contract
- Status: OPEN
- Sources: 09, 08
- Ziel: Einheitliches View-Model (`device/metrics/ports/links`) mit robustem Handling fehlender Optionalfelder.
- Scope:
  - normalized adapter layer.
  - soft-fail strategy for partial payloads.
- Akzeptanz:
  - Cockpits bleiben funktionsfähig bei partiellen Datenständen.
- Depends on: TASK-163, TASK-132
- Builder Log:

#### [TASK-171] Router TotCap Rendering-Regeln technisch erzwingen
- Status: OPEN
- Sources: 09, 05
- Ziel: Exaktes Label/Format `TotCap (Gbps)` inkl. dual-field capacity fallback und deterministischer Rundung.
- Scope:
  - formatting utility + snapshot tests.
  - metrics+capacity merge rules.
- Akzeptanz:
  - TotCap-Anzeige ist über alle Router-Cases konsistent.
- Depends on: TASK-138
- Builder Log:

#### [TASK-172] Matrix-Cockpits (OLT/AON) Datenfluss und Drilldown robust machen
- Status: OPEN
- Sources: 09, 08
- Ziel: OLT/AON-Matrizen auf Ports-Contract stützen, inkl. Drilldown-Flows und Statusfarben.
- Scope:
  - PON/ACCESS tile rendering from summary data.
  - ONT list drilldown contract integration.
- Akzeptanz:
  - Matrixanzeigen stimmen fachlich mit Port-Summaries überein.
- Depends on: TASK-134, TASK-163
- Builder Log:

#### [TASK-173] Container/Passive Cockpit Aggregationsvertrag stabilisieren
- Status: OPEN
- Sources: 09, 07
- Ziel: Container-Health/Traffic-Rollups und splitter-spezifische Badges konsistent und semantiktreu darstellen.
- Scope:
  - `DOWN>DEGRADED>UP` aggregation precedence.
  - splitter badge source from splitter parameters contract.
- Akzeptanz:
  - Aggregat- und Role-spezifische Anzeigen bleiben widerspruchsfrei.
- Depends on: TASK-159, TASK-010
- Builder Log:

#### [TASK-174] Cockpit A11y/Performance/Test-Baseline vollständig
- Status: OPEN
- Sources: 09, 12
- Ziel: Keyboard/contrast/a11y Regeln plus memoization/render-budget und tests verbindlich absichern.
- Scope:
  - accessibility checks for matrix navigation.
  - rerender profiling and regression tests.
- Akzeptanz:
  - Cockpit-UI bleibt zugänglich und performant bei Last.
- Depends on: TASK-038, TASK-048
- Builder Log:

### Interfaces & Addresses

#### [TASK-039] Interface/Address Datenmodell ergänzen
- Status: OPEN
- Sources: 10
- Ziel: Interface + Address Entitäten mit Rollen (`PON`, `UPLINK`, `ACCESS`, `TRUNK`, `MGMT`).
- Akzeptanz:
  - Interfaces/Adressen persistiert und abfragbar.
- Depends on: TASK-001, TASK-009
- Builder Log:

#### [TASK-040] Deterministische MAC-Generierung
- Status: OPEN
- Sources: 10
- Ziel: zentraler `MacAllocator` nach OUI-Regel.
- Akzeptanz:
  - keine MAC-Kollision, deterministisches Verhalten bei Reset.
- Depends on: TASK-039
- Builder Log:

#### [TASK-041] Interfaces API bereitstellen
- Status: OPEN
- Sources: 10
- Ziel: `GET /api/interfaces/:deviceId` inkl. Adressen.
- Akzeptanz:
  - Response-Struktur gemäß Doku.
- Depends on: TASK-039
- Builder Log:

#### [TASK-175] Interface/Address Schema-Constraints vervollständigen
- Status: OPEN
- Sources: 10
- Ziel: Eindeutige Constraints für `(device_id,name)`, `mac_address`, Primary-Address-Regeln und rollenbasierte Feldvalidierung.
- Scope:
  - DB constraints + service-level guards.
  - VRF-aware primary uniqueness policy.
- Akzeptanz:
  - inkonsistente Interface/Address-Zustände sind technisch ausgeschlossen.
- Depends on: TASK-039, TASK-083
- Builder Log:

#### [TASK-176] Deterministischen Naming Planner pro Hardware-Profil absichern
- Status: OPEN
- Sources: 10, 06
- Ziel: Stabile Interface-Namen (`mgmt0`, `ponN`, `uplinkN`, `accessN`) aus Modell/Profil ohne Reihenfolge-Drift.
- Scope:
  - canonical role ordering and index strategy.
  - migration guard for profile changes.
- Akzeptanz:
  - gleiche Modellinputs erzeugen reproduzierbare Interface-Namensräume.
- Depends on: TASK-039, TASK-024
- Builder Log:

#### [TASK-177] MacAllocator Concurrency/Retry-Verhalten härten
- Status: OPEN
- Sources: 10
- Ziel: Kollisionsfreie MAC-Zuweisung unter Parallel-Provisioning mit atomarem Reserve/Commit-Pfad.
- Scope:
  - allocator lock/transaction semantics.
  - retry + observability on uniqueness conflicts.
- Akzeptanz:
  - keine MAC-Kollisionen auch unter Last.
- Depends on: TASK-040, TASK-070
- Builder Log:

#### [TASK-178] Provisioning-Integration für Interfaces/Addresses idempotent machen
- Status: OPEN
- Sources: 10, 02, 03
- Ziel: Provisioning erzeugt deterministische Interfaces/Adressen und bleibt bei Wiederholung ohne Duplikate.
- Scope:
  - mgmt duplicate guard.
  - pool allocation/linkage consistency.
- Akzeptanz:
  - wiederholtes Provisioning erzeugt keinen Schema-Drift.
- Depends on: TASK-067, TASK-175
- Builder Log:

#### [TASK-179] Interfaces API Contract erweitern (ordering + errors + optionals)
- Status: OPEN
- Sources: 10, 13
- Ziel: `GET /api/interfaces/:deviceId` mit stabiler Sortierung, klaren Fehlercodes und optionalen Feldern robust versionieren.
- Scope:
  - response ordering by role/name.
  - 404/4xx mapping and contract tests.
- Akzeptanz:
  - API liefert reproduzierbare Responses und eindeutige Fehlersemantik.
- Depends on: TASK-041, TASK-049
- Builder Log:

#### [TASK-180] Interfaces Observability + Testmatrix vollständig
- Status: OPEN
- Sources: 10, 12
- Ziel: Logs/Metriken für Allocator/Addressing plus Regressionstests für Determinismus und Concurrency.
- Scope:
  - metrics: created interfaces, mac conflicts, ip assignment failures.
  - unit+integration tests for naming/mac/api ordering.
- Akzeptanz:
  - Interface/Address Regressionen werden frühzeitig erkannt.
- Depends on: TASK-047, TASK-177
- Builder Log:

### Traffic & Congestion

#### [TASK-042] GPON Segment Modell
- Status: OPEN
- Sources: 11
- Ziel: Segmentdefinition je OLT-PON bis first passive aggregation.
- Akzeptanz:
  - Segment-ID/Mapping reproduzierbar.
- Depends on: TASK-025, TASK-033
- Builder Log:

#### [TASK-043] Congestion Hysteresis umsetzen
- Status: OPEN
- Sources: 11
- Ziel: Enter/Exit-Schwellen für Device/Link/Segment ohne Flicker.
- Akzeptanz:
  - Zustandswechsel nur bei Schwellwert-Transitions.
- Depends on: TASK-042
- Builder Log:

#### [TASK-044] Congestion Event Contract
- Status: OPEN
- Sources: 11
- Ziel: `segment.congestion.detected/cleared` + device metrics events.
- Akzeptanz:
  - Events mit Tick/Utilization/PON-Kontext vorhanden.
- Depends on: TASK-043, TASK-020
- Builder Log:

#### [TASK-181] Traffic Tick Engine Determinismus und Scheduler-SLA absichern
- Status: OPEN
- Sources: 11, 06
- Ziel: Konfigurierbare Tick-Engine mit deterministischer Leaf-Generierung und stabiler Kadenz.
- Scope:
  - runtime loop timing/catch-up policy.
  - deterministic seed/device/tick generation contract.
- Akzeptanz:
  - identische Inputs erzeugen identische Tick-Reihen bei stabiler Tick-Kadenz.
- Depends on: TASK-148
- Builder Log:

#### [TASK-182] Asymmetrische Tarif- und Richtungsaggregation vollständig
- Status: OPEN
- Sources: 11
- Ziel: Upstream/Downstream getrennt generieren/aggregieren statt implizit symmetrisch.
- Scope:
  - per-direction leaf generation.
  - per-direction aggregation and capacity checks.
- Akzeptanz:
  - asymmetrische Tarife werden fachlich korrekt reflektiert.
- Depends on: TASK-181
- Builder Log:

#### [TASK-183] GPON Segment Identity/Capacity Contract stabilisieren
- Status: OPEN
- Sources: 11, 08
- Ziel: Deterministische Segmentdefinition pro OLT-PON bis erster Aggregationsgrenze inkl. Kapazitätsauflösung.
- Scope:
  - stable segment id construction.
  - profile/default fallback for segment capacity.
- Akzeptanz:
  - Segment-Mapping und Kapazitätswerte bleiben reproduzierbar über Ticks.
- Depends on: TASK-042, TASK-165
- Builder Log:

#### [TASK-184] Hysterese-State-Machine gegen Flattern absichern
- Status: OPEN
- Sources: 11
- Ziel: Enter/Clear-Transitions für Device/Link/Segment strikt nach Schwellenwerten emittieren.
- Scope:
  - no-event-on-steady-state behavior.
  - threshold boundary tests.
- Akzeptanz:
  - Congestion-Indikatoren bleiben stabil ohne Flicker.
- Depends on: TASK-043, TASK-095
- Builder Log:

#### [TASK-185] Congestion/Metrics Event Ordering + Snapshot-Reconciliation
- Status: OPEN
- Sources: 11, 05
- Ziel: Event-Reihenfolge und Reconnect-Baseline (`/api/metrics/snapshot`) für Gap-safe Verarbeitung sichern.
- Scope:
  - ordering policy metrics vs status/topology events.
  - client baseline replacement on reconnect/version gaps.
- Akzeptanz:
  - Reconnect oder Eventlücken führen nicht zu inkonsistenten Congestion-Zuständen.
- Depends on: TASK-150, TASK-044
- Builder Log:

#### [TASK-186] Traffic/Congestion Observability + Resilience Tests
- Status: OPEN
- Sources: 11, 12
- Ziel: Health/metrics/logging plus Fehlerresilienz (tick exceptions, backpressure collapse, no-leaf fast path) testbar machen.
- Scope:
  - `/api/sim/status` contract checks.
  - resilience test suite for runtime failure scenarios.
- Akzeptanz:
  - Traffic-Engine bleibt unter Fehlern und Last betriebssicher.
- Depends on: TASK-151, TASK-047
- Builder Log:

### Testing & Quality

#### [TASK-045] Negativtests für API-Validierung
- Status: OPEN
- Sources: 12, 05
- Ziel: 4xx-Fälle für invalid links/types/parents/status.
- Akzeptanz:
  - definierte Error Codes testabgedeckt.
- Depends on: TASK-007, TASK-013
- Builder Log:

#### [TASK-046] Socket Contract Tests
- Status: OPEN
- Sources: 12, 05, 13
- Ziel: Eventname/Payload/order testen.
- Akzeptanz:
  - Eventschema-Verstöße schlagen Tests fehl.
- Depends on: TASK-020
- Builder Log:

#### [TASK-047] Performance Harness implementieren
- Status: OPEN
- Sources: 12
- Ziel: `perf:seed` + `perf:load` real nutzbar machen.
- Akzeptanz:
  - reproduzierbarer Lasttest + dokumentierter Output.
- Depends on: TASK-025, TASK-043
- Builder Log:

#### [TASK-048] CI-Gates erzwingen
- Status: OPEN
- Sources: 12
- Ziel: lint/test/build als verpflichtende Pipeline.
- Akzeptanz:
  - Merge ohne grüne Gates nicht möglich.
- Depends on: TASK-045
- Builder Log:

#### [TASK-187] Test-Pyramide und Contract-Boundaries formalisieren
- Status: OPEN
- Sources: 12
- Ziel: Klare Testschichten (smoke/negative/realtime/simulation/ui-contract) mit stabilen Zuständigkeiten definieren.
- Scope:
  - layer ownership and required assertions per layer.
  - deterministic fixture policy.
- Akzeptanz:
  - neue Tests werden konsistent in die passende Schicht eingeordnet.
- Depends on: TASK-045, TASK-046
- Builder Log:

#### [TASK-188] API Negative Suite um vollständige Fehlercode-Abdeckung erweitern
- Status: OPEN
- Sources: 12, 13
- Ziel: Alle kanonischen 4xx-Pfade mit Error-Code-Asserts und Payload-Form absichern.
- Scope:
  - invalid links/parents/optical params/pool exhaustion.
  - deterministic error envelope assertions.
- Akzeptanz:
  - Error-Code-Regressionen werden automatisch erkannt.
- Depends on: TASK-072, TASK-140
- Builder Log:

#### [TASK-189] Realtime Contract + Ordering + Gap-Recovery Tests härten
- Status: OPEN
- Sources: 12, 05
- Ziel: Eventnamen/Payloads/Ordering und Reconnect-Gap-Verhalten testseitig verbindlich machen.
- Scope:
  - envelope validation incl. `topo_version`.
  - reconnect snapshot-baseline tests.
- Akzeptanz:
  - Realtime-Vertrag bleibt stabil trotz Refactors.
- Depends on: TASK-129, TASK-131, TASK-150
- Builder Log:

#### [TASK-190] Performance Harness (seed/load) reproduzierbar operationalisieren
- Status: OPEN
- Sources: 12, 06
- Ziel: `perf:seed` und `perf:load` mit deterministischen Szenarioprofilen und standardisiertem Ergebnisoutput umsetzen.
- Scope:
  - scale profiles and metadata manifest.
  - benchmark output parser/report.
- Akzeptanz:
  - Performance-Läufe sind reproduzierbar und vergleichbar.
- Depends on: TASK-047, TASK-148
- Builder Log:

#### [TASK-191] Performance Budgets und Regression Gates definieren
- Status: OPEN
- Sources: 12
- Ziel: p95/p99 Budgets für kritische Pfade definieren und als Gate/Report in CI integrieren.
- Scope:
  - topology/mutation/tick latency budgets.
  - threshold breach reporting.
- Akzeptanz:
  - Performance-Regressionen blockieren oder markieren Builds deterministisch.
- Depends on: TASK-190, TASK-048
- Builder Log:

#### [TASK-192] Test/Perf Observability Artefakte standardisieren
- Status: OPEN
- Sources: 12
- Ziel: Einheitliche Reports (junit, contract diff, benchmark summary) und Metrikausgabe für Tests/Benchmarks.
- Scope:
  - artifact schema/versioning.
  - CI upload + retention policy.
- Akzeptanz:
  - Qualitäts- und Performancezustand ist pro Run nachvollziehbar.
- Depends on: TASK-191, TASK-079
- Builder Log:

### API Reference Parity

#### [TASK-049] REST-Referenz 1:1 mit Implementierung abgleichen
- Status: OPEN
- Sources: 13
- Ziel: jeder dokumentierte Endpoint existiert mit passendem Verhalten.
- Akzeptanz:
  - kein drift zwischen `docs/13` und Servercode.
- Depends on: TASK-012, TASK-016, TASK-041
- Builder Log:

#### [TASK-050] WebSocket-Referenz 1:1 abgleichen
- Status: OPEN
- Sources: 13
- Ziel: dokumentierte Events + Payloads exakt erfüllt.
- Akzeptanz:
  - keine Eventnamen-/Payload-Divergenz.
- Depends on: TASK-020, TASK-044
- Builder Log:

#### [TASK-051] Versionierte API-Contract-Checks
- Status: OPEN
- Sources: 13
- Ziel: Contract Tests als Regression-Absicherung.
- Akzeptanz:
  - breaking change nur mit expliziter Doku-/Version-Änderung.
- Depends on: TASK-045, TASK-046
- Builder Log:

#### [TASK-052] Doku-Synchronisation abschließen
- Status: OPEN
- Sources: 01..13
- Ziel: Endabgleich aller Fachdokus mit Ist-Stand + offenen DEFERRED-Themen.
- Akzeptanz:
  - jeder offene Punkt ist als OPEN/DEFERRED Task referenziert.
- Depends on: TASK-001..051
- Builder Log:

#### [TASK-193] REST Endpoint-Matrix vollständig kanonisieren
- Status: OPEN
- Sources: 13
- Ziel: Vollständige Methode/Path-Matrix (`/api`) inkl. Batch-, Catalog-, Optical-, Metrics- und Interface-Endpunkte dokumentieren.
- Scope:
  - canonical path list with operation purpose.
  - deprecated/alias path governance notes.
- Akzeptanz:
  - API-Referenz enthält alle produktiven öffentlichen REST-Endpunkte ohne Lücken.
- Depends on: TASK-049, TASK-116
- Builder Log:

#### [TASK-194] Error Envelope + Code Mapping als API-Vertrag fixieren
- Status: OPEN
- Sources: 13
- Ziel: Einheitliches Fehlerformat (`code/message/details/request_id`) und deterministische HTTP-Status-Zuordnung dokumentieren/prüfen.
- Scope:
  - code catalog alignment with backend enum.
  - payload examples for common failure classes.
- Akzeptanz:
  - alle dokumentierten Fehlerpfade nutzen dieselbe Envelope-Struktur.
- Depends on: TASK-140, TASK-188
- Builder Log:

#### [TASK-195] Socket Event Inventory + Envelope Parität abschließen
- Status: OPEN
- Sources: 13, 05
- Ziel: Vollständige Eventliste inkl. Envelope-Feldern, Ordering und Gap-Recovery-Regeln versioniert dokumentieren.
- Scope:
  - event name canonicalization.
  - ordering section with normative sequence.
- Akzeptanz:
  - WebSocket-Referenz deckt reale Emissionen 1:1 ab.
- Depends on: TASK-050, TASK-129
- Builder Log:

#### [TASK-196] OpenAPI/Schema-Quellen für REST-Contracts etablieren
- Status: OPEN
- Sources: 13
- Ziel: Maschinenlesbare Contract-Quelle für REST-Payloads/Responses aufbauen und mit Doku synchron halten.
- Scope:
  - schema generation/export workflow.
  - CI drift checks between code and generated spec.
- Akzeptanz:
  - REST-Contract-Drift wird automatisiert erkannt.
- Depends on: TASK-051, TASK-193
- Builder Log:

#### [TASK-197] API Versioning/Compatibility Policy operationalisieren
- Status: OPEN
- Sources: 13
- Ziel: Regeln für breaking changes, aliasing (`/api/v1`) und Deprecation-Kommunikation verbindlich machen.
- Scope:
  - compatibility matrix and deprecation timelines.
  - required test/doc updates for breaking changes.
- Akzeptanz:
  - Versionswechsel und Abwärtskompatibilität sind klar steuerbar.
- Depends on: TASK-116, TASK-051
- Builder Log:

#### [TASK-198] Finale Doku-zu-Implementierung Traceability für 13 abschließen
- Status: OPEN
- Sources: 13, 12
- Ziel: Vollständigen Querverweis zwischen API-Referenz, Contract-Tests und implementierten Routen/Events herstellen.
- Scope:
  - endpoint/event -> test case mapping table.
  - unresolved gaps as explicit OPEN/DEFERRED items.
- Akzeptanz:
  - jede Referenzstelle ist testbar und in der Implementierung nachweisbar.
- Depends on: TASK-193, TASK-195, TASK-196
- Builder Log:

### Architecture & Operations Docs

#### [TASK-199] Architektur-Übersicht als konsolidierten Einstieg härten
- Status: OPEN
- Sources: ARCHITECTURE
- Ziel: `ARCHITECTURE.md` als konsistente High-Level-Einstiegsdoku mit klaren Layern, Servicegrenzen und Vertragsprinzipien etablieren.
- Scope:
  - runtime layer map and data-flow narrative.
  - principles aligned with backend-authoritative design.
- Akzeptanz:
  - Architekturübersicht widerspricht keiner Fachdoku und bleibt für Onboarding nutzbar.
- Depends on: TASK-052
- Builder Log:

#### [TASK-200] Domain-Service-Boundaries und Ownership explizit machen
- Status: OPEN
- Sources: ARCHITECTURE
- Ziel: Service-Verantwortlichkeiten (Device/Link/Provisioning/Status/Optical/Traffic/Ports/Catalog/Event) eindeutig dokumentieren.
- Scope:
  - ownership boundaries and no-overlap rules.
  - cross-service dependency notes.
- Akzeptanz:
  - Implementierungsentscheidungen lassen sich auf dokumentierte Servicegrenzen zurückführen.
- Depends on: TASK-199
- Builder Log:

#### [TASK-201] Determinismus- und Event-Ordering-Prinzipien in Architektur verankern
- Status: OPEN
- Sources: ARCHITECTURE, 05
- Ziel: Architekturweit verbindliche Determinismus- und Event-Ordering-Baselines dokumentieren.
- Scope:
  - canonical ordering sequence.
  - topo_version gap recovery principle.
- Akzeptanz:
  - Architekturreferenz deckt die im Realtime-Contract geforderten Reihenfolgen nachvollziehbar ab.
- Depends on: TASK-129, TASK-131, TASK-199
- Builder Log:

#### [TASK-202] Architektur-Map zu Docs/Roadmap vollständig pflegen
- Status: OPEN
- Sources: ARCHITECTURE
- Ziel: Vollständige, aktuelle Verlinkung der Kernspezifikationen (01..14) und Roadmap-Source-of-Truth.
- Scope:
  - canonical docs index in architecture file.
  - stale link checks in CI/docs review process.
- Akzeptanz:
  - neue Teammitglieder finden alle relevanten Spezifikationen direkt über die Architektur-Übersicht.
- Depends on: TASK-199, TASK-198
- Builder Log:

#### [TASK-203] Commands Playbook auf reale Skripte/Runtime angleichen
- Status: OPEN
- Sources: 14_commands
- Ziel: `14_commands_playbook.md` muss exakt die tatsächlich vorhandenen NPM/Prisma/Perf-Kommandos abbilden.
- Scope:
  - script parity checks against `package.json`.
  - runtime/env prerequisites clarity.
- Akzeptanz:
  - keine veralteten oder nicht existierenden Kommandos in der Playbook-Doku.
- Depends on: TASK-198
- Builder Log:

#### [TASK-204] Lokale Betriebsreihenfolge + Fehlerbehebung standardisieren
- Status: OPEN
- Sources: 14_commands
- Ziel: Einheitliche lokale Runbooks für Setup/Dev/Test/Build mit klaren Troubleshooting-Pfaden dokumentieren.
- Scope:
  - recommended command sequence.
  - known failure quick-fixes (Prisma drift, DB mismatch, perf dependencies).
- Akzeptanz:
  - reproduzierbarer lokaler Start ohne implizites Teamwissen.
- Depends on: TASK-203
- Builder Log:

#### [TASK-205] CI-Gate-Abbildung in Commands und Testdocs synchronisieren
- Status: OPEN
- Sources: 14_commands, 12
- Ziel: CI-Basisgates (`lint/test/build`) und optionale Perf-Profile konsistent zwischen Befehlsdoku und Teststrategie halten.
- Scope:
  - command-to-gate mapping table.
  - docs drift checks on CI script changes.
- Akzeptanz:
  - Änderungen an Build/Test-Skripten führen nicht zu Doku-Drift.
- Depends on: TASK-048, TASK-192, TASK-203
- Builder Log:

#### [TASK-206] Operations-Traceability zwischen Commands, API und Architektur schließen
- Status: OPEN
- Sources: 14_commands, ARCHITECTURE, 13
- Ziel: Befehle, Architektur-Abschnitte und API/Runtime-Verträge querverlinken, damit operative Schritte klar fachlich verankert sind.
- Scope:
  - cross-reference matrix for run commands -> affected subsystems.
  - update checklist for operational doc changes.
- Akzeptanz:
  - Betriebsdoku ist vollständig mit Architektur und API-Verträgen verbunden.
- Depends on: TASK-202, TASK-205
- Builder Log:

## 4) Reihenfolge-Empfehlung (praktisch)
1. TASK-001, 004, 013, 014, 020
2. TASK-005, 006, 007, 009, 010
3. TASK-011, 017, 018, 019, 025
4. TASK-033, 036, 037, 023
5. TASK-039, 040, 041, 042, 043, 044
6. TASK-045, 046, 048, 049, 050, 051, 052
7. DEFERRED Tracks: TASK-028, TASK-029 (später)

## 5) Hinweis zu MASTER_SPEC_UNOC_LITE.md
- Empfohlene Aktion jetzt: **behalten + als Archiv markieren**, nicht löschen.
- Empfohlene Aktion später (nach TASK-052): optional löschen oder in `docs/archive/` verschieben.

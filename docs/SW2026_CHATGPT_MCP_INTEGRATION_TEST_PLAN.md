# SW2026 ChatGPT/MCP Integration Test Plan

## Zweck

Dieses Dokument definiert die produktive End-to-End-Abnahme fuer die Integration ChatGPT -> Secure MCP Tunnel -> SolidworksMCP -> SOLIDWORKS 2026. Geprueft wird nicht nur die technische Erreichbarkeit einzelner Tools, sondern ein belastbarer, parametrischer und spaeter editierbarer CAD-Workflow fuer Brettspiel-Inserts.

Der Schwerpunkt liegt auf:

- parametrischer Modellierung statt rein geometrischer Erzeugung,
- stabiler SOLIDWORKS-2026-COM-Integration,
- direkter ChatGPT-MCP-Toolgrenze ohne versteckte Python-Bypaesse,
- semantischer und sitzungsuebergreifender Body-Identitaet,
- reproduzierbarem Verhalten ueber Save/Close/Reopen, MCP-Neustarts und Chat-Sitzungen,
- korrekter Fehlerbehandlung und atomarem Rollback,
- verifiziertem Readback der tatsaechlich erzeugten CAD-Geometrie,
- Multibody-/Scoped-Cut-Sicherheit,
- Transport-, Timeout-, Reconnect- und Idempotency-Robustheit.

---

## Aktueller validierter Ausgangsstand

Stand: 2026-09-13

Repository: `Belegur123123/SolidworksMCP`

Arbeitsbranch: `fix/sw2026-coincident-constraint`

Letzter committed Plan-Stand vor den aktuellen Codefixes: `77cd5d745258b17b8c69ef1e625d61a1c468f03b`

SOLIDWORKS: `SOLIDWORKS Design Premium 2026 SP0.0 / API 34.x`

MCP: `SolidworksMCP 6.5.31`

Tunnel: `openai/tunnel-client 0.0.14`

Aktuell validiert:

- 225 lokale Regressionstests erfolgreich, 0 Fehler, 0 Skips (aktueller Working-Tree-Stand).
- SW2026 Coincident-/SketchPoint-Reacquisition und Dynamic-Dispatch-Pfade live bestaetigt.
- Parametrischer Rechteck-/Extrusions-/Dimensionsaenderungs-Workflow live bestaetigt.
- Semantische Body-Identity-Schicht implementiert und lokal regressionsgetestet.
- Direkte ChatGPT-Sichtbarkeit des aktualisierten 88-Tool-Katalogs wurde in einer laufenden Sitzung bestaetigt.
- `register_body_identity`, `resolve_body_identity`, `list_body_identities`, `semantic_extrude`, `semantic_cut` sind serverseitig und clientseitig vorgesehen.
- `resolve_cut_direction` ist als direktes read-only Tool verfuegbar.
- Live-D2-Referenzfall bestaetigt: semantischer 15-mm-Pocket-Cut auf `body:insert_main`, automatische Materialseite, resultierendes Volumen 109000 mm^3.
- Der saubere Referenzzustand `SolidWorks_MCP_Rectangle_Extrude_Live_Test.SLDPRT` wurde nach dem D2-Test ohne Speichern wiederhergestellt: 19 Features, 1 Sketch, 1 Body, 6 Faces, 208000 mm^3.
- Tunnel-Start wurde gegen Doppelstart/Port-8080-Konflikte gehaertet; Restart stoppt den alten Prozessbaum vor dem Neustart und wartet auf `healthz=200` und `readyz=200`.
- Lange lokale Operationen sollen ueber `execute_python_async` statt synchron ueber die ca. 120-s-Requestgrenze laufen.

Bekannte, noch nicht vollstaendig abgenommene Punkte:

- dreifache Cold-Start-/Session-Rebind-Wiederholung,
- gezielt provozierter semantischer Postcondition-/Identity-Rollback gegen echtes SW2026-COM,
- Multibody-Rehydration nach echtem Tunnel/MCP-Neustart und anschliessender weiterer Scoped Cut,
- Idempotency-Replay nach Reconnect bzw. unsicherem Antwortzustand,
- Live-Retest der korrigierten Dokumentaktivierung sowie reale Konfigurationsisolation,
- kombinierter P1-A/P1-B-Constraint-/Dimensionstest,
- laengere Modellierungssitzung / Stresstest,
- semantische Face-/Edge-Identitaet ist bewusst noch nicht Teil der aktuellen Identity-Schicht.

---

# Teststrategie und Bewertung

Prioritaeten:

- **P0 - Produktionsblocker:** Muss vor allgemeiner produktiver Nutzung bestanden sein.
- **P1 - Funktionsbreite:** Muss fuer typische Insert-Konstruktionen ausreichend abgedeckt sein.
- **P2 - Robustheit/Skalierung:** Belastungs-, Langzeit- und komplexere Geometrietests.

Abschlussklassen:

- **PASS:** alle wesentlichen Sollkriterien geometrisch/topologisch und an der MCP-Grenze bestaetigt.
- **PASS MIT EINSCHRAENKUNG:** Kernfunktion korrekt, nichtkritische Diagnose/Telemetrie unvollstaendig.
- **FAIL - RECOVERED:** Operation fehlgeschlagen, Ausgangszustand vollstaendig verifiziert wiederhergestellt.
- **FAIL - STATE UNKNOWN:** Fehler aufgetreten, Dokumentzustand nicht eindeutig nachgewiesen.
- **FAIL - STATE CORRUPTED:** Restgeometrie, falsche Bodies/Features oder unvollstaendiges Rollback.

Grundregeln fuer jeden Live-Test:

1. Vor CAD-Mutation MCP, Toolkatalog, Runtime und SOLIDWORKS-Umgebung pruefen.
2. Tool-Erfolg allein ist niemals ausreichendes PASS-Kriterium.
3. Nach jeder Mutation Geometrie/Topologie per Readback pruefen.
4. Bei Transport-/Sessionfehlern keine Mutation ueber Ersatzpfade erzwingen.
5. `execute_python` darf fehlende direkte MCP-Tools in Akzeptanztests nicht ersetzen.
6. Keine stillen Geometrie-Workarounds, keine Fix-Constraints als Reparatur.
7. Bei kritischem Fehler sofort stoppen und Dokument-, Sketch-, Feature-, Body- und Transportzustand erfassen.
8. Referenzdateien nicht fuer destruktive Tests verwenden; dafuer explizite Testkopien anlegen.

---

# P0 - Kernintegration und Produktionsabnahme

## P0-A - Parametrisches Rechteck 120 x 80 mm

Vier unabhaengige Linien auf einer Standardebene, vier Coincident-Ecken, Horizontal/Vertical, keine Fix-Constraints, parametrische Lage, Breite 120 mm, Hoehe 80 mm.

PASS: eine geschlossene Kontur, korrekte Maße, Solver plausibel, editierbar, Normal-To/Fit korrekt, kein ActiveSketch-Leak und kein SW2026-Dynamic-Dispatch-Fehler.

**Status:** im Kern live validiert; bei zukuenftigen Codeaenderungen Regression.

## P0-B - Boss-Extrusion

20-mm-Extrusion aus P0-A; Feature Health, Body Count, Bounding Box, Volumen und Save pruefen.

**Status:** live validiert; bei relevanten Codeaenderungen Regression.

## P0-C - Parametrische Aenderung bestehender Dimension

Bestehende Breite 120 -> 130 mm aendern, kein Ersatz-Sketch/Feature; Rebuild und 208000 mm^3 fuer 130 x 80 x 20 mm pruefen.

**Status:** live validiert; bei relevanten Codeaenderungen Regression.

## P0-D - Semantischer Pocket-Cut

Produktionspfad verwenden:

- Body unter `body:insert_main` / `B_insert_main` registrieren oder per `semantic_extrude` erzeugen.
- Face-Sketch als `S_*` benennen.
- `resolve_cut_direction` read-only pruefen.
- `semantic_cut(..., direction_mode="auto_material_side")` verwenden.
- `F_*` Feature, Body-Identity, Feature Health, BBox und Volumen verifizieren.

Referenzfall D2: oberer Face-Sketch, 15-mm-Tiefe, automatische Richtung, erwartetes Endvolumen 109000 mm^3.

**Status:** direkter Live-Pfad bestaetigt.

## P0-E - Cross-Session Save/Close/Reopen/Weiterbearbeiten

Dies ist gegenueber dem alten Plan erweitert und ein Produktionsblocker.

Ablauf:

1. Auf Testkopie einen semantischen Body und mindestens ein parametrisches Feature erzeugen.
2. Datei speichern.
3. Dokument schliessen.
4. MCP/Tunnel vollstaendig neu starten.
5. Eine neue MCP-/ChatGPT-Session herstellen.
6. Datei erneut oeffnen.
7. `list_body_identities` und `resolve_body_identity` ohne alte Session-Registry ausfuehren.
8. Vorhandene Dimension aendern, keinen Ersatz erzeugen.
9. Rebuild und Body-Geometrie pruefen.
10. Einen weiteren `semantic_cut` ausfuehren.
11. Erneut speichern und Reopen-Readback pruefen.

PASS:

- `body:<id>` rehydriert deterministisch ueber den persistierten `B_*`-Namen.
- keine Abhaengigkeit von alten Python-COM-Wrappern oder Runtime-Registry.
- vorhandene Sketches/Features werden weiterbearbeitet, nicht dupliziert.
- Geometrie und Identity bleiben korrekt.

## P0-F - Live-Rollback-Matrix

Mindestens folgende reale Fehlerklassen getrennt auf Testkopien pruefen:

1. widerspruechliche Sketch-Constraints/Dimensionen,
2. von SOLIDWORKS abgelehnte Feature-Erzeugung,
3. nach Feature-Erzeugung verletztes `expected_bbox`,
4. semantische Postcondition-/Identity-Verifikation nach Mutation.

Vor und nach jedem Test erfassen: Feature-/Sketch-/Body-Anzahl, Namen, BBox, Volumen, ActiveSketch, Identity-Mapping und Rollback-Metriken.

PASS:

- Fehler strukturiert klassifiziert,
- bei erfolgreichem Rollback `document_restored=true`,
- bei fehlgeschlagenem Rollback niemals falsches `document_restored=true`,
- keine Restgeometrie, kein Ghost-Feature, kein ActiveSketch-Leak.

## P0-G - Toolkatalog-, Cold-Start- und Session-Rebind-Abnahme

Dieser Test ist neu und prueft die ChatGPT-MCP-Grenze selbst.

Ablauf mindestens 3-mal:

1. Tunnel/MCP vollstaendig beenden.
2. Sicherstellen, dass keine zweite Tunnelinstanz und kein alter stdio-Child uebrig ist.
3. Tunnel kalt starten und `healthz=200`, `readyz=200` abwarten.
4. MCP-Client neu verbinden bzw. neue ChatGPT-Session verwenden, falls der Host Sessions an die alte Verbindung bindet.
5. Clientseitigen Toolkatalog pruefen.
6. Direkten read-only Toolcall (`get_environment_status`, danach `resolve_cut_direction` nur wenn passende Geometrie existiert) ausfuehren.
7. 502/504, `Session terminated`, Initialize-/Tools-Call-Reihenfolge und Tunnel-Log erfassen.

PASS:

- aktueller Toolkatalog direkt sichtbar,
- semantische Tools und `resolve_cut_direction` direkt aufrufbar,
- erster Request nach Cold-Start funktioniert,
- kein `Session terminated`, 502 oder 504,
- keine Python-Bypaesse.

Wenn die laufende ChatGPT-Unterhaltung nach Tunnel-Restart dauerhaft an einer terminierten MCP-Session haengt, ist dies **FAIL - RECOVERED/SESSION REBIND REQUIRED** und muss als Host-/Connector-Lifecycle-Grenze dokumentiert werden. CAD-Mutationen werden in dieser Session nicht fortgesetzt.

## P0-H - Transport-Timeout, Reconnect und Idempotency

Ablauf:

- kurzer synchroner Call als Baseline,
- kontrollierter langer synchroner Call bis zur bekannten Request-Deadline,
- anschliessend normaler read-only MCP-Call,
- derselbe lange Vorgang ueber Async-Job,
- Restart im Leerlauf und nach abgeschlossener Mutation,
- identischen mutierenden Request mit gleichem `idempotency_key` wiederholen,
- Wiederholung nach Reconnect/unsicherem Antwortzustand pruefen.

PASS:

- Timeout zerstoert den Shared-stdio-Pfad nicht dauerhaft,
- Async-Pfad schliesst lange Arbeit erfolgreich ab,
- kein doppelter Sketch/Feature/Body durch Retry,
- Reconnect hinterlaesst keinen unbekannten CAD-Zustand.

---

# P1 - Funktionsbreite fuer Inserts

## P1-A - Kombinierte Constraint-Matrix

Horizontal, Vertical, Midpoint, Equal, Concentric, Tangent, Parallel, Perpendicular, Collinear und Symmetric zunaechst gezielt, danach in mindestens einem realistischen kombinierten Insert-Sketch.

## P1-B - Dimension-Matrix

Horizontale/vertikale Distanz, Linienlaenge, Punkt-Punkt, Radius, Durchmesser und bei Bedarf Winkel. Driving-Status, Namens-/Mapping-Stabilitaet und nachtraegliche Aenderbarkeit pruefen.

## P1-C - Kreise, Boegen und tangentiale Konturen

Mindestens Rechteck mit Fingerzugriff, Kreis-/Bohrungskontur und tangential verbundene Boegen. Selbstueberschneidung, Tangentialitaet und Cut-Tauglichkeit verifizieren.

## P1-D - ActiveSketch-Lifecycle

Mindestens 5 Sketches nacheinander auf unterschiedlichen Ebenen/Flaechen. Keine Mutation eines alten Sketches, keine Namensverwechslung, kein `SKETCH_ACTIVE_STATE_LOST`.

## P1-E/F - Semantischer Multibody + Scoped Cut

Mindestens drei Bodies mit logischen IDs, z. B.:

- `body:tray` -> `B_tray`
- `body:divider` -> `B_divider`
- `body:token_box` -> `B_token_box`

Dann `semantic_cut` nur auf einen Zielbody. Vorher/nachher Volumen und BBox aller Bodies vergleichen. Save/Close/Reopen/MCP-Restart und zweiten Scoped Cut auf anderen Body ausfuehren.

PASS: nur adressierter Body aendert sich, keine Merge-Fehler, alle IDs rehydrieren korrekt.

## P1-G - Dokument- und Konfigurationsisolation

Zwei Parts gleichzeitig mit gleicher logischer ID und anschliessend mindestens zwei SOLIDWORKS-Konfigurationen pruefen. Resolution und Mutation duerfen niemals das falsche Dokument oder die falsche Konfiguration treffen.

## P1-H - Topologieaenderung / funktionale Face-Auswahl

Da semantische Face-/Edge-Identity noch nicht implementiert ist, aktuelle geometrische/ray-basierte Auswahl gezielt gegen Topologieaenderungen testen: Face waehlen, Feature erzeugen, Topologie durch Cut/Fillet aendern, funktional gleiche Flaeche erneut finden und Folgefeature erzeugen.

---

# P2 - Robustheit und Skalierung

## P2-A - Splines/NURBS

Komplexere Freiformgeometrie, Endpoint-Readback, Rebuild, Export und geometrischer Vergleich.

## P2-B - Lange Modellierungssitzung

Mindestens:

- 10 Sketches,
- 50-100 Constraints,
- 30-50 Dimensionen,
- 10-20 Features,
- mehrere Saves/Rebuilds,
- mindestens ein MCP/Tunnel-Reconnect zwischen zwei Bearbeitungsschritten.

Beobachten: `RPC_E_DISCONNECTED`, `DISP_E_MEMBERNOTFOUND`, ActiveSketch-Leaks, UI_BLOCKED, Solver-/Rebuild-Zeit, Rollbacks, Namenskollisionen und Transportfehler.

## P2-C - Sketch-Stresstest

50, 100 und 200 Entities; Solverzeiten, COM-Stabilitaet, vollstaendigen geometrischen Export und Readback dokumentieren.

## P2-D - Realistisches End-to-End-Insert

Ein kleines produktionsnahes Insert mit Grundkoerper, mehreren Taschen, Fingerzugriffen und mehreren Bodies erstellen, spaeter parametrisch aendern, Save/Reopen pruefen und SLDPRT/STEP/STL bzw. 3MF exportieren. Dies ist die finale Nutzbarkeitsabnahme.

---

# Standard-Preflight

Vor jeder CAD-Mutation mindestens pruefen:

- direkter MCP-Call funktioniert,
- korrekter Toolkatalog sichtbar,
- korrekter Branch/Serverstand,
- SOLIDWORKS 2026 SP0.0 / API 34.x,
- `typed_module_available=true`,
- `modeler_available=true`,
- UI=`UI_READY`,
- keine modalen Dialoge,
- aktives Dokument eindeutig,
- kein aktiver unbekannter Transaction-/Sketch-Zustand.

Bei neuem Dokument: vor erster produktiver Geometrie speichern oder explizite Testdatei verwenden.

---

# Standard-Evidenz

Je Test mindestens erfassen:

- exakter relevante Toolcall/Argumente,
- Erfolg oder strukturierter Fehler (`code`, `stage`, `recoverable`, `document_restored`, HRESULT),
- Sketch-/Feature-/Body-Anzahl,
- ActiveSketch,
- Relations/Dimensionen,
- Feature Health/GetFaces,
- BBox und Volumen,
- semantische IDs und Aufloesungsquelle,
- Rebuild-/Rollback-Metriken,
- Save/Reopen-Ergebnis,
- bei Transporttests Tunnel-PID, Health/Ready, Initialize/Tools-Call-Reihenfolge und 502/504/Session-Fehler.

---

# Stop-Bedingungen

Bei kritischem Fehler sofort stoppen. Insbesondere nicht automatisch:

- fehlende MCP-Tools via `execute_python` umgehen,
- bei `Session terminated` CAD-Mutationen ueber eine andere interne Route erzwingen,
- Koordinaten oder Constraints zur Fehlerkaschierung veraendern,
- `fixed` einsetzen,
- Restfeatures manuell reparieren und dann den Test als PASS werten.

Zuerst Zustand und Recovery eindeutig dokumentieren.

---

# Produktive Abnahmekriterien

Die Integration gilt fuer reale Insert-Projekte als produktiv belastbar, wenn mindestens bestanden sind:

- P0-A bis P0-D,
- **P0-E Cross-Session-Persistenz**,
- **P0-F Live-Rollback-Matrix**,
- **P0-G Cold-Start/Session-Rebind**,
- **P0-H Transport/Idempotency**,
- ein kombinierter P1-A/P1-B-Sketch,
- **P1-E/F semantischer Multibody-/Scoped-Cut**,
- mindestens ein Reopen/Restart innerhalb dieses Multibody-Workflows.

P2 ist fuer die erste reale Nutzung kein harter Blocker, sollte aber vor laengerer unbeaufsichtigter oder umfangreicher Seriennutzung bestanden sein.

---

# Naechste Ausfuehrungsreihenfolge

1. **P0-G - aktueller Cold-Start-/Session-Rebind-Status**
2. **P0-E - Cross-Session Save/Close/Reopen/Weiterbearbeiten**
3. **P0-F - Live-Rollback-Matrix**
4. **P1-E/F - semantischer Multibody + Scoped Cut + Reopen**
5. **P0-H - Idempotency unter Reconnect/Timeout**
6. P1-A/B kombinierter Constraint-/Dimensionstest
7. P1-G Dokument-/Konfigurationsisolation
8. P1-H Face-/Topologie-Resilienz
9. P2-D realistisches End-to-End-Insert
10. P2-A/B/C Robustheits- und Stresstests

Nach jedem P0-Test wird das Ergebnis dokumentiert. Ein kritischer P0-Fehler blockiert die nachfolgenden mutierenden Tests, bis der Zustand eindeutig recovered oder die Ursache behoben ist.

---

# Live-Teststatus 2026-09-13 nach Reconnect-Abnahme

## P0-G - Cold-Start / Session-Rebind

**Status: PASS MIT EINSCHRAENKUNG / RECOVERED.**

Nach manuellem Tunnel-Neustart war die zuvor terminierte ChatGPT-MCP-Session wieder direkt nutzbar. `get_environment_status` lief ohne Bypass; UI war `UI_READY`, keine modalen Dialoge. Der direkte Toolkatalog enthielt 88 Tools inklusive aller semantischen Identity-Tools und `resolve_cut_direction`. Die im Plan geforderte dreifache Cold-Start-Wiederholung ist noch offen.

## P0-E - Cross-Session-Persistenz

**Status: PASS.**

Eine vor dem aktuellen MCP-Prozess gespeicherte Datei `IdentityPersistence_01387415.SLDPRT` wurde in einer neuen MCP-Session geoeffnet. `body:insert_main` wurde ohne alte Runtime-Registry aus `B_insert_main` per `canonical_name_inference` / `resolved_by=canonical_name` rehydriert; das gespeicherte Volumen blieb 109000 mm^3. Auf der daraus erzeugten Testkopie `P0E_CrossSession_Continuation.SLDPRT` wurde nach erneutem MCP-Neustart ein weiterer semantisch gescopter 2-mm-Cut `F_crosssession_followup` erzeugt. Das Volumen sank exakt auf 108200 mm^3. Save/Close/Reopen bestaetigte Body-Identity, Feature Health (5 Faces, alive) und Volumen unveraendert.

## P0-F - Live-Rollback-Matrix

**Status: WEITGEHEND PASS; ein semantischer Postcondition-Livefehler bleibt offen.**

Bestaetigte reale Fehlerklassen:

1. `auto_material_side` bei Body-BBox auf beiden Seiten der Skizzenebene: `INVALID_PLAN` vor Mutation.
2. Bewusst falscher `expected_bbox`: realer Cut wurde erzeugt, danach `FEATURE_WRONG_BBOX` erkannt und das Feature wieder geloescht (`feature_deleted=true`); Volumen und Identity blieben unveraendert.
3. Bewusst falsche Cut-Richtung: `FEATURE_CREATE_FAILED` in Stage `create_feature`, kein Ghost-Feature.
4. Widerspruechliche Driving-Dimensionen (10 mm und 20 mm auf derselben Linie): `SKETCH_OVERDEFINED`, `document_restored=true`; Feature-Anzahl, Body, Volumen und Identity blieben unveraendert.

Noch offen: gezielt provozierter semantischer Postcondition-/Identity-Fehler nach echter SW2026-Mutation. Der lokale Regressionstest `test_post_cut_identity_failure_rolls_back_and_rehydrates_identity` ist vorhanden und gruen.

## P1-E/F - Semantischer Multibody / Scoped Cut

**Status: PASS MIT EINSCHRAENKUNG; echter MCP-Restart innerhalb dieses Modells noch offen.**

Testmodell mit drei getrennten semantischen Bodies:

- `body:tray` -> `B_tray`, initial 16000 mm^3,
- `body:divider` -> `B_divider`, initial 6000 mm^3,
- `body:token_box` -> `B_token_box`, initial 12000 mm^3.

Erster `semantic_cut` nur auf `body:tray`: `B_tray` 16000 -> 15600 mm^3; die beiden anderen Bodies blieben exakt unveraendert. Nach Save-As auf einen neuen Dateipfad wurden alle drei IDs mit `source=canonical_name_inference` rehydriert. Zweiter `semantic_cut` nur auf `body:divider`: `B_divider` 6000 -> 5700 mm^3; `B_tray=15600` und `B_token_box=12000` blieben unveraendert. Body Count blieb 3, keine Merge-/Scope-Fehler.

Waehren des Aufbaus wurde einmal ein unbekanntes SOLIDWORKS-Popup erkannt. Es wurde nicht blind bestaetigt. `recover_environment(max_retries=0)` stellte mit Selection-Clear/Freeze-Bar-Check `UI_READY` wieder her; danach lief der Test normal weiter.

## P0-H - Transport / Idempotency

**Status: IN-SESSION IDEMPOTENCY PASS; Reconnect-Replay offen.**

Ein `create_parametric_sketch` mit `idempotency_key=P0H-idem-sketch-top-20260913` wurde zweimal mit identischen Argumenten aufgerufen. Der zweite Aufruf lieferte `idempotent_replay=true` in ca. 32 ms. Feature-/Sketch-Zahl stieg nur einmal (27/5 -> 28/6); kein Duplikat entstand. Der Testsketch wurde anschliessend ohne Speichern verworfen. Die bereits dokumentierte Transportregel bleibt bestehen: lange lokale Arbeit via `execute_python_async`, da synchrone Subprozesse an der Request-Deadline 502 erzeugen koennen, ohne den Shared-stdio-Pfad dauerhaft zu zerstoeren.

## View-/Fit-Verifikation - gefundene und korrigierte Fehler

**Face-Sketch-Fall live PASS nach erstem Fix.** Der reproduzierbare 20x20-mm-Face-Sketch, der vorher nach korrekter Geometrieerzeugung faelschlich an der View-Verifikation scheiterte, bestand nach Neustart. Implementiert wurden `max_center_offset=0.30` und achsenspezifische Clipping-Toleranzen von 1 % der Frame-Dimension.

**Zweiter Fall: schlanker Right-Plane-Sketch.** Live zeigte `ViewZoomtofit2` bereits einen vollstaendig sichtbaren Frame mit `dominant_fill_ratio=0.261347`, `center_offset=0.225023`, `clipped=false`. Die bisherige Mindestfuellung 0.35 erzwang danach eine unnoetige Hochskalierung, die den Sketch aus dem Frame schob. Lokaler Fix: Mindestfuellung auf 0.25 senken, waehrend max. Fuelle 0.90, Center 0.30 und Clipping-Grenzen unveraendert bleiben. Neuer Regressionstest `test_fit_measurement_accepts_visible_slender_quarter_frame` ist gruen. Live-Retest nach MCP-Neustart steht noch aus.

## P1-G - Dokument-/Konfigurationsisolation

**Status Dokumentisolation: FAIL - RECOVERED; Codefix lokal vorhanden. Konfigurations-Livefall offen.**

Zwei Parts wurden gleichzeitig geoeffnet und enthielten dieselbe logische ID `body:tray`, jedoch eindeutig verschiedene Geometrien. Dokument A hatte `B_tray` bei x ca. -60..-20 mm; Dokument B bei x=100..120 mm. Ein direkter `open_document(A)` meldete zwar Erfolg, der anschliessende Identity-Readback lief aber weiterhin gegen Dokument B (`document_key=...p1g_documentisolation_b...`). Ursache: `open_document()` rief nur `OpenDoc6()` auf; fuer bereits geoeffnete Dateien garantiert SOLIDWORKS dadurch keine Aktivierung.

Lokaler Fix: Nach `OpenDoc6()` wird der aktive Dokumentpfad geprueft; bei Abweichung wird `ActivateDoc2` ausgefuehrt und der aktive Pfad erneut verifiziert. Bei verbleibender Abweichung schlaegt `open_document()` fail-closed fehl, statt nachfolgende MCP-Mutationen am falschen Dokument zu riskieren. Zwei Regressionstests decken erfolgreiche Aktivierung und Fail-Closed ab. Der Live-Retest benoetigt einen MCP-Neustart.

## Regression nach aktuellen Codefixes

**225 Tests, 0 Fehler, 0 Skips.**

Die zwei aktuell noch nicht im laufenden MCP-Prozess geladenen Codeaenderungen sind: `min_fill=0.25` fuer sichtbare schlanke Sketches und die verifizierte Dokumentaktivierung in `open_document()`. Beide sind lokal regressionsgetestet; die Live-Abnahme folgt nach dem naechsten MCP/Tunnel-Neustart.

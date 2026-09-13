# SW2026 ChatGPT/MCP Integration Test Plan

## Zweck

Dieses Dokument definiert den geplanten End-to-End-Testablauf für die Integration von ChatGPT, SolidworksMCP und SOLIDWORKS 2026. Ziel ist nicht nur die Prüfung einzelner API-Aufrufe, sondern die belastbare Validierung eines produktiven, parametrischen CAD-Workflows für die spätere Konstruktion von Brettspiel-Inserts.

Der Schwerpunkt liegt auf:

- parametrischer Modellierung statt rein geometrischer Erzeugung,
- stabiler SOLIDWORKS-2026-COM-Integration,
- reproduzierbarem Verhalten über Rebuilds und Sitzungsgrenzen hinweg,
- korrekter Fehlerbehandlung und atomarem Rollback,
- verlässlichem Readback der tatsächlich erzeugten CAD-Geometrie,
- späterer Änderbarkeit bereits erzeugter Modelle.

---

## Aktueller validierter Ausgangsstand

Stand: 2026-09-13

Repository:

`Belegur123123/SolidworksMCP`

Arbeitsbranch:

`fix/sw2026-coincident-constraint`

SOLIDWORKS:

`SOLIDWORKS Design Premium 2026 SP0.0 / API 34.x`

Aktuell validiert:

- 171 lokale Tests erfolgreich.
- Runtime-Signatur von `create_parametric_sketch` entspricht wieder der vollständigen Upstream-Signatur.
- MCP-Dispatch verwirft keine Parameter mehr.
- SW2026-spezifischer Coincident-Fall live bestätigt.
- Coincident wird geometrisch korrekt akzeptiert, auch wenn der RelationManager danach `relation_count = 0` meldet.
- `relations_created = 1` bei geometrisch verschmolzenen Endpunkten live bestätigt.
- SketchPoint-Reacquisition über owning SketchSegment und `com_get(...)` live bestätigt.
- Kein `RPC_E_DISCONNECTED` im finalen Minimaltest.
- Kein `DISP_E_MEMBERNOTFOUND` im korrekten `com_get`-Readback-Pfad.
- ActiveSketch-Lifecycle nach Rebuild live bestätigt.
- Normal-To und Fit-to-Screen erfolgreich.
- Speichern des Testdokuments erfolgreich.
- Kein Rollback im erfolgreichen Minimaltest erforderlich.

Der Minimaltest gilt damit als abgeschlossen. Die folgenden Tests erweitern die Validierung schrittweise vom API-Sonderfall hin zu einem produktiv nutzbaren parametrischen CAD-Workflow.

---

# Teststrategie

Die Tests werden in drei Prioritätsklassen durchgeführt:

- **P0 – Kernintegration:** Muss vor produktiver Nutzung bestanden sein.
- **P1 – Funktionsbreite:** Validiert typische Modellierungsoperationen für Inserts.
- **P2 – Robustheit und Skalierung:** Prüft Stabilität bei größeren Modellen und längeren Sitzungen.

Grundregel für alle Live-Tests:

1. Vor jeder CAD-Mutation Runtime und Umgebung prüfen.
2. Nach jeder Mutation das CAD-Ergebnis geometrisch bzw. topologisch verifizieren.
3. Tool-Erfolg allein ist kein ausreichendes PASS-Kriterium.
4. Bei kritischem Fehler sofort stoppen.
5. Keine stillen Workarounds, keine Fix-Constraints als Ersatz und keine automatische Geometrieänderung, sofern der Test dies nicht explizit vorsieht.
6. Fehlerzustände müssen auf Dokument-, Sketch-, Feature- und Body-Ebene nachkontrolliert werden.
7. Für dynamische SW2026-COM-Endpunkte `com_get(segment, "GetStartPoint2", ...)` bzw. `com_get(segment, "GetEndPoint2", ...)` verwenden; direkte Aufrufe `segment.GetStartPoint2()` / `segment.GetEndPoint2()` sind kein valider Diagnosepfad für Dynamic Dispatch.

---

# P0 – Kernintegration

## P0-A – Parametrisches Rechteck 120 × 80 mm

### Ziel

Validierung einer realistischen parametrischen Skizze mit mehreren aufeinanderfolgenden Constraints, mehreren Coincident-Operationen, Bemaßung, Rebuild und geschlossener Kontur.

### Geometrie

Top Plane, Einheit mm.

Vier unabhängige Linien bilden ein Rechteck mit Sollmaß:

- Breite: 120 mm
- Höhe: 80 mm

Die Linien sollen bewusst als einzelne Segmente erzeugt werden. Die Ecken werden über Constraints verbunden.

### Constraints

Mindestens:

- 4 × Coincident an den vier Ecken
- 2 × Horizontal
- 2 × Vertical

Die Lage soll ohne `fixed` bestimmt werden. Für die Positionierung soll eine parametrische Beziehung verwendet werden, z. B. Mittelpunktbezug, Symmetrie oder geeignete Referenzgeometrie.

### Dimensionen

Mindestens:

- Breite = 120 mm
- Höhe = 80 mm

### PASS-Kriterien

- `create_parametric_sketch` erfolgreich.
- 4 Segmente erzeugt.
- Alle vier Ecken geometrisch geschlossen.
- Genau 1 geschlossene Kontur.
- Keine unerwarteten offenen Endpunkte.
- Keine Fix-Constraints.
- Maße 120 × 80 mm im Readback bestätigt.
- Keine `SKETCH_CONSTRAINT_UNVERIFIED`.
- Kein `RPC_E_DISCONNECTED`.
- Kein ActiveSketch-Lifecycle-Fehler.
- Normal-To erfolgreich.
- Fit-to-Screen erfolgreich.
- Sketch bleibt editierbar und parametrisch.

### Besonders zu beobachten

- Verhalten nach mehreren aufeinanderfolgenden Coincident-Operationen.
- Reacquisition der SketchPoints nach jeder Topologieänderung.
- RelationManager Count gegenüber geometrischem Readback.
- Solverstatus nach vollständiger Constraint-/Dimensionierungsfolge.

---

## P0-B – Boss-Extrusion des Rechtecks

### Ziel

Validierung des vollständigen Sketch→Feature→Body-Pfads.

### Ausgangszustand

Erfolgreicher P0-A-Sketch.

### Operation

Mit `advanced_extrude`:

- Tiefe: 20 mm
- 1 Solid Body erwartet

### Erwartete Geometrie

Soll-Bounding-Box ungefähr:

- 120 mm × 80 mm × 20 mm

Soll-Volumen:

`120 × 80 × 20 = 192000 mm³`

### PASS-Kriterien

- Extrusion erfolgreich.
- Feature besitzt Flächen (`GetFaces > 0`).
- Feature nicht suppressed.
- Genau 1 Solid Body.
- Bounding Box innerhalb sinnvoller numerischer Toleranz.
- Volumen innerhalb sinnvoller numerischer Toleranz.
- Keine unerwarteten Bodies.
- Keine tote oder leere Feature-Geometrie.
- Save erfolgreich.

---

## P0-C – Parametrische Änderung eines bestehenden Maßes

### Ziel

Nachweis, dass ChatGPT nicht nur Modelle erzeugen, sondern bestehende parametrische Modelle korrekt ändern kann.

### Ausgangszustand

Erfolgreiches Modell aus P0-B.

### Änderung

Breite ändern:

- vorher: 120 mm
- nachher: 130 mm

Die vorhandene Dimension muss geändert werden. Es darf kein neues Rechteck und kein Ersatzfeature erzeugt werden.

### Erwartetes Ergebnis

Sketch:

- Breite = 130 mm
- Höhe = 80 mm

Solid:

- ungefähr 130 × 80 × 20 mm

Soll-Volumen:

`130 × 80 × 20 = 208000 mm³`

### PASS-Kriterien

- vorhandene Dimension geändert, nicht ersetzt.
- Rebuild erfolgreich.
- vorhandene Extrusion bleibt dasselbe Feature.
- Body-Anzahl unverändert.
- neue Bounding Box korrekt.
- neues Volumen korrekt.
- keine zusätzlichen Sketches oder Features.
- Save erfolgreich.

---

## P0-D – Tasche auf Oberseite eines Insert-Grundkörpers

### Ziel

Validierung eines typischen Brettspiel-Insert-Workflows.

### Ausgangsgeometrie

Grundkörper:

- 120 × 80 × 20 mm

### Tasche

Auf der Oberseite:

- 100 × 60 mm
- Tiefe: 15 mm

Erwartete Geometrie:

- umlaufender Rand: 10 mm
- verbleibende Bodenstärke: 5 mm

### Operationen

1. obere planare Fläche identifizieren.
2. Sketch auf dieser Fläche erzeugen.
3. parametrisches Innenrechteck erzeugen.
4. `advanced_cut` mit 15 mm Tiefe ausführen.

### PASS-Kriterien

- richtige Fläche verwendet.
- Sketch auf der richtigen Fläche.
- Tasche 100 × 60 mm.
- Tiefe 15 mm.
- Bodenstärke 5 mm.
- Außenmaße bleiben unverändert.
- genau 1 Solid Body.
- Feature gesund.
- kein Durchbruch durch den Boden.
- Save erfolgreich.

---

## P0-E – Save → Close → Reopen → Weiterbearbeiten

### Ziel

Validierung der Persistenz über Sitzungs- und COM-Wrapper-Grenzen hinweg.

### Ablauf

1. Modell aus P0-D speichern.
2. Dokument schließen.
3. Dokument erneut öffnen.
4. Sketches, Dimensionen und Features nur anhand gespeicherter CAD-Struktur wiederfinden.
5. vorhandene Dimension erneut ändern.
6. Rebuild ausführen.
7. Body-Geometrie verifizieren.
8. erneut speichern.

### Beispieländerung

Breite z. B.:

- 130 mm → 125 mm

### PASS-Kriterien

- Datei korrekt erneut geöffnet.
- Feature-/Sketch-Namen vorhanden.
- Dimension wiedergefunden.
- keine Abhängigkeit von alten Python-COM-Wrappern.
- Änderung wirkt auf vorhandenes Modell.
- Body-Geometrie nach Rebuild korrekt.
- keine Dubletten.
- Save erfolgreich.

### Bedeutung

Dieser Test ist für die reale ChatGPT-Nutzung besonders wichtig, da spätere Änderungen typischerweise in einer neuen Chat-/Server-/SOLIDWORKS-Sitzung erfolgen.

---

## P0-F – Atomarer Fehler- und Rollback-Test

### Ziel

Nachweis, dass fehlgeschlagene Modellierungsoperationen keinen beschädigten oder halbfertigen CAD-Zustand hinterlassen.

### Fehlerfall

Gezielt widersprüchliche Constraints oder Dimensionen erzeugen, z. B. eine Geometrie gleichzeitig auf inkompatible Breiten festlegen.

### PASS-Kriterien

- Operation schlägt kontrolliert fehl.
- strukturierter Fehlercode vorhanden.
- Fehlerstage korrekt klassifiziert.
- `document_restored = true`, sofern Mutation begonnen hatte.
- Rollback metrisch erfasst.
- kein zusätzlicher Sketch verbleibt.
- keine halbfertigen Dimensionen verbleiben.
- kein unerwartetes Feature verbleibt.
- kein zusätzlicher Body verbleibt.
- kein ActiveSketch-Leak.
- Dokumentzustand entspricht dem Zustand vor dem Test.

---

# P1 – Funktionsbreite

## P1-A – Constraint-Matrix

### Ziel

Validierung der wichtigsten Constraint-Typen für Insert-Konstruktionen.

Priorität:

1. Horizontal
2. Vertical
3. Midpoint
4. Equal
5. Concentric
6. Tangent
7. Parallel
8. Perpendicular
9. Collinear
10. Symmetric

### Vorgehen

Nicht nur isolierte Einzelfälle testen. Zusätzlich mindestens einen kombinierten Sketch verwenden, in dem mehrere Constraint-Typen zusammenwirken.

### PASS-Kriterien

- jeder Constraint-Typ geometrisch verifiziert.
- kein stiller No-op.
- keine falsche Erfolgsmeldung aufgrund ungeeigneter RelationManager-Zählung.
- Solverstatus plausibel.
- Readback nach Rebuild stabil.

---

## P1-B – Dimension-Matrix

### Ziel

Validierung verschiedener Bemaßungsarten.

Zu prüfen:

- horizontale Distanz
- vertikale Distanz
- Linienlänge
- Abstand Punkt–Punkt
- Radius
- Durchmesser
- Winkel, sofern produktiv benötigt

### PASS-Kriterien

- Sollwert nach Erzeugung korrekt.
- Dimension ist driving, sofern vorgesehen.
- Änderbarkeit nachträglich bestätigt.
- Rebuild aktualisiert Geometrie korrekt.
- Dimension-Name/Mapping stabil.

---

## P1-C – Kreis-, Bogen- und tangentiale Konturen

### Ziel

Validierung typischer Insert-Aussparungen und Fingerzugriffe.

Beispiel:

- Rechteck mit halbkreisförmigem Fingerzugriff
- Kreisbohrung/Aussparung
- tangential verbundene Bögen

### PASS-Kriterien

- Kreise/Bögen geometrisch korrekt.
- Tangentialität verifiziert.
- Radius-/Durchmessermaße korrekt.
- Kontur für Extrusion/Cut gültig.
- keine unerwarteten Selbstüberschneidungen.

---

## P1-D – Mehrere aufeinanderfolgende Sketches

### Ziel

Validierung des ActiveSketch-Lifecycles bei mehreren Features.

### Szenario

Mindestens 5 Sketches nacheinander auf unterschiedlichen Ebenen bzw. Flächen erzeugen und verwenden.

### PASS-Kriterien

- immer der richtige Sketch aktiv bzw. ausgewählt.
- keine Mutation eines vorherigen Sketches.
- keine Sketch-Namensverwechslung.
- Normal-To/Fill funktionieren jeweils.
- kein `SKETCH_ACTIVE_STATE_LOST`.

---

## P1-E – Mehrkörper-Part

### Ziel

Validierung einer Insert-Architektur mit mehreren Bodies.

Beispiel:

- `Body_Tray`
- `Body_Divider`
- `Body_TokenBox`

### PASS-Kriterien

- jeder Body getrennt vorhanden.
- Body-Namen stabil.
- keine unbeabsichtigten Merge-Vorgänge.
- Bounding Box und Volumen pro Body plausibel.

---

## P1-F – Scoped Cut im Multibody-Part

### Ziel

Prüfung, dass ein Cut nur den explizit gewünschten Body verändert.

### PASS-Kriterien

- `scope_bodies` wirkt korrekt.
- nur Zielbody verliert Volumen.
- andere Bodies behalten identisches Volumen und Bounding Box.
- keine unerwarteten Body-Merges.

---

## P1-G – Idempotency

### Ziel

Validierung wiederholter identischer ChatGPT-/MCP-Aufrufe.

### PASS-Kriterien

- identischer Request mit gleichem `idempotency_key` erzeugt keine Dubletten.
- keine zusätzliche Geometrie.
- kein zusätzlicher Sketch.
- kein zusätzliches Feature.
- Resultat eindeutig als Replay erkennbar, sofern unterstützt.

---

# P2 – Robustheit und Skalierung

## P2-A – Komplexere Splines/NURBS

### Ziel

Validierung komplexerer Freiformgeometrie.

### PASS-Kriterien

- stabile Erzeugung.
- Endpoint-Readback stabil.
- kein `RPC_E_DISCONNECTED`.
- Rebuild stabil.
- Export/Readback stimmt geometrisch.

---

## P2-B – Lange Modellierungssitzung

### Ziel

Erkennung von COM-Lifetime-, ActiveSketch- oder Ressourcenproblemen.

### Beispielumfang

- mindestens 10 Sketches
- 50–100 Constraints
- 30–50 Dimensionen
- 10–20 Features
- mehrere Saves
- mehrere Rebuilds

### Zu beobachten

- COM-Fehler
- `RPC_E_DISCONNECTED`
- `DISP_E_MEMBERNOTFOUND`
- ActiveSketch-Leaks
- UI_BLOCKED
- steigende Solver-/Rebuild-Zeit
- unerwartete Rollbacks
- Namenskollisionen

---

## P2-C – Sketch-Stresstest

### Ziel

Prüfung der praktischen Nutzbarkeit größerer parametrischer Sketches.

### Größenordnung

Schrittweise steigern:

- 50 Entities
- 100 Entities
- 200 Entities

### PASS-Kriterien

- keine unkontrollierten Timeouts.
- keine COM-Abbrüche.
- Solverzeiten dokumentiert.
- geometrischer Export vollständig.
- Readback stabil.

---

# Empfohlene Ausführungsreihenfolge

Die nächsten Live-Tests sollen in folgender Reihenfolge durchgeführt werden:

1. **P0-A – Parametrisches Rechteck 120 × 80 mm**
2. **P0-B – 20-mm-Boss-Extrusion**
3. **P0-C – Breite 120/130 mm parametrisch ändern**
4. **P0-D – 100 × 60 × 15-mm-Tasche erzeugen**
5. **P0-E – Save → Close → Reopen → Maß erneut ändern**
6. **P0-F – Fehler- und Rollback-Test**
7. P1-A bis P1-G
8. P2-A bis P2-C

P0-A und P0-B können in einem gemeinsamen Live-Test durchgeführt werden, solange der Sketch vor der Extrusion vollständig verifiziert wird und bei Sketch-Fehlern nicht weitergearbeitet wird.

---

# Standard-Preflight für jeden Live-Test

Vor CAD-Mutation prüfen:

- MCP verbunden.
- korrekter Branch/Serverstand geladen.
- Runtime-Signatur des relevanten Tools plausibel.
- SOLIDWORKS 2026 SP0.0 / API 34.x.
- `typed_module_available = true`.
- `modeler_available = true`.
- UI state = `UI_READY`.
- keine modalen Dialoge.
- aktives Dokument eindeutig bestimmt.

Wenn ein Test auf einem neuen Dokument basiert:

- Dokument speichern, bevor die erste Geometrie erzeugt wird.
- initiale Sketch-/Body-/Feature-Anzahl dokumentieren.

---

# Standard-Evidenz je Test

Mindestens erfassen:

- exakter Tool-Aufruf / wesentliche Argumente
- Erfolg/Fehler
- strukturierter Fehlercode bei Fehler
- `stage`
- `recoverable`
- `document_restored`
- COM HRESULT, falls vorhanden
- Entities/Relations/Dimensions/Features erzeugt
- Rebuild Count
- Solver Time
- Phase Timings, falls verfügbar
- Sketch Count
- ActiveSketch-Status
- Solid Body Count
- Bounding Box
- Volumen bei Solid-Tests
- Feature Health (`GetFaces`)
- Save-Ergebnis
- Rollback Count

Bei parametrischer Geometrie zusätzlich:

- CAD-Readback der relevanten Koordinaten
- Dimensionen
- Constraint-/Topologiezustand
- Vergleich Soll/IST

---

# Stop-Bedingungen

Bei einem kritischen Fehler sofort stoppen.

Nicht automatisch:

- Koordinaten verändern,
- zusätzliche Constraints hinzufügen,
- `fixed` einsetzen,
- Ersatzgeometrie erzeugen,
- ein fehlerhaftes Feature manuell reparieren,
- den nächsten Testschritt ausführen.

Vor weiterer Arbeit zuerst den Fehlerzustand dokumentieren und prüfen:

- aktueller Dokumentzustand,
- ActiveSketch,
- Sketch-Anzahl,
- Feature-Anzahl,
- Body-Anzahl,
- Rollback-Ergebnis.

---

# Bewertungssystem

Jeder Test erhält eine Abschlussklassifikation:

- **PASS:** Alle wesentlichen Sollkriterien live und geometrisch/topologisch bestätigt.
- **PASS MIT EINSCHRÄNKUNG:** Kernfunktion korrekt, aber nichtkritische Telemetrie oder Diagnose unvollständig.
- **FAIL – RECOVERED:** Operation fehlgeschlagen, Dokument vollständig und verifiziert zurückgerollt.
- **FAIL – STATE UNKNOWN:** Fehler aufgetreten und Dokumentzustand nicht eindeutig verifiziert.
- **FAIL – STATE CORRUPTED:** Unerwartete Restgeometrie/Features/Bodies oder nicht vollständig zurückgerollter Zustand.

---

# Abnahmekriterium für produktive Insert-Modellierung

Die Integration gilt für den Kernworkflow als produktiv belastbar, wenn mindestens folgende Tests vollständig bestanden sind:

- P0-A parametrisches Rechteck
- P0-B Extrusion
- P0-C nachträgliche Maßänderung
- P0-D Tasche/Cut auf Fläche
- P0-E Save/Close/Reopen/Weiterbearbeiten
- P0-F atomarer Rollback

Zusätzlich sollte vor umfangreicher Nutzung mindestens ein kombinierter P1-Constraint-/Dimensionstest sowie ein Multibody-/Scoped-Cut-Test bestanden sein.

---

# Nächster geplanter Test

**P0-A + P0-B kombiniert:**

1. Neues Part.
2. Parametrisches Rechteck 120 × 80 mm auf Top Plane.
3. Vier Coincident-Ecken.
4. Horizontal-/Vertical-Constraints.
5. Breiten-/Höhendimensionen.
6. Geometrie und geschlossene Kontur verifizieren.
7. Nur bei vollständigem PASS: 20-mm-Boss-Extrusion.
8. Feature Health, Body Count, Bounding Box und Volumen prüfen.
9. Speichern.
10. Stoppen und Ergebnis berichten, bevor P0-C begonnen wird.

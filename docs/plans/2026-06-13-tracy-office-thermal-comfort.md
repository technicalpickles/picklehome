# Tracy's office thermal comfort: findings and plan

**Date:** 2026-06-13
**Status:** research complete, no fixes applied yet
**Scope agreed:** cheap/no-install fixes plus better use of the existing Ecobee SmartSensor (no mid-tier equipment, no structural work for now)

## The room

Tracy's office is a converted carport on the downstairs Ecobee zone:

- Concrete slab on grade (uninsulated)
- Floor-to-ceiling **east-facing** glass
- A supply register cut into brick that blows directly on her back

## What the data actually says

Pulled from `just climate-history --thermostat downstairs --days 7` (Ecobee `runtimeReport`).

**Summer / cooling season (current):** the room *overheats*, it does not run cold.

| | Downstairs thermostat | Tracy's office |
|---|---|---|
| Overnight (empty) | 71.6–74.2°F | tracks the house, 71–74°F |
| 9am–1pm (occupied) | steady ~72–73°F | **spikes to 77–82°F, peak 82.3°F** |
| Empty day (6/11) peak | — | 75.6°F |
| Occupied days (6/12, 6/13) peak | — | 82.6 / 82.3°F |

So: ~3°F above the house even when empty (slab/envelope), spiking to **8–9°F above** during her morning work hours. The 9am–1pm timing is textbook **east solar gain** (morning sun off that wall; gone by 2pm). Her body + computer load adds the rest.

**Why "too hot" and "too cold/drafty" are both true:** the AC register dumps cold supply air on her back (localized cold draft) while the room around her bakes from solar gain the central AC can't overcome (globally hot room). Different mechanisms, both real.

**Winter / heating season:** the cold-and-drafty complaint is **radiant loss**, not air temperature: skin radiates toward the cold glass, and the uninsulated slab is a cold radiative floor.

**The thermostat is blind to all of this:** it reads 72.5°F at its own location and cools to setpoint while her room is 80+. Her SmartSensor is not participating in the active cooling comfort profile.

## What the research found

Multi-source pass (DOE/PNNL, LBNL, CBE Berkeley/ASHRAE 55, Energy Vanguard, GreenBuildingAdvisor), 25 claims verified, 0 refuted.

### 1. Block the east sun before it hits the glass (highest leverage)

Exterior shading beats interior shading by **2–4x**, because once sunlight passes the glass it is already heat inside the room; interior shades can only re-radiate it back out.

- Same screen: **46% heat blocked mounted outside vs 14% inside** (PNNL, citing Brunger 1999; note: insect-screen figures).
- Heat-wave study: exterior shades cut dangerous-heat hours **55%**, interior roller shades only **18%**, insulating interior shades **23%**.
- DOE summer shading priority ranks **east/west windows #2** (after skylights, which this room doesn't have), so her glass is the top applicable target.
- **For east specifically:** low morning sun is nearly horizontal, so awnings/overhangs (great for high south sun: 65–77% there) help little. Use a **vertical exterior solar screen** sized for E/W; it keeps the view and diffuse daylight.
- **Cheapest no-install fallback:** interior **cellular/honeycomb shades**, up to 60% solar reduction *with a tight, sealed-edge fit*. Weaker than exterior but renter-grade easy.

### 2. Put a small fan on her (cheapest high-impact fix)

A personal/circulation fan gives **~4°F of perceived cooling** at desk speed; chamber studies found people comfortable **6–11°F warmer** with fan air than still air. Her overheat is 8–9°F, so this is in range, and it works **without lowering the whole-house setpoint**. Aim near her head/upper body. Bonus: mixing the stratified hot layer also makes her sensor read closer to reality.

_Caveat:_ the 4°F is approximate (ASHRAE's elevated-air-speed model may overstate it; some studies used heat-acclimatized subjects). Direction solid, exact degrees fuzzy.

### 3. Deflect the register, do NOT close it

Redirect the cold supply off her back with a **vent deflector**. Do not seal the register: on a single-zone central system, closing it raises duct static pressure past design (~0.5 iwc), can **freeze the evaporator coil and kill the compressor**, increases duct leakage, and doesn't reliably save energy (Energy Vanguard, GreenBuildingAdvisor both: "don't"). A deflector that redirects (not seals) is the safe version and pairs with the fan.

### 4. Ecobee SmartSensor: monitor and trigger, don't control

Adding her hot sensor to the occupied **cooling** comfort profile backfires: Ecobee controls to the *average* of participating sensors, so an 80°F room pulls the control temp up, runs the AC harder, **overcools the rest of the house and worsens her draft**, while the AC still can't beat the solar load. Leave it out of the cooling profile. Better: use the sensor for **visibility and automation triggers** (e.g. drive a fan/smart plug off "Tracy Office > 76°F during work hours") rather than dragging the central system into an unwinnable fight. A cheap smart vent is a possible middle ground but carries the same static-pressure risk as #3, so it's lower priority.

### 5. Winter (separate problem, separate fixes)

LBNL heating-comfort priorities: reduce cold radiative surfaces (cold floors especially, plus large glass) and **heat at foot level** ("providing heat to the foot area is the most effective use of local control"). Practically: **area rug + insulating pad** over the slab, and a small foot-level heater. _Caveat:_ the principle is well-verified, but no specific "rug = X°F warmer" number survived verification.

## Recommended order of operations

Each item is tracked in taskwarrior (`project:picklehome.climate*`); UUIDs cited so they survive ID reuse.

1. **Fan on her desk** (today, ~$30, cancels most of the overheat) — task `f8e4746f`
2. **Exterior solar screen on the east glass** (the real fix; interior cellular shades if exterior isn't feasible) — task `3eecf3b8`
3. **Vent deflector** to get the draft off her back — task `a78610fb`
4. **Drop the whole-zone setpoint compensation** once 1–3 are in — task `b883f3fb`; and **repurpose her sensor as a monitor/automation trigger** — task `19803137`
5. **Winter:** rug + pad + foot-level heat — task `0df75ea9`

Related backlog: sensor participation is API-writable and wants a guarded command to enroll/remove a remote sensor per climate (task `3f72e752`); `climate-history`'s date window is filtered in UTC, not local time, so hourly rows are offset (task `bdcab9b7`); follow up with Tracy on comfort after the earlier ceiling change (task `4acc8608`).

## Open questions

- How exterior vertical screens compare for *low-angle east* sun specifically (clean numbers are south/west).
- Whether the Ecobee API exposes the sensor-participation toggle in a way usable for automation (vs only for thermostat control). README notes the `program.climates[].sensors` array is writable, so participation is settable; the open part is driving an external action (fan/plug) off the reading.
- Whether cheap smart vents improve flow to the room without tripping the coil-freeze/leakage risk, and at how many throttled vents risk begins.

## Sources

- DOE/PNNL Building America Solution Center: [window attachments solar control](https://basc.pnnl.gov/resource-guides/window-attachments-solar-control-and-energy-efficiency), [shading and solar control](https://basc.pnnl.gov/resource-guides/shading-and-solar-control-windows-and-skylights)
- DOE Energy Saver: [energy-efficient window coverings](https://www.energy.gov/energysaver/energy-efficient-window-coverings)
- LBNL: [comfort and HVAC design report (LBNL-6131E)](https://eta-publications.lbl.gov/sites/default/files/lbnl-6131e.pdf)
- CBE Berkeley fans guidebook: [elevated air speed and thermal comfort](https://cbe-berkeley.gitbook.io/fans-guidebook/full-guidebook/elevated-air-speed-and-thermal-comfort)
- Energy Vanguard: [closing HVAC vents](https://www.energyvanguard.com/blog/can-you-save-money-by-closing-hvac-vents-in-unused-rooms/)
- GreenBuildingAdvisor: [closing AC vents](https://www.greenbuildingadvisor.com/article/is-it-ok-to-close-air-conditioner-vents-in-unused-rooms), [comfort problems related to radiation](https://www.greenbuildingadvisor.com/article/comfort-problems-related-to-radiation)

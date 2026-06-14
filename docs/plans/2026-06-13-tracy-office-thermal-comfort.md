# Tracy's office thermal comfort: findings and plan

**Date:** 2026-06-13 (fan approach added 2026-06-14)
**Status:** research complete; fan approach decided (existing circulator + Hue plug + schedule), nothing deployed yet
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

### 4. Ecobee SmartSensor: a data point, not a control lever

The sensor stays purely a **data point**, for visibility and to confirm whether the fixes above are working (it's how the overheat was found in the first place). It is explicitly **not** used to address temperature:

- **Not for thermostat control.** Adding her hot sensor to the occupied cooling comfort profile backfires: Ecobee controls to the *average* of participating sensors, so an 80°F room pulls the control temp up, runs the AC harder, **overcools the rest of the house and worsens her draft**, while the AC still can't beat the solar load. Leave it out of the cooling profile.
- **Not as an automation trigger.** No driving a fan, vent, or smart plug off its reading. The fixes are the physical ones above; the sensor just tells us if they helped.

(A cheap smart vent was considered as a middle ground but carries the same static-pressure risk as #3 *and* would be using the room reading to push conditioning, so it's out of scope.)

### 5. Winter (separate problem, separate fixes)

LBNL heating-comfort priorities: reduce cold radiative surfaces (cold floors especially, plus large glass) and **heat at foot level** ("providing heat to the foot area is the most effective use of local control"). Practically: **area rug + insulating pad** over the slab, and a small foot-level heater. _Caveat:_ the principle is well-verified, but no specific "rug = X°F warmer" number survived verification.

## Recommended order of operations

Each item is tracked in taskwarrior (`project:picklehome.climate*`); UUIDs cited so they survive ID reuse.

1. **Vortex circulator on a scheduled Hue plug** — existing fan found, resume-verified, parked on LOW; add a Hue Smart Plug and schedule it for the morning solar window. Tasks `f8e4746f` (place fan), `7518ca0c` (buy plug), `174ada3d` (schedule). Detail: [Fan: chosen approach and schedule](#fan-chosen-approach-and-schedule).
2. **Exterior solar screen on the east glass** (the real fix; interior cellular shades if exterior isn't feasible) — task `3eecf3b8`
3. **Vent deflector** to get the draft off her back — task `a78610fb`
4. **Drop the whole-zone setpoint compensation** once 1–3 are in — task `b883f3fb`. Her sensor stays a **monitoring data point only**: no thermostat control, no temperature-driving automation.
5. **Winter:** rug + pad + foot-level heat — task `0df75ea9`

Related backlog: `climate-history`'s date window is filtered in UTC, not local time, so hourly rows are offset (task `bdcab9b7`); follow up with Tracy on comfort after the earlier ceiling change (task `4acc8608`).

## Fan: chosen approach and schedule

A second research pass (CBE Berkeley / ASHRAE-55, peer-reviewed draft studies, measured fan testing) settled the fan choice.

### Why a vortex circulator, run on LOW

- **Type:** a vortex **air circulator** (Vornado/TurboForce-style), not a tower fan. It genuinely *mixes* the room (air bounces off walls/ceiling and breaks up the hot stratified layer); a tower fan just pushes a directed stream and doesn't destratify well. The circulator's tilt covers both modes: low speed = gentle whole-room mixing, tilt + higher speed = aimed at her on demand.
- **Run it on LOW.** A controlled study (Griefahn 2001) confirms the same airflow feels like an unpleasant draft when the room is cooler. Low speed keeps occupied-zone air velocity down, which is what avoids recreating her cold-draft-on-the-back complaint.
- **Science:** ~0.5 m/s of air movement ≈ 4°F of perceived cooling by *widening the comfort zone*, and it only helps when she's warm. That is exactly why this runs on a **time schedule tied to the morning solar window**, not all day, running it in a cool afternoon room would just feel like a draft.
- **Noise is a non-issue:** domestic fans run 30–70 dBA, a small room never needs max speed, and a circulator on low sits in the quiet "refrigerator hum" range.

### The fan itself (no purchase)

An existing vortex circulator was found. The make-or-break property for the smart-plug path, **does it resume running when power is restored?**, was tested (unplug, wait, replug) and it **passed**: it spins back up on its own. It has a mechanical switch, so leaving the dial parked on LOW means the Hue plug can do all the on/off. Clean the grille/blades before it goes in (dust cuts airflow and can smell when the motor warms).

### Placement and aim

Room orientation (from her seat): the **big window wall (hot glass) is on her left**, the **vent/shelving is directly at her back** (blowing onto her), she **faces the exterior windowed door on her right**. So the only safe high-velocity zone is up at the window wall, as far from her back as the room allows.

- **Primary: top-right corner** (window wall meets exterior-door wall), aimed **left, along the window wall**, tilted **up ~15–30°**, on **LOW**. This washes the hot glass end-to-end, runs the strong air up at the window away from her, and the gentle return loops down the far (vent) wall, entraining the cold supply instead of letting it jet her back.
- **Backup: top-left corner**, aimed **right along the glass** (output pointed away from her, since this corner is near her back-left).
- It can sit on a **low shelf** if floor space is tight, as long as it tracks the glass and isn't aimed at her.

**Hard avoid:** the vent/left wall or anything aimed at her back (doubles the AC draft); high speed (small room). Bottom-right is unavailable (house-door swing + printer). Treat the corner as a starting point and let her nudge/re-tilt it over a few mornings, felt result beats the diagram.

### Control: Hue Smart Plug, not Caséta

Caséta has no good indoor plug for a fan: its only indoor plug-in is the **PD-3PCL lamp *dimmer*** (never put a fan motor on a dimmer), and its on/off plug (PD-15OUT) is an outdoor weatherproof brick. The **Philips Hue Smart Plug** (US 552349) is the fit: simple on/off relay, 15A/1800W (a circulator's ~30–60W is trivial), Zigbee via the existing Hue bridge, and it enrolls as an on/off "light" so `just hue on/off "<name>"` controls it directly. Stays local, stays in the existing stack.

> Note: the Hue plug's "power-loss recovery" setting governs the *plug* after a blackout, not the fan. The fan-side resume (verified above) is the property that actually matters for daily scheduling.

### Schedule design (sketch, implement once the plug is in: task `174ada3d`)

Target window: **fan on ~08:30, off ~13:30, Mon–Fri** (her work hours, matching the measured 9am–1pm solar spike with a little lead-in). Weekday-only because the point is her occupied comfort. Window timing should be refined against the sensor history once the `climate-history` UTC offset (task `bdcab9b7`) is sorted, since the exact clock hours may shift an hour.

Command shape is just `just hue on "Tracy Office Fan"` / `just hue off "Tracy Office Fan"` (the plug, named in the Hue app). Two ways to drive it on picklelab, modeled on `homelab/services/climate-auto-switch/`:

- **Two systemd timers (simplest):** an `on` service at `OnCalendar=Mon..Fri 08:30` and an `off` service at `OnCalendar=Mon..Fri 13:30`, both `Persistent=true` so a reboot inside/after the window still lands the fan in the right state. Adequate for a fan; the only gap is no same-day retry if a single `hue` call fails (bridge briefly unreachable).
- **Idempotent reconciler (matches climate pattern):** one oneshot run every 15 min (`OnCalendar=*:0/15`, like climate-auto-switch) that computes desired state from the current time/day and sets the plug. Self-healing after reboots and transient failures, at the cost of redundant (harmless) on/off commands.

Recommendation: start with the **two-timer** version (it's a fan, simplicity wins); upgrade to the reconciler only if a missed morning actually happens.

### Fan research sources

- CBE Berkeley fans guidebook: [elevated air speed and thermal comfort](https://cbe-berkeley.gitbook.io/fans-guidebook/full-guidebook/elevated-air-speed-and-thermal-comfort), [design goals and fan selection](https://cbe-berkeley.gitbook.io/fans-guidebook/practitioner-summary/design-goals-and-fan-selection)
- Griefahn et al. 2001, *Applied Ergonomics* (draught annoyance vs velocity/temperature): [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0003687001000102)
- Vornado 660 (no timer, no oscillation, push-button): [CHOICE lab data](https://www.choice.com.au/products/home-and-living/cooling/fans/vornado-whole-room-air-circulator-660)
- Smart-plug auto-resume gotcha: [HowToGeek](https://www.howtogeek.com/258757/not-all-appliances-work-with-smart-outlets.-heres-how-to-know/)
- Hue Smart Plug specs: [Best Buy Q&A](https://www.bestbuy.com/site/questions/philips-hue-smart-plug-white/6367452); Caséta PD-3PCL lamp dimmer: [Lutron](https://support.lutron.com/us/en/product/casetawireless/article/product-selection/Caseta-Plug-In-Lamp-Dimmer-PD-3PCL)

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

# Rain Garden Advisor — API Samples for Design

Companion to `DESIGN_SPEC.md`. Gives Claude Design **real data to design
against** instead of lorem: the exact `POST /chat` response shape, four
representative states, and a full example conversation. All shapes are taken
verbatim from `app.py` (`ChatResponse`) and `tools.py` (tool outputs); the
numbers are computed with the real formulas (`src/rain_garden/sizing.py`) so
they're internally consistent.

---

## 1. What the UI actually renders

The endpoint is `POST /chat`, **client-stateless**: the browser holds the whole
`messages` transcript and resends it every turn. But for *design* purposes, the UI
only ever reads these fields of the response:

| Field | Type | Drives |
|---|---|---|
| `status` | `awaiting_user` \| `complete` \| `address_not_found` \| `out_of_region` \| `error` | Whether to show the input box, the results screen, or an error/redirect. `address_not_found` = geocode miss; `out_of_region` = resolved but outside lower-48 (two distinct Address error screens) |
| `outcome` | `null` \| `"plan"` \| `"plan_not_recommended"` \| `"declined"` | **Which terminal screen** renders (set only when `status: complete`) |
| `assistant_message` | string \| null | The latest advisor chat bubble text |
| `results` | object \| null | The **plan/results screen** (sizing options, advisories, plants) |
| `stages` | array of 5 | The **progress stepper** |
| `roof_sqft` | number \| null | The satellite roof estimate (echoed each turn; shown in the catchment question and as a results footnote) |
| `messages` | array | **Opaque to the UI** — transport state only. Do NOT render it. The visible chat log is built from `assistant_message` (advisor) + the user's own inputs. |
| `detail` | string \| null | Error / out-of-region explanation text |

> **Design takeaway:** you never parse `messages`. Design the transcript from the
> running list of user inputs + `assistant_message` values, the stepper from
> `stages`, and the final screen from `outcome` + `results`.

The `stages` array is always five items in this order, each
`{id, label, state}` with `state ∈ not_started | in_progress | complete`:

```json
[
  {"id": "address",            "label": "Address"},
  {"id": "localized_data",     "label": "Localized Data"},
  {"id": "site_conditions",    "label": "Site Conditions"},
  {"id": "growing_conditions", "label": "Growing Conditions"},
  {"id": "plan",               "label": "Rain Garden Plan"}
]
```

---

## 2. Sample payloads (4 states)

`messages` is shown as `"[…transport transcript, not rendered…]"` for readability —
it's a large opaque array in the real response.

### 2a. Mid-conversation — `awaiting_user` (the catchment question, roof estimate offered)

Localized data is done; the advisor is asking about the drainage area and has
surfaced the satellite roof estimate. Note `outcome` and `results` are `null`, the
stepper cursor sits on Site Conditions, and `roof_sqft` carries the exact figure
(already substituted into `assistant_message`).

```json
{
  "status": "awaiting_user",
  "outcome": null,
  "assistant_message": "Great — I've pulled your local rainfall and hardiness data. Now, how big is the area draining to this spot? A satellite look at your roof suggests about 1740 sq ft of total roof footprint — but that's the whole roof, and your downspout only carries part of it. You can give me your own number, or tell me to use that estimate.",
  "results": null,
  "roof_sqft": 1740,
  "detail": null,
  "messages": "[…transport transcript, not rendered…]",
  "stages": [
    {"id": "address",            "label": "Address",            "state": "complete"},
    {"id": "localized_data",     "label": "Localized Data",     "state": "complete"},
    {"id": "site_conditions",    "label": "Site Conditions",    "state": "in_progress"},
    {"id": "growing_conditions", "label": "Growing Conditions", "state": "not_started"},
    {"id": "plan",               "label": "Rain Garden Plan",   "state": "not_started"}
  ]
}
```

### 2b. Recommended plan — `complete`, `outcome: "plan"`

The full happy-path result. `catchment_sa = 600`, Loamy soil, good site.
`results.recommended = true`. Three depth options (deeper → smaller footprint),
each with its own token-injected `summary`, its own `advisories` array (empty
here), plus depth-invariant site `advisories`, the plant lists, and
`gallons_per_year`. The whole stepper is `complete`.

```json
{
  "status": "complete",
  "outcome": "plan",
  "assistant_message": "Here's your rain garden plan. At about 4 inches deep it covers roughly 192 sq ft; going deeper to 8 inches shrinks it to about 90 sq ft if space is tight. I've split the planting into a wetter center and a drier edge, and pulled a native plant list suited to your zone. A few things to check before you dig are noted below.",
  "results": {
    "recommended": true,
    "sizing": {
      "options": [
        {
          "depth_in": 4,
          "band": "3-5",
          "area_sqft": 192,
          "interior_plants": 87,
          "perimeter_plants": 21,
          "advisories": [],
          "summary": "At about 4 inches deep, your rain garden should cover roughly 192 sq ft. Plan for 87 plants in the wetter center and 21 around the drier edge. It captures roughly 15709 gallons of runoff a year from about 600 sq ft of catchment."
        },
        {
          "depth_in": 6,
          "band": "6-7",
          "area_sqft": 144,
          "interior_plants": 63,
          "perimeter_plants": 18,
          "advisories": [],
          "summary": "At about 6 inches deep, your rain garden should cover roughly 144 sq ft. Plan for 63 plants in the wetter center and 18 around the drier edge. It captures roughly 15709 gallons of runoff a year from about 600 sq ft of catchment."
        },
        {
          "depth_in": 8,
          "band": "8",
          "area_sqft": 90,
          "interior_plants": 37,
          "perimeter_plants": 14,
          "advisories": [],
          "summary": "At about 8 inches deep, your rain garden should cover roughly 90 sq ft. Plan for 37 plants in the wetter center and 14 around the drier edge. It captures roughly 15709 gallons of runoff a year from about 600 sq ft of catchment."
        }
      ],
      "advisories": []
    },
    "advisories": [
      {
        "type": "utilities",
        "severity": "informational",
        "message": "Check for underground utilities before digging."
      },
      {
        "type": "roof_estimate",
        "severity": "informational",
        "message": "The satellite roof estimate reflects your entire roof's footprint — not the catchment area for this specific downspout. Most homes have more than one gutter and downspout, each carrying only part of the total roof runoff."
      }
    ],
    "gallons_per_year": 15709,
    "plants": {
      "interior": [
        {"common_name": "Blue Flag Iris",    "bloom_period": "Spring",        "flower_color": "Blue",   "height_ft": 3, "moisture_use": "High"},
        {"common_name": "Swamp Milkweed",    "bloom_period": "Summer",        "flower_color": "Pink",   "height_ft": 4, "moisture_use": "High"},
        {"common_name": "Cardinal Flower",   "bloom_period": "Late Summer",   "flower_color": "Red",    "height_ft": 3, "moisture_use": "High"}
      ],
      "perimeter": [
        {"common_name": "Black-Eyed Susan",  "bloom_period": "Summer",        "flower_color": "Yellow", "height_ft": 3, "moisture_use": "Medium"},
        {"common_name": "Purple Coneflower",  "bloom_period": "Summer",        "flower_color": "Purple", "height_ft": 4, "moisture_use": "Medium"},
        {"common_name": "Little Bluestem",   "bloom_period": "Fall",          "flower_color": "Bronze", "height_ft": 3, "moisture_use": "Low"}
      ]
    }
  },
  "roof_sqft": 1740,
  "detail": null,
  "messages": "[…transport transcript, not rendered…]",
  "stages": [
    {"id": "address",            "label": "Address",            "state": "complete"},
    {"id": "localized_data",     "label": "Localized Data",     "state": "complete"},
    {"id": "site_conditions",    "label": "Site Conditions",    "state": "complete"},
    {"id": "growing_conditions", "label": "Growing Conditions", "state": "complete"},
    {"id": "plan",               "label": "Rain Garden Plan",   "state": "complete"}
  ]
}
```

> **Design notes for this screen:**
> - **Depth options are a 3-up card set / toggle** — this is the frontend's depth
>   selector. Same shape each, `area_sqft` + plant counts differ. Selected state =
>   sage accent (spec §2.2). Each option has its own `summary` prose and possibly
>   its own `advisories` (see 2c for when those fire).
> - **Two advisory levels:** per-option `sizing.options[i].advisories` (depth-
>   dependent) and top-level `results.advisories` (site-wide). Render both; group
>   by `severity`.
> - **`severity` values you'll see:** `informational` (neutral note),
>   `corrective` (do this / coexists with a plan), `blocking` (viability failure —
>   only in the not-recommended state). Map to spec §2.1 colors.
> - **Plants** split into `interior` (wettest center) and `perimeter` (drier edge),
>   up to 15 each. Fields: `common_name`, `bloom_period`, `flower_color`,
>   `height_ft`, `moisture_use`.
> - ⚠️ **Wireframe vs. API column mismatch:** the results wireframe's plant table
>   shows *Scientific Name* and *Drought Tolerance* columns that the API does **not**
>   return. `filter_plants` exposes `moisture_use` (not drought tolerance) and no
>   scientific name. Resolution is a **backend decision** (add `scientific_name` to
>   `tools.py` `_PLANT_COLUMNS`; relabel the column "Moisture Use" or add a real
>   drought-tolerance field) — see `DESIGN_SPEC.md` §6.4. Clean maps:
>   Height→`height_ft`, Color→`flower_color`, Bloom Period→`bloom_period`.

### 2c. Not recommended — `complete`, `outcome: "plan_not_recommended"`

State A: the user has a blocker (here the garden must sit **less than 10 ft from
the foundation**) but chose to proceed anyway. The plan is still produced, but
`recommended: false` and a `blocking` advisory rides in `results.advisories`. The
stepper still fills completely (a plan was produced). Design a **muted plan
header** that surfaces the blocker prominently but not alarmingly.

This example also shows the **depth-dependent option advisories** firing: a larger
catchment (1400 sq ft, Clayey) pushes the shallow option over 300 sq ft
(`split_ceiling`), which in turn enables the top-level `reduction_allowance` note
in `sizing.advisories`.

```json
{
  "status": "complete",
  "outcome": "plan_not_recommended",
  "assistant_message": "I've put together a plan, but I want to be upfront: siting a rain garden less than 10 feet from your foundation isn't recommended — water pooling that close can risk your foundation. If you're able to move it farther out, that's the safer choice. Here's the design in case you decide to proceed, with that caution kept front and center.",
  "results": {
    "recommended": false,
    "sizing": {
      "options": [
        {
          "depth_in": 4,
          "band": "3-5",
          "area_sqft": 448,
          "interior_plants": 224,
          "perimeter_plants": 29,
          "advisories": [
            {
              "type": "split_ceiling",
              "severity": "informational",
              "message": "At over 300 sq ft this is large for a single basin — consider dividing it into two or more smaller rain gardens."
            }
          ],
          "summary": "At about 4 inches deep, your rain garden should cover roughly 448 sq ft. Plan for 224 plants in the wetter center and 29 around the drier edge. It captures roughly 36654 gallons of runoff a year from about 1400 sq ft of catchment."
        },
        {
          "depth_in": 6,
          "band": "6-7",
          "area_sqft": 336,
          "interior_plants": 163,
          "perimeter_plants": 27,
          "advisories": [
            {
              "type": "split_ceiling",
              "severity": "informational",
              "message": "At over 300 sq ft this is large for a single basin — consider dividing it into two or more smaller rain gardens."
            }
          ],
          "summary": "At about 6 inches deep, your rain garden should cover roughly 336 sq ft. Plan for 163 plants in the wetter center and 27 around the drier edge. It captures roughly 36654 gallons of runoff a year from about 1400 sq ft of catchment."
        },
        {
          "depth_in": 8,
          "band": "8",
          "area_sqft": 224,
          "interior_plants": 104,
          "perimeter_plants": 23,
          "advisories": [],
          "summary": "At about 8 inches deep, your rain garden should cover roughly 224 sq ft. Plan for 104 plants in the wetter center and 23 around the drier edge. It captures roughly 36654 gallons of runoff a year from about 1400 sq ft of catchment."
        }
      ],
      "advisories": [
        {
          "type": "reduction_allowance",
          "severity": "informational",
          "message": "Any of these can be shrunk by up to 30% and still control about 90% of the yearly runoff — handy if the full size won't fit your yard."
        }
      ]
    },
    "advisories": [
      {
        "type": "foundation_setback",
        "severity": "blocking",
        "corrective_action": "relocate_min_10ft",
        "message": "Site the rain garden at least 10 ft from the foundation."
      },
      {
        "type": "clayey_unverified",
        "severity": "corrective",
        "corrective_action": "test_and_amend",
        "message": "Clayey soil: verify drainage is at least 0.5 in/hr; amend until it is."
      },
      {
        "type": "utilities",
        "severity": "informational",
        "message": "Check for underground utilities before digging."
      }
    ],
    "gallons_per_year": 36654,
    "plants": {
      "interior": [
        {"common_name": "Blue Flag Iris",  "bloom_period": "Spring", "flower_color": "Blue", "height_ft": 3, "moisture_use": "High"},
        {"common_name": "Swamp Milkweed",  "bloom_period": "Summer", "flower_color": "Pink", "height_ft": 4, "moisture_use": "High"}
      ],
      "perimeter": [
        {"common_name": "Black-Eyed Susan", "bloom_period": "Summer", "flower_color": "Yellow", "height_ft": 3, "moisture_use": "Medium"},
        {"common_name": "Switchgrass",      "bloom_period": "Fall",   "flower_color": "Green",  "height_ft": 5, "moisture_use": "Low"}
      ]
    }
  },
  "roof_sqft": null,
  "detail": null,
  "messages": "[…transport transcript, not rendered…]",
  "stages": [
    {"id": "address",            "label": "Address",            "state": "complete"},
    {"id": "localized_data",     "label": "Localized Data",     "state": "complete"},
    {"id": "site_conditions",    "label": "Site Conditions",    "state": "complete"},
    {"id": "growing_conditions", "label": "Growing Conditions", "state": "complete"},
    {"id": "plan",               "label": "Rain Garden Plan",   "state": "complete"}
  ]
}
```

> Note the extra advisory field on viability items: `corrective_action` (a machine
> slug like `relocate_min_10ft`) appears **only** on viability advisories. You can
> ignore it for display or use it to pick an icon; the human text is in `message`.

### 2d. Declined — `complete`, `outcome: "declined"`

State B: the user hit an un-overridable blocker and chose **not** to proceed.
There is **no plan** — `results` is `null`, only a kind closing `assistant_message`.
The stepper **freezes**: the site stage keeps its `in_progress` cursor and Plan
never completes. The frontend styles this "halt" from `outcome === "declined"`.

```json
{
  "status": "complete",
  "outcome": "declined",
  "assistant_message": "That's completely understandable — a spot with drainage this slow really isn't a good candidate for a rain garden without significant soil work, and it's better to know that now than after digging. If you ever amend the soil or pick a different part of the yard, I'd be glad to help you plan it then. Thanks for thinking about managing your stormwater the green way.",
  "results": null,
  "roof_sqft": 1740,
  "detail": null,
  "messages": "[…transport transcript, not rendered…]",
  "stages": [
    {"id": "address",            "label": "Address",            "state": "complete"},
    {"id": "localized_data",     "label": "Localized Data",     "state": "complete"},
    {"id": "site_conditions",    "label": "Site Conditions",    "state": "in_progress"},
    {"id": "growing_conditions", "label": "Growing Conditions", "state": "not_started"},
    {"id": "plan",               "label": "Rain Garden Plan",   "state": "not_started"}
  ]
}
```

### 2e. Out of region — `out_of_region` (bonus edge state)

Address resolved but is outside the lower-48. No transcript exists yet; only the
address stage is lit. Show `detail` and let the user re-enter an address.

> **Sibling state — `address_not_found`:** identical payload shape (same stepper,
> `results`/`messages` empty) but `status: "address_not_found"` and a different
> `detail` (*"I couldn't find that address…"*), fired when geocoding finds no match.
> These are the design's two distinct Address-error screens — key off `status`.

```json
{
  "status": "out_of_region",
  "outcome": null,
  "assistant_message": null,
  "results": null,
  "detail": "This tool currently supports the contiguous lower-48 US states only.",
  "roof_sqft": null,
  "messages": "[…empty / not rendered…]",
  "stages": [
    {"id": "address",            "label": "Address",            "state": "in_progress"},
    {"id": "localized_data",     "label": "Localized Data",     "state": "not_started"},
    {"id": "site_conditions",    "label": "Site Conditions",    "state": "not_started"},
    {"id": "growing_conditions", "label": "Growing Conditions", "state": "not_started"},
    {"id": "plan",               "label": "Rain Garden Plan",   "state": "not_started"}
  ]
}
```

There is also a `status: "error"` (HTTP 500) shape with `detail` — design a simple
error state for it.

---

## 3. Advisory type catalogue (for iconography / grouping)

Every `type` string the UI can receive, with its severity, so Design can plan icons
and grouping. `severity` drives color (spec §2.1); `type` can drive an icon.

| `type` | severity | Where | Meaning |
|---|---|---|---|
| `foundation_setback` | blocking | `results.advisories` | Garden < 10 ft from house |
| `slope` | blocking | `results.advisories` | Grade steeper than 12% |
| `low_drainage` | blocking | `results.advisories` | Measured drainage < 0.5 in/hr |
| `clayey_unverified` | corrective | `results.advisories` | Clay soil, drainage untested |
| `slope_toward_house` | corrective | `results.advisories` | Ground slopes toward house — needs overflow outlet |
| `unknown_soil` | informational | `results.advisories` | Soil undetermined; sized conservatively |
| `rate_unparsed` | informational | `results.advisories` | Couldn't read drainage rate |
| `utilities` | informational | `results.advisories` | Call 811 before digging (always present) |
| `roof_estimate` | informational | `results.advisories` | Whole-roof-footprint caveat (when estimate offered) |
| `split_ceiling` | informational | `options[i].advisories` | Option > 300 sq ft; consider splitting |
| `two_zone_floor` | corrective | `options[i].advisories` | Option too small for a separate center; single-zone planting |
| `reduction_allowance` | informational | `sizing.advisories` | May shrink up to 30% |

---

## 4. Example conversation (full happy path)

A representative transcript so Design can judge **chat length, tone, and rhythm**.
Voice is "plain, encouraging, homeowner-friendly" (from the system prompt). Each
advisor turn notes the tool(s) that fire and the stage that advances — use it to
storyboard the stepper animating alongside the chat.

> The **address is collected pre-chat** (its own entry screen), then the chat
> begins. The advisor never re-asks for state/zip/coordinates.

**[Entry screen]** User submits address: `1600 Grandview Ave, Columbus, OH`
→ server geocodes + gates + resolves roof estimate. Stepper: **Address ✓**.

---

**Advisor:** Nice — I found your place in Columbus and I've got the local rainfall
and USDA hardiness data queued up. Let me pull those now.
*(fires `get_precipitation_stats`, `get_hardiness_zone`)* → **Localized Data ✓**

**Advisor:** You're in hardiness zone 6a, and your area gets about 40 inches of
rain a year. Now let's talk about your site. How big is the area that drains to the
spot you have in mind? If it's your roof, a satellite look suggests about **1740
sq ft** of total roof — but that's the whole roof, and one downspout only carries
part of it. Give me your best number, or say "use the estimate."

**User:** It's the back half of the roof, I'd guess around 600 square feet.

**Advisor:** Perfect, 600 sq ft it is. A couple of quick site questions. About how
far is the spot from your house foundation — under 10 ft, 10 to 30 ft, or more
than 30 ft?

**User:** Maybe 20 feet.

**Advisor:** Good — that's a safe distance. And is the ground there fairly flat, or
does it slope? If it slopes, does it run toward the house or away from it?
*(as slots fill, fires `check_viability` incrementally)*

**User:** Pretty flat, slopes gently away from the house.

**Advisor:** That's an ideal setup. Last couple: what's the soil like there — sandy,
clay, loamy? And how much sun does the spot get?
*(→ Site Conditions ✓ once viability clears)*

**User:** It's pretty loamy, and it gets full sun most of the day.

**Advisor:** Great growing conditions. Let me put it all together.
*(fires `size_garden`, `filter_plants`, then `search_guidance`, then
`present_results`)* → **Growing Conditions ✓**, **Rain Garden Plan ✓**

**Advisor:** Here's your plan. At about **4 inches deep** it covers roughly **192
sq ft**; if space is tight, going to **8 inches** shrinks it to about **90 sq ft**.
I've split the planting into a wetter center and a drier edge and pulled a native
plant list for zone 6a — Blue Flag Iris and Swamp Milkweed for the center, Black-
Eyed Susan and Little Bluestem around the rim. A few things to check before you
dig are below. *(renders the results screen — 2b)*

---

**Storyboard summary (stepper vs. chat):**

| Chat beat | Tools fired | Stage that lights |
|---|---|---|
| Address entry (pre-chat) | geocode + roof estimate | Address ✓ |
| "pull local data" | precipitation + hardiness | Localized Data ✓ |
| distance / slope / soil Q&A | `check_viability` (incremental) | Site Conditions ✓ |
| sun + soil confirmed | `filter_plants` | Growing Conditions ✓ |
| "here's your plan" | `size_garden` → `present_results` | Rain Garden Plan ✓ |

---

## 5. Source of truth
Shapes from `app.py` (`ChatResponse`, `_stages`, `_ROOF_ADVISORY`) and `tools.py`
(`_size_garden`, `check_viability`, `_advisories`, plant columns). Numbers computed
with `src/rain_garden/sizing.py` (factors `SIZE_FACTORS_BY_DEPTH`,
`PLANT_WIDTH_FT = 1.33`, `GALLONS_PER_CUBIC_INCH = 0.004329`). Plant *names* are
illustrative placeholders; their **shape** is exact.

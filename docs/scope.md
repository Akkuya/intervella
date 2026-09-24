# UTSC Room Finder — Scope Document

**Working title:** RoomFinder (UTSC) **One-liner:** Shows which rooms and buildings on campus are free right now, and recommends the best place to study based on where you are and how many people you have.

---

## 1. Problem

Finding an empty room at UTSC means wandering hallways or checking room bookings by hand. Timetable data exists, but it's spread across systems and not shaped around the question students actually ask: *"where can I sit right now?"*

## 2. Goals

1. Answer "what's free near me, right now, for N people?" in under 10 seconds.
2. Be a solid portfolio piece: real data pipeline, real users, deployed and usable.
3. Leave room for a university collaboration and a 3D map later, without needing them for v1.

## 3. Non-goals (for v1)

- 3D visualization
- Actually booking rooms
- Storing anyone's UTORid credentials
- Anything requiring official university approval

## 4. Critical first step: data feasibility (Phase 0)

Everything depends on where the data comes from. Answer these before writing app code:

- **What's public?** The public course timetable already lists sections with days, times, and rooms. That alone can power "free = no scheduled class" for a v1.
- **What's behind login?** The room schedule view on the intranet (which lectures are running in each room). This is scheduled-class data, not a booking system, and the app only *shows* empty rooms; it never books anything. Compare it against the public timetable: it may be the same data, in which case you don't need the login at all.
- **Is scraping behind login allowed?** Check UofT's acceptable-use / IT policies. Automating a logged-in session or handling other people's credentials is the risky part. Design so the app **never** asks users for their UTORid password.
- **Room metadata:** capacity, room type, building/floor. Find out if it's published anywhere or if it must be entered by hand for a subset of buildings.
- **Fallback:** if login-gated data is off limits, ship v1 on public timetable data and label it "based on scheduled classes; may not reflect ad hoc bookings."

**Exit criteria:** a written note listing data sources, what each gives you, and what's allowed.

## 5. Phases

### Phase 1 — MVP (core value)

- Ingest timetable data into a database (rooms, buildings, time slots)
- "Free now" and "free until X" list, filterable by building
- Room info: type, capacity (where known)
- Mobile-first web app (PWA), works fine on desktop too
- Deployed with a public URL

### Phase 2 — Smart recommendations

- Input: group size, how long you need, optional location
- Ranking by: distance from you, free duration, capacity fit, room type
- Start with a transparent scoring function (weights you tune); consider an ML/learning layer only once you have usage or feedback data
- Geolocation with a manual building-picker fallback

### Phase 3 — Campus map (2D)

- Floor plans/building map with free rooms highlighted
- Walking distance/time between buildings

### Phase 4 — Crowd signal (optional)

- "I'm here" or "this room is actually empty/busy" reports from users, to correct for ad hoc use that timetables miss

### Phase 5 — 3D campus view (far future)

- 3D building models with room-level highlighting (e.g. three.js / CesiumJS)
- Only worth it once Phases 1–3 have real users

### Phase 6 — University collaboration (far future)

- Pitch to UTSC IT / student union with usage numbers
- Possible official data feed instead of scraping

## 6. Suggested tech stack (adjust freely)

| Layer | Option |
| --- | --- |
| Data ingestion | Python scripts on a schedule |
| Database | SQLite/Postgres |
| Backend | FastAPI or Node |
| Frontend | React PWA (mobile-first) |
| Maps | Leaflet/Mapbox (2D), three.js (3D later) |
| Hosting | Free tier (Vercel/Render/Fly) |

**Mobile vs desktop:** start as a PWA. One codebase, installable on a phone, usable on a laptop. Native apps can wait.

## 7. Risks

| Risk | Mitigation |
| --- | --- |
| Data behind login / policy issues | Phase 0 check; start with public data; never handle passwords |
| Timetable ≠ reality (rooms used ad hoc, exams, events) | Clear disclaimer; Phase 4 crowd signal |
| Scraper breaks when site changes | Isolate ingestion; alert on failures; cache last good data |
| Scope creep into 3D | Phases are gated; 3D is explicitly Phase 5 |
| Low adoption | Ship early, share in class groups/Discord, get feedback |

## 8. Success metrics

- Phase 1 shipped and deployed within a few weeks
- 50+ weekly users from UTSC students
- Data accuracy: spot-check 20 rooms, aim for \~90% correct "free now"
- Bonus: one public write-up/README with architecture and screenshots

## 9. Portfolio framing

Highlight: data pipeline design, handling messy real-world data, recommendation scoring, deployed product with real users. Keep the README honest about data limits.

## 10. Open questions

- Which data sources are actually accessible and permitted?
- Is room capacity available, or does it need to be collected manually?
- Do floor plans exist publicly for map work?

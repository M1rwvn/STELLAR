# Research summary: Digital Twin and astronaut health monitoring

> Status: concise engineering note for a student hackathon prototype. Sources below were found by web search
> on 2026-10-27; only the statements attributed to them are claimed. Anything not in a listed source is marked
> **ENGINEERING ASSUMPTION** or **PENDING VERIFICATION**. This is not medical guidance.

## 1. What a Digital Twin means in personalized health monitoring
A digital twin is a digital model kept in sync with data from a physical counterpart, used for monitoring and
simulation. In healthcare, a *personalized* digital twin is an individualized model updated with person-specific
data (Saratkar et al., 2025; see also source 5). In AstroGuardian the twin is deliberately
simple: **a personal baseline** (robust median + reference interval per signal, from calibration days 1-14) and
**deviations of new readings from it**. It is a monitoring indicator, not a physiological simulation.

## 2. Why personal baselines can reveal changes population thresholds miss
Two astronauts can both have a "normal" resting heart rate (e.g. 62 and 72 bpm) while a rise of 10 bpm is
unusual for only one of them in context. A fixed population threshold flags neither; a personal baseline flags the
change relative to that individual. NASA's own sleep-risk evidence report notes individual differences in sleep need
and in responses to sleep loss and circadian misalignment (Flynn-Evans et al., NTRS 20160003864), which supports
comparing a person with themselves. *(The numeric examples above are illustrative design values, not data.)*

## 3. Astronaut health-monitoring considerations (supported by retrieved sources)
* Sleep is reduced and circadian misalignment occurs on the ISS (NASA NTRS 20140003280). NASA's Human Research
  Program describes sleep loss, circadian desynchronization and work overload as a spaceflight risk area (NASA
  sleep-risk page and NTRS 20160003864).
* A NASA-STD-3001 technical brief on sleep accommodations reports average nightly sleep of about 6-6.5 hours on shuttle
  and ISS (actigraphy summary). This is why `sleep_hours`, `sleep_quality` and a sleep-debt feature are tracked.
* The same NASA material notes there are no easily collected biomarkers to determine circadian phase in flight
  (NTRS 20160003864) - so our circadian pattern in the synthetic data is a modelling choice, not a measurement.

**PENDING VERIFICATION in v1.0 (most now covered in section 3b):** microgravity muscle/bone loss, fluid
shift and vision problems (SANS), radiation, psychological stress/isolation effects, and reference ranges of HR, HRV,
SpO2 and temperature in astronauts vs. the general population. Suggested research questions:
1. What resting HR/HRV/SpO2/temperature ranges are reported for ISS crew in flight vs. pre-flight?
2. How large are in-flight changes in resting HR and sleep duration relative to individual pre-flight baselines?
3. Which wearable signals have been validated in flight (e.g. NASA/ESA studies), and with what error?
4. Which NASA-STD-3001 / HRP evidence reports define monitoring thresholds, if any?

## 3b. Pending topics completed in v1.1 (sources retrieved 2026-10-28)
Each statement below is attributed to the source it comes from; check the full paper before quoting numbers.

* **The five hazards.** NASA's Human Research Program groups spaceflight risks into five hazards: space radiation,
  isolation and confinement, distance from Earth, gravity (and its absence), and closed/hostile environments, and notes
  that they can compound one another (NASA HRP "hazards" page, source 7). The acronym "RIDGE" is used by secondary
  sources, not shown on the NASA page.
* **Bone loss.** In 17 ISS astronauts (missions of ~5.5 months), tibia bone mineral density was still ~2.1 % lower and
  bone strength ~1.3 % lower one year after landing; 9 of the 17 had not fully recovered (Gabel et al., 2022, source 8).
  The often quoted "1-1.5 % per month" rate was **not** confirmed by the sources retrieved - do not cite it.
* **Vision / fluid shift (SANS).** Spaceflight-associated neuro-ocular syndrome describes eye and vision changes in
  flight; the leading hypothesis is the headward shift of blood and cerebrospinal fluid in microgravity, but the
  mechanism is not settled (NASA ISS science note, source 9; Lee et al. review, source 10). Reported prevalence
  varies between sources - quote none without the original paper.
* **Body temperature in space.** Core body temperature of astronauts rose by about 1 °C at rest, building up over
  ~2.5 months on long missions (Stahn et al., 2017, source 11). Relevance for us: a personal temperature baseline
  must come from the astronaut's own in-flight calibration, not from ground norms.
* **Heart-rate variability rhythm.** 24-hour ECG studies of ISS crews found that the 24-, 12- and 8-hour HRV
  rhythms persist during long missions (Otsuka et al., 2016, source 12). This supports the circadian pattern in our
  synthetic data and the limitation that a single all-hours baseline mixes day and night.
* **Radiation.** ISS crews receive roughly 0.4-1.0 mSv per day, depending on solar activity; ~80 mSv per six months at
  solar maximum and ~160 mSv at solar minimum (figures from secondary reports of NASA data, sources 13-14 -
  **secondary**, verify against a NASA document before presenting).
* **Isolation and confinement.** NASA lists behavioural and psychological responses of small isolated crews as part
  of the isolation hazard (source 7). AstroGuardian does not model psychological state; HRV/stress indicators are
  physiological proxies only.

**Still PENDING VERIFICATION:** in-flight reference ranges of resting HR, SpO2 and respiration rate (question 1 above).

## 4. Table of metric ranges used in this project
| Metric | Unit | Synthetic scenario design value (stable astronaut) | Source status |
|---|---|---|---|
| hr | bpm | ~60-65 (Ahmed); other astronauts 54-74 | Team task file (design value) |
| hrv | ms | ~55-70 | Team task file (design value) |
| spo2 | % | ~96-99; Omar's deterioration ~93 | Team task file (design value) |
| temp | degC | ~36.5-36.9; Omar's deterioration ~37.8 | Team task file (design value) |
| sleep_hours | h/day | ~7 | Team task file (design value) |
| resp_rate | breaths/min | 12-18 | Team task file (design value) |
These are **scenario design values, not medically validated reference intervals**. A medically verified
comparison table is PENDING VERIFICATION (question 1).

## 5. Limitations and the diagnosis boundary
Synthetic data cannot establish real-world accuracy; every output of this module is a *monitoring indicator*
(percent change from a personal reference), never a diagnosis. See `limitations.md`.

## 6. Sources (all retrieved by search; check details before citing in a paper)
1. NASA NTRS 20140003280, "Fatigue-Related Countermeasures for Long-Duration Exploration Missions" (NASA HRP Behavioral
   Health and Performance Element). https://ntrs.nasa.gov/citations/20140003280
2. Flynn-Evans, E. et al., NASA HRP evidence report on risk from sleep loss, circadian desynchronization and work
   overload, NTRS 20160003864 (exact title/year to be confirmed from the PDF).
   https://ntrs.nasa.gov/api/citations/20160003864/downloads/20160003864.pdf
3. NASA-STD-3001 Technical Brief, "Sleep Accommodations" (NASA OCHMO).
   https://www.nasa.gov/wp-content/uploads/2023/03/sleep-accomodations-technical-brief-ochmo.pdf
4. Saratkar S.Y., Langote M., Kumar P., Gote P., Weerarathna I.N., Mishra G.V. (2025). "Digital twin for personalized
   medicine development." Frontiers in Digital Health 7:1583466. doi:10.3389/fdgth.2025.1583466
5. "Digital Twins' Advancements and Applications in Healthcare, Towards Precision Medicine." Journal of Personalized
   Medicine 2024, 14(11):1101. doi:10.3390/jpm14111101
6. NASA Human Research Roadmap page "Risk of Performance Decrements and Adverse Health Outcomes Resulting from Sleep Loss,
   Circadian Desynchronization, and Work Overload" (nasa.gov; found via search - add the exact URL when citing).
7. NASA Human Research Program, "5 Hazards of Human Spaceflight". https://www.nasa.gov/hrp/hazards
8. Gabel L. et al. (2022). Bone recovery 1 year after long-duration spaceflight (17 ISS astronauts), Scientific
   Reports. Summary: https://www.sci.news/space/spaceflight-bone-strength-density-10963.html (open the original paper
   before citing numbers).
9. NASA, "Science in Space: July 28, 2023 - astronaut vision (SANS)".
   https://www.nasa.gov/missions/station/science-in-space-july-28-2023-astronaut-vision/
10. Lee A.G. et al. (2020). Spaceflight associated neuro-ocular syndrome (SANS), review (NASA NTRS 20200002256).
    https://ntrs.nasa.gov/api/citations/20200002256/downloads/20200002256.pdf
11. Stahn A.C. et al. (2017). "Increased core body temperature in astronauts during long-duration space missions."
    Scientific Reports 7:16180. doi:10.1038/s41598-017-15560-w. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5701078/
12. Otsuka K. et al. (2016). "Long-term exposure to space's microgravity alters the time structure of heart rate
    variability of astronauts." Heliyon. https://doaj.org/article/11207814ef8944fc920f1cb36a0b37f9
13. NBC News (2012), report of D. Hassler (Curiosity RAD) on ISS daily dose. https://www.nbcnews.com/id/wbna50072690
    (secondary)
14. STCE / Royal Observatory of Belgium, "Radiation in space" (cites NASA/MSFC six-month ISS doses).
    https://www.sidc.be/article/radiation-space (secondary)

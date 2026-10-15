# Shannon Energy — Metric Dictionary (Tableau)

Project cut-off date: **30 June 2026**. `TODAY()` is never used — the analysis must
reproduce identically at any future date.

Source of values: the `prepared/` tables produced by `scripts/prepare_data.py`.
Every control value in this document is asserted by that script on each run.

---

## 1. Data sources and model

Five independent sources. **Fact tables are never joined to each other** — their grains
differ, and joining them would fan out rows and inflate every measure.

| Source | File | Grain |
|---|---|---|
| AcquisitionClean | `AcquisitionClean.csv` | one row = one acquisition (25,998) |
| MonthlyPerformance | `MonthlyPerformance.csv` | month × channel × segment × region × tariff × fuel |
| PlanPerformance | `PlanPerformance.csv` | month × channel × segment |
| RetentionCohorts | `RetentionCohorts.csv` | cohort × channel × segment × region × fuel × tariff × **N** |
| ChurnBase | `ChurnBase.csv` | one row = one churn event (17,018) |

Dimension attributes are denormalised into each fact during preparation, so no
Relationships are needed in Tableau. `Dim_Channel` carries the technical code **LEG**
and `Dim_Region` the code **UNK**.

Filters are synchronised across sources through **parameters** only. Filter actions do
not bridge independent data sources, and identically named fields do not link anything
by themselves.

---

## 2. Parameters

| Parameter | Type | Purpose |
|---|---|---|
| `pStartMonth` | Date | Start of the analysed period |
| `pEndMonth` | Date | End of the analysed period |
| `pSegmentFocus` | String | Segment selector (RES / SME / COR / All segments) |

```
// DataAsOf — a project constant, deliberately NOT TODAY()
#2026-06-30#
```

---

## 3. Growth metrics — source: MonthlyPerformance

```
// Acquisitions — count of cleaned acquisitions
SUM([Acquisitions])
```
```
// Churned Customers — churn events in the selected period
SUM([ChurnedCustomers])
```
```
// Net Adds
SUM([Acquisitions]) - SUM([ChurnedCustomers])
```
```
// Acquisition Cost
SUM([AcquisitionCost])
```
```
// CPA — division guarded against zero
IF SUM([Acquisitions]) > 0
THEN SUM([AcquisitionCost]) / SUM([Acquisitions])
END
```
```
// Revenue
SUM([Revenue])
```
```
// Closing Base — the base of the LAST OBSERVED MONTH in the period.
// A customer base is a stock, not a flow: summing it across months is meaningless.

{ FIXED : MAX( IF [MonthStart] <= [pEndMonth] AND [RevenueObservationCount] = 1
               THEN [MonthStart] END ) }          // field: Last Observed Month

SUM( IF DATETRUNC('month', [MonthStart]) = DATETRUNC('month', [Last Observed Month])
     THEN [ClosingCustomers] END )                // field: Closing Base
```
> `DATETRUNC` is required on both sides: Tableau reads the CSV date column as a datetime,
> so a direct equality comparison silently returns nothing.
>
> **Control value: 18,470.** This must equal one month's base, never a sum across months.

```
// Monthly ARPU — revenue per customer-month observation, NOT per customer
IF SUM([ClosingCustomers]) > 0
THEN SUM([Revenue]) / SUM([ClosingCustomers])
END
```

---

## 4. Monthly Churn Rate

The denominator is the **opening** base, not the current one. Percentages from different
months are never averaged: numerators and denominators are summed separately, so a large
month carries more weight than a small one.

```
// Churn Numerator
SUM( IIF([MonthEligibleForChurnRate] = 1, [ChurnedCustomers], 0) )
```
```
// Churn Denominator
SUM( IIF([MonthEligibleForChurnRate] = 1, [OpeningCustomers], 0) )
```
```
// Monthly Churn Rate
IF [Churn Denominator] > 0
THEN [Churn Numerator] / [Churn Denominator]
END
```

**Control value with no filters applied: 2.919411%.**

### What `MonthEligibleForChurnRate` does, and why it matters

A month is eligible if it has a revenue observation **and** a positive opening base. The
flag is computed in `prepare_data.py` **at month level**, not at row level. This is not a
stylistic choice — it is the difference between a correct and an incorrect metric.

An earlier version of this calculation returned **1.92%**. Two separate defects caused it:

1. **Eligibility applied at row level.** The 5,967 legacy churn events coded `LEG` have no
   revenue rows, so a row-level filter discarded them silently before aggregation —
   removing roughly a third of all churn from the numerator.
2. **The opening base was lost for disappearing key combinations.** Joining the previous
   month with a *left* join dropped any key combination that existed last month and not
   this one. `OpeningCustomers` must come from the snapshot of the **previous calendar
   month**, not from "the previous existing row", so an *outer* join is required.

### Documented limitation

The flag is fixed at the overall level, without business filters. Only January 2023 — the
first month of the dataset, which has no preceding snapshot — is excluded. Under a narrow
filter a month may have a zero base; the denominator guard then returns NULL rather than a
misleading zero.

Annualised churn is deliberately **not** published as a headline KPI: compounding a monthly
rate assumes a constant hazard across the year, which the tenure analysis shows is false.

---

## 5. Twelve-month retention — source: AcquisitionClean

`Eligible12Flag`, `Retained12Flag` and `Eligible12Cost` are pre-computed in the pipeline.
`TenureAtChurn` is the supplied `TenureMonths`, never recomputed from days.
`MonthsObservable` counts month boundaries between the acquisition month and the cut-off —
month precision, not day precision.

```
// 12-Month Retention
IF SUM([Eligible12Flag]) > 0
THEN SUM([Retained12Flag]) / SUM([Eligible12Flag])
END
```
```
// 12M Cohort Coverage %
IF COUNTD([CustomerID]) > 0
THEN SUM([Eligible12Flag]) / COUNTD([CustomerID])
END
```
```
// Cost per Retained Customer
IF SUM([Retained12Flag]) > 0
THEN SUM([Eligible12Cost]) / SUM([Retained12Flag])
END
```
```
// 12M Cohort CPA
IF SUM([Eligible12Flag]) > 0
THEN SUM([Eligible12Cost]) / SUM([Eligible12Flag])
END
```

Control values with no filters: **65.963216%** / **65.251173%** / **€170.3053**.

**Immature cohorts are excluded from the denominator.** A cohort acquired three months
before the cut-off cannot yet have a twelve-month outcome; including it would bias
retention upward.

**Cost per Retained Customer is not CPA divided by retention.** The two are computed over
different populations: CPA covers all acquisitions, this metric only mature cohorts.

---

## 6. Retention curves and tenure risk — source: RetentionCohorts

The `N` axis is ordered 0, 1, 2 … 24. A customer appears at several values of `N`:
**customers and costs must never be summed across N.**

```
// Retention Rate — cumulative survival
IF SUM([EligibleN]) > 0
THEN SUM([RetainedN]) / SUM([EligibleN])
END
```
```
// Tenure Churn Rate — probability of leaving specifically in month N,
// among those still at risk at the start of that month
IF SUM([AtRiskN]) > 0
THEN SUM([ChurnAtN]) / SUM([AtRiskN])
END
```

A zero denominator returns NULL, not zero, so immature and future cells of the cohort
heatmap stay empty rather than reading as 0% retention.

Retention Rate at `N = 12` must equal the 12-Month Retention KPI. This is a built-in
cross-check between two independently constructed sources.

**Retention Rate and Tenure Churn Rate are different metrics** and do not sum to 100%: one
is cumulative survival, the other a single-period hazard.

---

## 7. Plan versus actual — source: PlanPerformance

The plan exists at three keys only: `MonthStart × ChannelCode × SegmentCode`.

```
// Acquisition Variance %
IF SUM([TargetAcquisitions]) > 0
THEN SUM([ActualAcquisitions]) / SUM([TargetAcquisitions]) - 1
END
```
```
// Plan Availability — guard against a plan that does not exist at this grain
IF SUM([TargetAcquisitions]) > 0 THEN "Plan set"
ELSE "No plan is defined at this level of detail"
END
```

When sliced by region, tariff or fuel, plan-based KPIs are shown as **N/A** with that
explanation. The plan is never spread or allocated across a grain it was not set at —
doing so would invent targets and present them as given.

---

## 8. Revenue Rolling 12M

```
// AnchorMonth — the last month with an actual revenue observation
// inside the selected period
{ FIXED : MAX( IF [RevenueObservationCount] = 1 AND [MonthStart] <= [pEndMonth]
               THEN [MonthStart] END ) }
```
```
// Revenue Rolling 12M
SUM(
  IF [MonthStart] >= DATEADD('month', -11, [AnchorMonth])
     AND [MonthStart] <= [AnchorMonth]
  THEN [Revenue]
  END
)
```

**Control value: €158,057,438.68**, covering July 2025 to June 2026.

An ordinary period filter must **not** be placed on this sheet: it would cut off the
preceding months the calculation needs. The period is bounded only through `pStartMonth`
and `pEndMonth` inside the formula.

`FIXED` is evaluated before dimension filters, so any business filter that should affect
this calculation must be converted to a **context filter**. If the period contains no
observations, the sheet shows N/A.

---

## 9. What the period filter means on each page

| Page | Meaning of the selected period |
|---|---|
| Growth & Performance | months of business operation |
| Channel Economics | the **acquisition** period |
| Retention & Churn | cohorts: acquisition period; churn events: period of **leaving** |

A single date filter is deliberately not applied mechanically across all sources, because
the same calendar range means different things to different grains.

---

## 10. What this data cannot support

The following are never presented as facts:

- **Profit and margin.** The sources contain no cost of goods. A *Contribution per
  Acquisition (24M)* metric based on an assumed 18% margin was removed from the project
  rather than published on an assumption.
- **Causality.** The churn spike at month 12 coincides with the expiry of twelve-month
  contracts, but the data contains no renewal event, no price change at renewal and no
  competitor pricing. This is a **hypothesis**, not a demonstrated cause.
- **Forecasts.** Future periods contain no actuals.
- **Revenue per individual customer.** `Fact_Revenue_Monthly` carries no `CustomerID`.

### A separate observation, outside the original specification

Peak `ClosingCustomers` is 18,470, while `Dim_Customer` holds 40,998 customers. The revenue
table therefore does not cover the whole customer base.

Consequently **Closing Base and the customer count from `Dim_Customer` are different
metrics** and are never displayed side by side as though they were the same thing.

Monthly ARPU by segment: RES ≈ €124–166, SME ≈ €1,037–1,397, COR ≈ €8,082–10,864.

The figures above are **FACT**; the conclusion that revenue coverage is partial is an
**INFERENCE**.

---

## 11. Dashboard footnotes

Every dashboard carries the same footer, so no screenshot can circulate without its caveats:

```
Data as of 30 Jun 2026
Retention uses mature cohorts only
Synthetic demonstration data
```

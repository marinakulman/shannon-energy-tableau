# Shannon Energy — словарь показателей (Tableau)

Дата среза проекта: **30 июня 2026**. Не использовать `TODAY()`.
Источник значений: `prepared/`. Все контрольные значения раздела 15 ТЗ воспроизведены.

---

## 1. Источники данных и модель

Четыре независимых источника. **JOIN между фактами не использовать** — разная гранулярность размножит строки.

| Источник | Файл | Гранулярность |
|---|---|---|
| AcquisitionClean | `AcquisitionClean.csv` | 1 строка = 1 привлечение (25 998) |
| MonthlyPerformance | `MonthlyPerformance.csv` | месяц × канал × сегмент × регион × тариф × топливо |
| PlanPerformance | `PlanPerformance.csv` | месяц × канал × сегмент |
| RetentionCohorts | `RetentionCohorts.csv` | когорта × канал × сегмент × регион × топливо × тариф × **N** |
| ChurnBase | `ChurnBase.csv` | 1 строка = 1 событие оттока (17 018) |

Справочники (`Dim_*.csv`) подключаются к каждому источнику через **Relationships**, не JOIN.
`Dim_Channel` содержит служебный код **LEG**, `Dim_Region` — **UNK**.

Синхронизация фильтров между источниками — только через **параметры** или явный
*Edit Blend Relationships*. Одинаковые названия полей сами по себе ничего не связывают.

---

## 2. Параметры

| Параметр | Тип | Назначение |
|---|---|---|
| `pStartMonth` | Date | Начало анализируемого периода |
| `pEndMonth` | Date | Конец анализируемого периода |
| `pSegmentFocus` | String | Выбор сегмента для scatterplot (RES / SME / COR / All) |

```
// DataAsOf — константа проекта, НЕ TODAY()
#2026-06-30#
```

---

## 3. Показатели роста — источник MonthlyPerformance

```
// Acquisitions — количество очищенных привлечений
SUM([Acquisitions])
```
```
// Churned Customers — события оттока за выбранный период
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
// CPA — деление защищено от нуля
IF SUM([Acquisitions]) > 0
THEN SUM([AcquisitionCost]) / SUM([Acquisitions])
END
```
```
// Revenue
SUM([Revenue])
```
```
// Closing Base — база ПОСЛЕДНЕГО наблюдаемого месяца периода.
// Суммировать клиентскую базу за несколько месяцев нельзя.
{ FIXED : MAX( IF [MonthStart] <= [pEndMonth] AND [RevenueObservationCount] = 1
               THEN [MonthStart] END ) }   // поле Last Observed Month

SUM( IF [MonthStart] = [Last Observed Month] THEN [ClosingCustomers] END )   // поле Closing Base
```
> Проверка: значение равно базе одного месяца, а не сумме за период. Контроль — 18 470.

```
// Monthly ARPU — выручка на клиенто-месячное наблюдение, НЕ на клиента
IF SUM([ClosingCustomers]) > 0
THEN SUM([Revenue]) / SUM([ClosingCustomers])
END
```

---

## 4. Monthly Churn Rate

Знаменатель — открывающая база, а не текущая. Проценты разных месяцев не усредняются:
суммируются числители и знаменатели.

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

**Контроль без фильтров: 2,919411%.**

### Что делает `MonthEligibleForChurnRate`

Месяц допустим, если в нём есть наблюдение выручки **и** положительная открывающая база.
Флаг рассчитан в `prepare_data.py` **на уровне месяца**, а не строки. Это принципиально:

- при отборе на уровне строки 5 967 событий оттока канала **LEG** выпадают молча
  (у LEG нет строк выручки), и показатель падает до 1,92% — заниженное, неверное значение;
- `OpeningCustomers` берётся из снимка **предыдущего календарного месяца** тех же ключей,
  а не «предыдущей существующей строки». Комбинации ключей, исчезнувшие в текущем месяце,
  сохраняют свою открывающую базу отдельной строкой — иначе знаменатель занижается.

**Ограничение, которое нужно указать в tooltip:** флаг зафиксирован на общем уровне
(без бизнес-фильтров). Исключается только январь 2023 — первый месяц набора, у которого нет
предыдущего снимка. Если под узким фильтром у какого-то месяца база окажется нулевой,
показатель для него вернёт NULL через защиту знаменателя. Годовую экстраполяцию оттока
основным KPI не выводить.

---

## 5. Удержание на 12-м месяце — источник AcquisitionClean

Флаги `Eligible12Flag`, `Retained12Flag`, `Eligible12Cost` уже рассчитаны в данных
по формулам раздела 8 ТЗ. `TenureAtChurn` — исходный `TenureMonths`, без пересчёта из дней.
`MonthsObservable` — число месячных границ между месяцем привлечения и датой среза
(месячная, не дневная точность).

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

Контроль без фильтров: **65,963216%** / **65,251173%** / **€170,305300**.

Незрелые когорты в знаменатель retention не входят. Cost per Retained Customer —
это не общий CPA, делённый на retention: базы разные.

---

## 6. Кривые удержания и риск оттока — источник RetentionCohorts

Ось N отсортирована **0, 1, 2 … 24**. Клиент представлен на нескольких значениях N:
**суммировать клиентов или стоимость по всем N нельзя.**

```
// Retention Rate — накопленное удержание
IF SUM([EligibleN]) > 0
THEN SUM([RetainedN]) / SUM([EligibleN])
END
```
```
// Tenure Churn Rate — вероятность ухода именно в месяце N среди ещё подверженных риску
IF SUM([AtRiskN]) > 0
THEN SUM([ChurnAtN]) / SUM([AtRiskN])
END
```

При нулевом знаменателе возвращается NULL, а не ноль. В heatmap незрелые и будущие ячейки
остаются пустыми. Значение Retention Rate при N = 12 обязано совпасть с KPI 12-Month Retention.

Retention и Tenure Churn Rate — **разные показатели**, не дополняют друг друга до 100%.

---

## 7. План против факта — источник PlanPerformance

План задан только на трёх ключах: `MonthStart × ChannelCode × SegmentCode`.

```
// Acquisition Variance %
IF SUM([TargetAcquisitions]) > 0
THEN SUM([ActualAcquisitions]) / SUM([TargetAcquisitions]) - 1
END
```
```
// Plan Availability — защита от несуществующего плана
IF SUM([TargetAcquisitions]) > 0 THEN "Plan set"
ELSE "План не задан на этой детализации"
END
```

При разрезе по региону, тарифу или топливу плановые KPI показывать как **N/A**
с этим пояснением. План по этим измерениям не размножать.

---

## 8. Revenue Rolling 12M

```
// AnchorMonth — последний месяц с фактическим наблюдением выручки внутри периода и фильтров
{ FIXED : MAX( IIF([RevenueObservationCount] = 1 AND [MonthStart] <= [pEndMonth],
                   [MonthStart], NULL) ) }
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

**Контроль: €158 057 438,68**, интервал июль 2025 — июнь 2026.

На этот лист обычный фильтр периода не накладывать: он отрежет предыдущие месяцы,
которые нужны расчёту. Ограничивать период только через `pStartMonth` / `pEndMonth`
внутри формулы. `FIXED` не реагирует на dimension filters — бизнес-фильтры,
которые должны влиять на расчёт, переводить в **context filters**.
Если наблюдений в периоде нет — показывать N/A.

---

## 9. Смысл фильтра периода по страницам

| Страница | Что означает период |
|---|---|
| Growth & Performance | месяцы бизнес-операций |
| Channel Economics | период **привлечения** клиентов |
| Retention & Churn | когорты — период привлечения; события оттока — период **ухода** |

Один фильтр даты механически ко всем источникам не применять.

---

## 10. Чего в этих данных нет

Не выводить как факт:

- **прибыль и маржу** — в источниках нет себестоимости. Показатель
  *Contribution per Acquisition (24M)* с условной маржой 18% из проекта исключён;
- **причинность** — пик ухода на 12-м месяце совпадает с окончанием 12-месячных
  контрактов, но данные не доказывают причину. Это **гипотеза**;
- **прогноз** — будущие периоды фактических данных не содержат;
- **выручку на конкретного клиента** — `Fact_Revenue_Monthly` не содержит `CustomerID`.

**Отдельное наблюдение (в ТЗ отсутствует).** Пик `ClosingCustomers` — 18 470,
клиентов в `Dim_Customer` — 40 998. Таблица выручки покрывает не всю базу.
Следовательно **Closing Base и число клиентов из Dim_Customer — разные метрики**
и рядом как одно и то же не показываются. ARPU по сегментам:
RES ≈ €124–166/мес, SME ≈ €1 037–1 397, COR ≈ €8 082–10 864.
Это **ФАКТ**; вывод о неполном покрытии — **ИНФЕРЕНС**.

---

## 11. Подписи на дашбордах

```
Data as of 30 Jun 2026
Retention uses mature cohorts only
Synthetic demonstration data
```

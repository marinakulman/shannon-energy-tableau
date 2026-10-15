"""
Shannon Energy - data preparation for Tableau.
Input  : ../data/raw/*.csv  (source files, NEVER modified)
Output : ../prepared/*.csv  + ../docs/data_quality_report.md
Project cut-off date: 2026-06-30 (fixed, deliberately NOT TODAY()).
"""
import pandas as pd, numpy as np, os, warnings
from decimal import Decimal
warnings.filterwarnings('ignore')

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'raw'))
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'prepared'))
DOC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'docs'))
os.makedirs(OUT, exist_ok=True)
os.makedirs(DOC, exist_ok=True)
DATA_AS_OF = pd.Timestamp('2026-06-30')
MAX_N = 24
log = []
def note(s):
    log.append(s); print(s)

L = lambda f: pd.read_csv(os.path.join(SRC, f), encoding='utf-8-sig', dtype=str)

# ---------------------------------------------------------------- dimensions
dim_channel = L('Dim_Channel.csv')
dim_region  = L('Dim_Region.csv')
dim_segment = L('Dim_Segment.csv')
dim_fuel    = L('Dim_Fuel.csv')
dim_tariff  = L('Dim_Tariff.csv')
dim_cust    = L('Dim_Customer.csv')

# extend dimensions with technical members
dim_channel = pd.concat([dim_channel, pd.DataFrame([{
    'ChannelCode':'LEG','ChannelName':'Legacy / channel unavailable',
    'ChannelType':'Unknown','ChannelGroup':'Legacy'}])], ignore_index=True)
dim_region = pd.concat([dim_region, pd.DataFrame([{
    'RegionCode':'UNK','RegionName':'Unknown','Market':'Unknown'}])], ignore_index=True)

dim_cust['CustomerID'] = dim_cust.CustomerID.str.strip()
dim_cust['AcquisitionDate'] = pd.to_datetime(dim_cust.AcquisitionDate, format='%Y-%m-%d')

# ---------------------------------------------------------------- acquisitions
acq = L('Fact_Acquisitions.csv')
n_raw = len(acq)
acq['CustomerID'] = acq.CustomerID.str.strip()
acq = acq.drop_duplicates()
n_dedup = len(acq)
note(f'Acquisitions: {n_raw} rows in, {n_raw-n_dedup} exact duplicates removed, {n_dedup} retained.')

conflicts = acq[acq.duplicated('CustomerID', keep=False)]
if len(conflicts):
    conflicts.to_csv(os.path.join(DOC,'conflicts_duplicate_customerid.csv'), index=False)
    note(f'WARNING: {conflicts.CustomerID.nunique()} CustomerID values with conflicting records exported to docs/.')
else:
    note('No CustomerID conflicts after deduplication - the key is unique.')

# money: strip the euro sign, thousands separators and spaces. Parse failures are NOT zeroed.
raw_cost = acq.AcquisitionCost
n_currency = raw_cost.str.contains('€', na=False).sum()
cost_clean = (raw_cost.str.replace('€','',regex=False)
                      .str.replace(',','',regex=False)
                      .str.replace(' ','',regex=False).str.strip())
acq['AcquisitionCost'] = pd.to_numeric(cost_clean, errors='coerce')
n_cost_bad = acq.AcquisitionCost.isna().sum()
note(f'AcquisitionCost: {n_currency} values carried a euro sign; {n_cost_bad} remain unparseable.')

# channels: explicit mapping only, never fuzzy matching
CHANNEL_MAP = {
 'digital':'DIG','web/digital':'DIG',
 'pcw':'PCW','price comparison':'PCW',
 'call center':'CCT','call centre':'CCT',
 'direct field':'FLD','field sales':'FLD',
 'partner / retail':'PTR','partner/retail':'PTR','retail partner':'PTR',
 'broker':'BRK','broker channel':'BRK',
 'direct b2b':'DIR','direct-b2b':'DIR',
}
key = acq.Channel.str.strip().str.lower().str.replace(r'\s+',' ',regex=True)
acq['ChannelCode'] = key.map(CHANNEL_MAP)
unmapped = acq[acq.ChannelCode.isna()]
if len(unmapped):
    unmapped.Channel.value_counts().to_csv(os.path.join(DOC,'unmapped_channels.csv'))
    note(f'WARNING: {len(unmapped)} rows with an unknown channel - exported, NOT defaulted to DIR.')
else:
    note(f'Channels: {key.nunique()} source spellings mapped to 7 codes, none unknown.')

n_region_null = acq.RegionCode.isna().sum()
acq['RegionCode'] = acq.RegionCode.fillna('UNK')
note(f'RegionCode: {n_region_null} blank values flagged UNK (customers retained).')

acq['AcquisitionDate'] = pd.to_datetime(acq.AcquisitionDate, format='%Y-%m-%d')
acq['CohortMonth'] = acq.AcquisitionDate.values.astype('datetime64[M]')

# ---------------------------------------------------------------- churn
ch = L('Fact_Churn.csv')
ch['CustomerID'] = ch.CustomerID.str.strip()
iso = pd.to_datetime(ch.ChurnDate, format='%Y-%m-%d', errors='coerce')
dmy = pd.to_datetime(ch.ChurnDate, format='%d/%m/%Y', errors='coerce')
n_iso, n_dmy = iso.notna().sum(), dmy.notna().sum()
ch['ChurnDate'] = iso.fillna(dmy)
n_bad_date = ch.ChurnDate.isna().sum()
note(f'ChurnDate: {n_iso} in ISO format, {n_dmy} in DD/MM/YYYY - parsed explicitly; {n_bad_date} unrecognised.')
ch['TenureMonths'] = pd.to_numeric(ch.TenureMonths, errors='coerce')
n_switch_null = ch.SwitchedTo.isna().sum()
ch['SwitchedTo'] = ch.SwitchedTo.fillna('Not stated')
note(f'SwitchedTo: {n_switch_null} blank values flagged "Not stated".')
assert not ch.CustomerID.duplicated().any(), 'repeated churn events per customer'
note(f'Churn: {len(ch)} events, no customer appears twice.')

# ChurnBase - an independent churn-event table, attributes sourced from Dim_Customer
churn_base = ch.merge(dim_cust[['CustomerID','SegmentCode','RegionCode','FuelCode','TariffCode']],
                      on='CustomerID', how='left')
churn_base = churn_base.merge(acq[['CustomerID','ChannelCode']], on='CustomerID', how='left')
n_leg = churn_base.ChannelCode.isna().sum()
churn_base['ChannelCode'] = churn_base.ChannelCode.fillna('LEG')
churn_base['RegionCode']  = churn_base.RegionCode.fillna('UNK')
churn_base['ChurnMonth']  = churn_base.ChurnDate.values.astype('datetime64[M]')
note(f'ChurnBase: {n_leg} churn events with no matching acquisition flagged channel LEG (retained, not dropped).')

# ---------------------------------------------------------------- cohorts
m = acq.merge(ch[['CustomerID','ChurnDate','TenureMonths']], on='CustomerID', how='left')
m['Churned'] = m.ChurnDate.notna()
m['TenureAtChurn'] = m.TenureMonths            # as supplied, never recomputed from days
m['MonthsObservable'] = ((DATA_AS_OF.year - m.AcquisitionDate.dt.year)*12
                        + (DATA_AS_OF.month - m.AcquisitionDate.dt.month))
m['Eligible12Flag'] = (m.MonthsObservable >= 12).astype(int)
m['Retained12Flag'] = np.where(m.MonthsObservable >= 12,
                        np.where(m.Churned & (m.TenureAtChurn <= 12), 0, 1), 0)
m['Eligible12Cost']  = np.where(m.MonthsObservable >= 12, m.AcquisitionCost, 0.0)

acq_clean = m[['CustomerID','AcquisitionDate','CohortMonth','ChannelCode','SegmentCode',
               'RegionCode','TariffCode','FuelCode','AcquisitionCost','Churned','ChurnDate',
               'TenureAtChurn','MonthsObservable','Eligible12Flag','Retained12Flag','Eligible12Cost']]
acq_clean.to_csv(os.path.join(OUT,'AcquisitionClean.csv'), index=False)

# ---------------------------------------------------------------- RetentionCohorts
KEYS = ['CohortMonth','ChannelCode','SegmentCode','RegionCode','FuelCode','TariffCode']
rows = []
for N in range(0, MAX_N+1):
    e  = m.MonthsObservable >= N
    lost     = e & m.Churned & (m.TenureAtChurn <= N)
    retained = e & ~lost
    at_risk  = e & ~(m.Churned & (m.TenureAtChurn < N))
    churn_n  = e & m.Churned & (m.TenureAtChurn == N)
    t = m[KEYS].copy()
    t['N'] = N
    t['EligibleN'], t['RetainedN'], t['AtRiskN'], t['ChurnAtN'] = e.astype(int), retained.astype(int), at_risk.astype(int), churn_n.astype(int)
    rows.append(t)
coh = (pd.concat(rows).groupby(KEYS+['N'], as_index=False)
         [['EligibleN','RetainedN','AtRiskN','ChurnAtN']].sum())
coh = coh[coh.EligibleN > 0]
coh.to_csv(os.path.join(OUT,'RetentionCohorts.csv'), index=False)
note(f'RetentionCohorts: {len(coh)} rows (a customer appears at several values of N - customers must never be summed across N).')

# ---------------------------------------------------------------- MonthlyPerformance
GK = ['MonthStart','ChannelCode','SegmentCode','RegionCode','TariffCode','FuelCode']
rev = L('Fact_Revenue_Monthly.csv')
rev['MonthStart'] = pd.to_datetime(rev.MonthStart, format='%Y-%m-%d')
rev['Revenue'] = pd.to_numeric(rev.Revenue)
rev['ClosingCustomers'] = pd.to_numeric(rev.ActiveCustomers)
rev = rev[GK+['Revenue','ClosingCustomers']].copy()
rev['RevenueObservationCount'] = 1

a_agg = (acq.assign(MonthStart=acq.CohortMonth)
            .groupby(GK, as_index=False)
            .agg(Acquisitions=('CustomerID','count'), AcquisitionCost=('AcquisitionCost','sum')))
c_agg = (churn_base.assign(MonthStart=churn_base.ChurnMonth)
            .groupby(GK, as_index=False)
            .agg(ChurnedCustomers=('CustomerID','count')))

mp = rev.merge(a_agg, on=GK, how='outer').merge(c_agg, on=GK, how='outer')
for c in ['Acquisitions','ChurnedCustomers','AcquisitionCost']:
    mp[c] = mp[c].fillna(0)
mp['RevenueObservationCount'] = mp.RevenueObservationCount.fillna(0).astype(int)

# OpeningCustomers = snapshot of the PREVIOUS CALENDAR MONTH, not of the previous existing row
prev = rev[GK+['ClosingCustomers']].copy()
prev['MonthStart'] = prev.MonthStart + pd.DateOffset(months=1)
prev = prev.rename(columns={'ClosingCustomers':'OpeningCustomers'})
# outer, not left: a key combination that existed last month and disappeared this
# month must keep its opening base - otherwise the Monthly Churn Rate
# denominator is silently understated.
mp = mp.merge(prev, on=GK, how='outer')
for c in ['Acquisitions','ChurnedCustomers','AcquisitionCost']:
    mp[c] = mp[c].fillna(0)
mp['RevenueObservationCount'] = mp.RevenueObservationCount.fillna(0).astype(int)
# Month-eligibility flag for Monthly Churn Rate, fixed at the OVERALL level
# (no business filters). It makes the denominator computable by plain aggregation and
# guarantees LEG churn is not lost. The limitation is documented in the metric dictionary.
_e = mp.groupby('MonthStart').agg(op=('OpeningCustomers','sum'), obs=('RevenueObservationCount','sum'))
_ok = set(_e[(_e.obs > 0) & (_e.op > 0)].index)
mp['MonthEligibleForChurnRate'] = mp.MonthStart.isin(_ok).astype(int)

mp = mp.sort_values(GK)
mp.to_csv(os.path.join(OUT,'MonthlyPerformance.csv'), index=False)
note(f'MonthlyPerformance: {len(mp)} rows; OpeningCustomers is blank in {mp.OpeningCustomers.isna().sum()} rows (no previous-month snapshot).')

# ---------------------------------------------------------------- PlanPerformance
PK = ['MonthStart','ChannelCode','SegmentCode']
tgt = L('Fact_Target.csv')
tgt['MonthStart'] = pd.to_datetime(tgt.MonthStart, format='%Y-%m-%d')
tgt['TargetAcquisitions'] = pd.to_numeric(tgt.TargetAcquisitions)
act = (acq.assign(MonthStart=acq.CohortMonth).groupby(PK, as_index=False)
          .agg(ActualAcquisitions=('CustomerID','count')))
pp = tgt.merge(act, on=PK, how='outer')
pp['TargetAcquisitions']  = pp.TargetAcquisitions.fillna(0)
pp['ActualAcquisitions']  = pp.ActualAcquisitions.fillna(0)
pp.sort_values(PK).to_csv(os.path.join(OUT,'PlanPerformance.csv'), index=False)
note(f'PlanPerformance: {len(pp)} rows at month x channel x segment grain (no plan is set by region, tariff or fuel).')

# ---------------------------------------------------------------- dimensions + N calendar
dim_channel.to_csv(os.path.join(OUT,'Dim_Channel.csv'), index=False)
dim_region.to_csv(os.path.join(OUT,'Dim_Region.csv'), index=False)
dim_segment.to_csv(os.path.join(OUT,'Dim_Segment.csv'), index=False)
dim_fuel.to_csv(os.path.join(OUT,'Dim_Fuel.csv'), index=False)
dim_tariff.to_csv(os.path.join(OUT,'Dim_Tariff.csv'), index=False)
dim_cust.to_csv(os.path.join(OUT,'Dim_Customer.csv'), index=False)
churn_base[['CustomerID','ChurnDate','ChurnMonth','ChurnReason','SwitchedTo','TenureMonths',
            'ChannelCode','SegmentCode','RegionCode','FuelCode','TariffCode']
          ].to_csv(os.path.join(OUT,'ChurnBase.csv'), index=False)

# ---------------------------------------------------------------- control values
el = acq_clean.Eligible12Flag.sum(); ret = acq_clean.Retained12Flag.sum()
cost_el = acq_clean.Eligible12Cost.sum()
anchor = rev.MonthStart.max()
r12 = rev[(rev.MonthStart >= anchor - pd.DateOffset(months=11)) & (rev.MonthStart <= anchor)].Revenue.sum()
checks = [
 ('Acquisitions before cleaning', n_raw, 26238),
 ('Acquisitions after cleaning', n_dedup, 25998),
 ('Duplicates removed', n_raw-n_dedup, 240),
 ('Churn events', len(ch), 17018),
 ('Customers with 12 months observable', int(el), 16964),
 ('Churned by month 12', int(el-ret), 5774),
 ('Retained at month 12', int(ret), 11190),
 ('12-Month Retention, %', round(100*ret/el,6), 65.963216),
 ('12M Cohort Coverage, %', round(100*el/acq_clean.CustomerID.nunique(),6), 65.251173),
 ('Acquisition cost of mature cohorts, EUR', round(cost_el,2), 1905716.31),
 ('Cost per Retained Customer, €', round(cost_el/ret,6), 170.305300),
 ('Revenue Rolling 12M, €', round(r12,2), 158057438.68),
 ('LEG churn events', int(n_leg), 5967),
]
# Monthly Churn Rate over a comparable scope
# Eligibility is decided AT MONTH LEVEL, not by discarding individual rows
# before aggregation (which would lose LEG churn).
_v = mp[mp.MonthEligibleForChurnRate == 1]
mcr = 100*_v.ChurnedCustomers.sum()/_v.OpeningCustomers.sum()
checks.append(('Monthly Churn Rate, %', round(mcr,6), 2.919411))
note('')
note('| Check | Actual | Expected | Status |')
note('|---|---|---|---|')
ok_all = True
for name, got, exp in checks:
    ok = abs(float(got)-float(exp)) < 0.0000015*max(1,abs(exp))
    ok_all &= ok
    note(f'| {name} | {got:,} | {exp:,} | {"OK" if ok else "MISMATCH"} |')
checks.append(('Monthly Churn Rate, %', round(mcr,6), 2.919411))
note('')
note('RESULT: ' + ('all control values match.' if ok_all else 'MISMATCHES FOUND - investigate the cause, do not tune the formulas to fit.'))
note(f'Cut-off date: {DATA_AS_OF.date()}. AnchorMonth for Rolling 12M: {anchor.date()}.')

with open(os.path.join(DOC,'data_quality_report.md'),'w') as f:
    f.write('# Shannon Energy - Data Quality Report\n\n')
    f.write(f'Generated by `scripts/prepare_data.py`. Cut-off date: **{DATA_AS_OF.date()}**.\n\n')
    f.write('\n'.join(('' if s.startswith('|') else '- ')+s if s else '' for s in log))
    f.write('\n')

# ---------------------------------------------------------------- denormalisation
# Dimension attributes are merged into the facts: the dimensions are tiny and static,
# fan-out is impossible, and Tableau receives flat files with no Relationships to manage.
import subprocess, sys
subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                'denormalize.py')], check=True)

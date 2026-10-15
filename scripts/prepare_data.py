"""
Shannon Energy — подготовка данных для Tableau.
Вход  : ../../*.csv  (исходники, НЕ изменяются)
Выход : ../prepared/*.csv  + ../docs/data_quality_report.md
Дата среза проекта: 2026-06-30 (фиксированная, НЕ TODAY()).
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

# ---------------------------------------------------------------- справочники
dim_channel = L('Dim_Channel.csv')
dim_region  = L('Dim_Region.csv')
dim_segment = L('Dim_Segment.csv')
dim_fuel    = L('Dim_Fuel.csv')
dim_tariff  = L('Dim_Tariff.csv')
dim_cust    = L('Dim_Customer.csv')

# расширяем справочники служебными членами
dim_channel = pd.concat([dim_channel, pd.DataFrame([{
    'ChannelCode':'LEG','ChannelName':'Legacy / channel unavailable',
    'ChannelType':'Unknown','ChannelGroup':'Legacy'}])], ignore_index=True)
dim_region = pd.concat([dim_region, pd.DataFrame([{
    'RegionCode':'UNK','RegionName':'Unknown','Market':'Unknown'}])], ignore_index=True)

dim_cust['CustomerID'] = dim_cust.CustomerID.str.strip()
dim_cust['AcquisitionDate'] = pd.to_datetime(dim_cust.AcquisitionDate, format='%Y-%m-%d')

# ---------------------------------------------------------------- привлечения
acq = L('Fact_Acquisitions.csv')
n_raw = len(acq)
acq['CustomerID'] = acq.CustomerID.str.strip()
acq = acq.drop_duplicates()
n_dedup = len(acq)
note(f'Привлечения: {n_raw} строк на входе, удалено полных дублей {n_raw-n_dedup}, осталось {n_dedup}.')

conflicts = acq[acq.duplicated('CustomerID', keep=False)]
if len(conflicts):
    conflicts.to_csv(os.path.join(DOC,'conflicts_duplicate_customerid.csv'), index=False)
    note(f'ВНИМАНИЕ: {conflicts.CustomerID.nunique()} CustomerID с расходящимися записями выгружены в docs/.')
else:
    note('Конфликтов CustomerID после дедупликации нет — ключ уникален.')

# деньги: снимаем €, разделители тысяч, пробелы. Ошибки НЕ обнуляем.
raw_cost = acq.AcquisitionCost
n_currency = raw_cost.str.contains('€', na=False).sum()
cost_clean = (raw_cost.str.replace('€','',regex=False)
                      .str.replace(',','',regex=False)
                      .str.replace(' ','',regex=False).str.strip())
acq['AcquisitionCost'] = pd.to_numeric(cost_clean, errors='coerce')
n_cost_bad = acq.AcquisitionCost.isna().sum()
note(f'AcquisitionCost: {n_currency} значений содержали знак €; непреобразуемых осталось {n_cost_bad}.')

# каналы: явный маппинг, без «похоже на»
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
    note(f'ВНИМАНИЕ: {len(unmapped)} строк с неизвестным каналом — выгружены, НЕ отнесены к DIR.')
else:
    note(f'Каналы: {key.nunique()} исходных написаний сведены к 7 кодам, неизвестных нет.')

n_region_null = acq.RegionCode.isna().sum()
acq['RegionCode'] = acq.RegionCode.fillna('UNK')
note(f'RegionCode: {n_region_null} пустых значений помечены UNK (клиенты сохранены).')

acq['AcquisitionDate'] = pd.to_datetime(acq.AcquisitionDate, format='%Y-%m-%d')
acq['CohortMonth'] = acq.AcquisitionDate.values.astype('datetime64[M]')

# ---------------------------------------------------------------- отток
ch = L('Fact_Churn.csv')
ch['CustomerID'] = ch.CustomerID.str.strip()
iso = pd.to_datetime(ch.ChurnDate, format='%Y-%m-%d', errors='coerce')
dmy = pd.to_datetime(ch.ChurnDate, format='%d/%m/%Y', errors='coerce')
n_iso, n_dmy = iso.notna().sum(), dmy.notna().sum()
ch['ChurnDate'] = iso.fillna(dmy)
n_bad_date = ch.ChurnDate.isna().sum()
note(f'ChurnDate: {n_iso} в формате ISO, {n_dmy} в DD/MM/YYYY — разобраны явно; нераспознанных {n_bad_date}.')
ch['TenureMonths'] = pd.to_numeric(ch.TenureMonths, errors='coerce')
n_switch_null = ch.SwitchedTo.isna().sum()
ch['SwitchedTo'] = ch.SwitchedTo.fillna('Not stated')
note(f'SwitchedTo: {n_switch_null} пустых значений помечены "Not stated".')
assert not ch.CustomerID.duplicated().any(), 'повторные события оттока'
note(f'Отток: {len(ch)} событий, повторных событий на клиента нет.')

# ChurnBase — независимая таблица событий оттока, атрибуты из Dim_Customer
churn_base = ch.merge(dim_cust[['CustomerID','SegmentCode','RegionCode','FuelCode','TariffCode']],
                      on='CustomerID', how='left')
churn_base = churn_base.merge(acq[['CustomerID','ChannelCode']], on='CustomerID', how='left')
n_leg = churn_base.ChannelCode.isna().sum()
churn_base['ChannelCode'] = churn_base.ChannelCode.fillna('LEG')
churn_base['RegionCode']  = churn_base.RegionCode.fillna('UNK')
churn_base['ChurnMonth']  = churn_base.ChurnDate.values.astype('datetime64[M]')
note(f'ChurnBase: {n_leg} событий оттока без записи о привлечении помечены каналом LEG (не удалены).')

# ---------------------------------------------------------------- когорты
m = acq.merge(ch[['CustomerID','ChurnDate','TenureMonths']], on='CustomerID', how='left')
m['Churned'] = m.ChurnDate.notna()
m['TenureAtChurn'] = m.TenureMonths            # исходный, без пересчёта из дней
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
note(f'RetentionCohorts: {len(coh)} строк (клиент представлен на нескольких N — суммировать клиентов по всем N нельзя).')

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

# OpeningCustomers = снимок ПРЕДЫДУЩЕГО КАЛЕНДАРНОГО месяца, не «предыдущей строки»
prev = rev[GK+['ClosingCustomers']].copy()
prev['MonthStart'] = prev.MonthStart + pd.DateOffset(months=1)
prev = prev.rename(columns={'ClosingCustomers':'OpeningCustomers'})
# outer, а не left: комбинация ключей, существовавшая в прошлом месяце и
# исчезнувшая в этом, обязана сохранить свою открывающую базу — иначе
# знаменатель Monthly Churn Rate молча занижается.
mp = mp.merge(prev, on=GK, how='outer')
for c in ['Acquisitions','ChurnedCustomers','AcquisitionCost']:
    mp[c] = mp[c].fillna(0)
mp['RevenueObservationCount'] = mp.RevenueObservationCount.fillna(0).astype(int)
# Флаг допустимости месяца для Monthly Churn Rate, зафиксированный на ОБЩЕМ уровне
# (без бизнес-фильтров). Делает знаменатель вычислимым обычной агрегацией и
# гарантирует, что отток LEG не теряется. Ограничение описано в словаре показателей.
_e = mp.groupby('MonthStart').agg(op=('OpeningCustomers','sum'), obs=('RevenueObservationCount','sum'))
_ok = set(_e[(_e.obs > 0) & (_e.op > 0)].index)
mp['MonthEligibleForChurnRate'] = mp.MonthStart.isin(_ok).astype(int)

mp = mp.sort_values(GK)
mp.to_csv(os.path.join(OUT,'MonthlyPerformance.csv'), index=False)
note(f'MonthlyPerformance: {len(mp)} строк; OpeningCustomers пуст в {mp.OpeningCustomers.isna().sum()} строках (нет снимка предыдущего месяца).')

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
note(f'PlanPerformance: {len(pp)} строк на детализации месяц × канал × сегмент (план по региону/тарифу/топливу не задан).')

# ---------------------------------------------------------------- Dim + календарь N
dim_channel.to_csv(os.path.join(OUT,'Dim_Channel.csv'), index=False)
dim_region.to_csv(os.path.join(OUT,'Dim_Region.csv'), index=False)
dim_segment.to_csv(os.path.join(OUT,'Dim_Segment.csv'), index=False)
dim_fuel.to_csv(os.path.join(OUT,'Dim_Fuel.csv'), index=False)
dim_tariff.to_csv(os.path.join(OUT,'Dim_Tariff.csv'), index=False)
dim_cust.to_csv(os.path.join(OUT,'Dim_Customer.csv'), index=False)
churn_base[['CustomerID','ChurnDate','ChurnMonth','ChurnReason','SwitchedTo','TenureMonths',
            'ChannelCode','SegmentCode','RegionCode','FuelCode','TariffCode']
          ].to_csv(os.path.join(OUT,'ChurnBase.csv'), index=False)

# ---------------------------------------------------------------- контроль
el = acq_clean.Eligible12Flag.sum(); ret = acq_clean.Retained12Flag.sum()
cost_el = acq_clean.Eligible12Cost.sum()
anchor = rev.MonthStart.max()
r12 = rev[(rev.MonthStart >= anchor - pd.DateOffset(months=11)) & (rev.MonthStart <= anchor)].Revenue.sum()
checks = [
 ('Привлечения до очистки', n_raw, 26238),
 ('Привлечения после очистки', n_dedup, 25998),
 ('Удалённые дубли', n_raw-n_dedup, 240),
 ('События оттока', len(ch), 17018),
 ('Клиенты с 12 мес. наблюдения', int(el), 16964),
 ('Ушедшие к 12-му месяцу', int(el-ret), 5774),
 ('Оставшиеся к 12-му месяцу', int(ret), 11190),
 ('12-Month Retention, %', round(100*ret/el,6), 65.963216),
 ('12M Cohort Coverage, %', round(100*el/acq_clean.CustomerID.nunique(),6), 65.251173),
 ('Стоимость привлечения зрелых когорт, €', round(cost_el,2), 1905716.31),
 ('Cost per Retained Customer, €', round(cost_el/ret,6), 170.305300),
 ('Revenue Rolling 12M, €', round(r12,2), 158057438.68),
 ('События оттока LEG', int(n_leg), 5967),
]
# Monthly Churn Rate на сопоставимой области
# Допустимость месяца определяется НА УРОВНЕ МЕСЯЦА разреза, а не отбрасыванием
# отдельных строк до агрегирования (иначе теряется отток LEG).
_v = mp[mp.MonthEligibleForChurnRate == 1]
mcr = 100*_v.ChurnedCustomers.sum()/_v.OpeningCustomers.sum()
checks.append(('Monthly Churn Rate, %', round(mcr,6), 2.919411))
note('')
note('| Проверка | Факт | Ожидание | Статус |')
note('|---|---|---|---|')
ok_all = True
for name, got, exp in checks:
    ok = abs(float(got)-float(exp)) < 0.0000015*max(1,abs(exp))
    ok_all &= ok
    note(f'| {name} | {got:,} | {exp:,} | {"OK" if ok else "РАСХОЖДЕНИЕ"} |')
checks.append(('Monthly Churn Rate, %', round(mcr,6), 2.919411))
note('')
note('ИТОГ: ' + ('все контрольные значения сошлись.' if ok_all else 'ЕСТЬ РАСХОЖДЕНИЯ — формулы не подгонять, искать причину.'))
note(f'Дата среза: {DATA_AS_OF.date()}. AnchorMonth для Rolling 12M: {anchor.date()}.')

with open(os.path.join(DOC,'data_quality_report.md'),'w') as f:
    f.write('# Shannon Energy — отчёт качества данных\n\n')
    f.write(f'Сгенерирован `scripts/prepare_data.py`. Дата среза: **{DATA_AS_OF.date()}**.\n\n')
    f.write('\n'.join(('' if s.startswith('|') else '- ')+s if s else '' for s in log))
    f.write('\n')

# ---------------------------------------------------------------- денормализация
# Атрибуты справочников вшиваются в факты: справочники статические и крошечные,
# fan-out невозможен, а Tableau получает плоские файлы без Relationships.
import subprocess, sys
subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                'denormalize.py')], check=True)

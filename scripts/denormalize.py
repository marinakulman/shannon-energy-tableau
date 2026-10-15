"""Денормализация: атрибуты справочников вшиваются в факты.
Справочники крошечные (3-8 строк), fan-out невозможен. Даёт плоские CSV,
которые Tableau читает без Relationships."""
import pandas as pd, os
P = os.path.abspath(os.path.join(os.path.dirname(__file__),'..','prepared'))
L = lambda f: pd.read_csv(os.path.join(P,f))

dims = {
 'ChannelCode': L('Dim_Channel.csv'),
 'SegmentCode': L('Dim_Segment.csv'),
 'RegionCode':  L('Dim_Region.csv'),
 'TariffCode':  L('Dim_Tariff.csv'),
 'FuelCode':    L('Dim_Fuel.csv'),
}
for f in ['MonthlyPerformance','AcquisitionClean','RetentionCohorts','PlanPerformance','ChurnBase']:
    d = L(f+'.csv'); n0 = len(d)
    for k, dim in dims.items():
        if k in d.columns:
            d = d.merge(dim, on=k, how='left')
    assert len(d) == n0, f'{f}: размножение строк!'
    d.to_csv(os.path.join(P, f+'.csv'), index=False)
    print(f'{f}: {n0} строк, {len(d.columns)} колонок -> {list(d.columns)[-4:]}')

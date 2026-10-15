"""Denormalisation: dimension attributes are merged into the fact tables.
The dimensions are tiny (3-8 rows) and fan-out is impossible. The result is flat
CSV files that Tableau reads without needing Relationships."""
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
    assert len(d) == n0, f'{f}: row count changed - fan-out detected!'
    d.to_csv(os.path.join(P, f+'.csv'), index=False)
    print(f'{f}: {n0} rows, {len(d.columns)} columns -> {list(d.columns)[-4:]}')

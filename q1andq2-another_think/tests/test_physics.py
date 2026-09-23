import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pytest
from core import Data

@pytest.fixture(scope='module')
def data():return Data()

def test_charge_boundary_and_known_values(data):
    for g,d in data.drones.items():
        assert data.charge_time(g,1)==0
        assert data.charge_time(g,0)==pytest.approx(d.charge_full)
        assert data.charge_time(g,.9)==pytest.approx(.35*d.charge_full)
        assert data.charge_time(g,.9-1e-10)==pytest.approx(data.charge_time(g,.9),abs=1e-5)
        assert data.charge_time(g,.8)==pytest.approx(d.charge_full*(.65*.1/.9+.35))

def test_payload_boundaries_and_monotonicity(data):
    for g,d in data.drones.items():
        for s in data.sites:
            q=data.safe_payload(g,s)
            assert q is not None
            assert data.energy(g,'O01',s,q)+data.energy(g,s,'O01',0)<=(1-d.reserve)*d.battery+1e-8
            if q<d.capacity-1e-5:
                assert data.energy(g,'O01',s,q+1e-5)+data.energy(g,s,'O01',0)>(1-d.reserve)*d.battery
            assert data.safe_payload(g,s,.1)>=q

def test_geometry_reversal(data):
    for (a,b),leg in data.legs.items():
        rev=data.legs[b,a]
        assert leg['distance']==pytest.approx(rev['distance'])
        assert leg['cruise_z']==rev['cruise_z']
        assert leg['climb']==rev['descent']

def test_multistop_mass_accounting(data):
    ids=['S001-MED-01','S002-MED-01']
    r=data.route('C',ids,['S001','S002'])
    assert r
    assert [l['load'] for l in r['legs']]==[6,3,0]
    assert r['completion'][ids[1]]>r['completion'][ids[0]]
    assert r['duration']>r['completion'][ids[1]]

def test_volume_prevents_overpacking(data):
    ids=[b.id for b in data.by_site['S001'] if b.category=='生活卫生用品']
    assert len(ids)==2
    assert data.route('A',ids) is None  # 12kg 未超质量，但 0.07m3 超过 0.06m3。

"""题目统一数据与物理规则。内部单位 kg, m, s, kWh；不依赖工作目录。"""
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import Counter
import json
import hashlib
import math
import numpy as np
import pandas as pd
import openpyxl
from scipy.io import loadmat
from scipy.optimize import brentq
from pyproj import Geod

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw'
RESULTS = ROOT / 'results'
GEOD = Geod(ellps='WGS84')

def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=lambda x: x.item() if isinstance(x, np.generic) else str(x)), encoding='utf-8')

def csv(name, rows):
    path = RESULTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')

def workbook(name):
    return openpyxl.load_workbook(next(RAW.rglob(name)), data_only=True)

@dataclass(frozen=True)
class Drone:
    id: str
    name: str
    mass: float
    capacity: float
    volume: float
    speed: float
    range0: float
    rangeF: float
    battery: float
    reserve: float
    prep: float
    load: float
    service: float
    unload: float
    up: float
    down: float
    efficiency: float
    descent_eff: float
    count: int
    batteries: int
    charge_full: float

@dataclass(frozen=True)
class Box:
    id: str
    site: str
    category: str
    mass: float
    volume: float
    first: bool
    first_deadline: float
    desired: float
    priority: float

    @property
    def hard(self):
        return min(self.first_deadline if self.first else math.inf,
                   self.desired if self.category == '医疗物资' else math.inf)

class Data:
    def __init__(self):
        rows = list(workbook('调度中心与服务区.xlsx')['数据'].values)
        self.nodes = {r[0]: dict(id=r[0], name=r[1], lon=r[2], lat=r[3], z=r[4], population=r[5] or 0)
                      for r in [rows[2]] + rows[6:] if r[0]}
        self.sites = sorted(k for k in self.nodes if k != 'O01')
        rows = list(workbook('运输无人机数据.xlsx')['数据'].values)
        self.units = {g: [r[0] for r in rows[8:16] if r[1] == g] for g in 'ABC'}
        self.drones = {}
        for r, stock in zip(rows[2:5], rows[19:22]):
            vals = list(r); vals[9] /= 100
            self.drones[r[0]] = Drone(*vals, len(self.units[r[0]]), stock[1], stock[2])
        rows = list(workbook('物资需求与配送时限.xlsx')['逐箱货箱清单'].values)[1:]
        self.boxes = {r[0]: Box(*list(r[:5]), r[5] == '是', r[6] or math.inf, r[7], r[8]) for r in rows if r[0]}
        self.by_site = {s: [b for b in self.boxes.values() if b.site == s] for s in self.sites}
        self.dem_data = loadmat(next(RAW.rglob('*DEM.mat')))
        self.dem = self.dem_data['dem']
        self.transform = self.dem_data['transform'].ravel()
        self.lon = self.dem_data['longitude'].ravel()
        self.lat = self.dem_data['latitude'].ravel()
        self.legs = {}
        for a in self.nodes:
            for b in self.nodes:
                if a != b:
                    n1, n2 = self.nodes[a], self.nodes[b]
                    rr, cc, ts = self.cells(n1['lon'], n1['lat'], n2['lon'], n2['lat'])
                    heights = self.dem[rr, cc]
                    if np.any(heights == self.dem_data['nodata'].item()): raise ValueError('NoData along leg')
                    top = float(heights.max()) + 50
                    z1 = n1['z'] + (0 if a == 'O01' else 30)
                    z2 = n2['z'] + (0 if b == 'O01' else 30)
                    if top < max(z1, z2): raise ValueError('巡航高度低于端点作业高度，需检查数据')
                    distance = GEOD.inv(n1['lon'], n1['lat'], n2['lon'], n2['lat'])[2]
                    self.legs[a,b] = dict(origin=a, destination=b, distance=distance, cruise_z=top,
                        climb=top-z1, descent=top-z2, cells=len(rr), dem_max=top-50)

    def cells(self, x0, y0, x1, y1):
        """将直线在每条像元边界处切分，取各段所在像元；不使用稀疏采样。"""
        dx, _, ox, _, dy, oy = self.transform
        c0, c1, r0, r1 = (x0-ox)/dx, (x1-ox)/dx, (y0-oy)/dy, (y1-oy)/dy
        tt = [0., 1.]
        for u,v in [(c0,c1),(r0,r1)]:
            if abs(v-u)>1e-12:
                for k in range(math.floor(min(u,v))+1, math.ceil(max(u,v))):
                    t=(k-u)/(v-u)
                    if 0<t<1: tt.append(t)
        ts=np.unique(tt); mids=(ts[:-1]+ts[1:])/2
        points=np.r_[0.,mids,1.]
        rr=np.floor(r0+points*(r1-r0)).astype(int)
        cc=np.floor(c0+points*(c1-c0)).astype(int)
        if (rr.min()<0 or cc.min()<0 or rr.max()>=self.dem.shape[0] or cc.max()>=self.dem.shape[1]):
            raise ValueError('航段超出 DEM 范围')
        return rr,cc,points

    def energy(self, g, a, b, q):
        d = self.drones[g]; leg = self.legs[a,b]
        if q < -1e-7 or q>d.capacity+1e-7: return math.inf
        q=max(0.,q)
        eqrange=d.range0-(d.range0-d.rangeF)*(q/d.capacity)**1.5
        return d.battery*leg['distance']/eqrange+(d.mass+q)*9.81*leg['climb']/(d.efficiency*3.6e6)

    def flight_time(self,g,a,b):
        d=self.drones[g]; leg=self.legs[a,b]
        return leg['climb']/d.up+leg['distance']/d.speed+leg['descent']/d.down

    def charge_time(self,g,soc):
        d=self.drones[g]
        return d.charge_full*(0.65*(0.9-soc)/0.9+0.35 if soc<0.9 else 0.35*(1-soc)/0.1)

    def safe_payload(self,g,s,reserve=None):
        d=self.drones[g]; reserve=d.reserve if reserve is None else reserve
        f=lambda q:self.energy(g,'O01',s,q)+self.energy(g,s,'O01',0)-(1-reserve)*d.battery
        if f(0)>0: return None
        if f(d.capacity)<=0: return d.capacity
        return float(brentq(f,0,d.capacity,xtol=1e-10))

    def route(self,g,ids,order=None,reserve=None):
        ids=tuple(sorted(ids)); boxes=[self.boxes[i] for i in ids]; d=self.drones[g]
        if not boxes: return None
        sites=sorted({b.site for b in boxes})
        order=tuple(sites if order is None else order)
        if sorted(order)!=sites: raise ValueError('Each visited site must occur once and have a delivery')
        mass=sum(b.mass for b in boxes); volume=sum(b.volume for b in boxes)
        if mass>d.capacity+1e-8 or volume>d.volume+1e-8: return None
        t=d.prep+d.load*len(ids); e=0.; q=mass; a='O01'; completion={}; legs=[]
        for s in order+('O01',):
            dt=self.flight_time(g,a,s); de=self.energy(g,a,s,q)
            legs.append(dict(origin=a,destination=s,load=q,start_offset=t,end_offset=t+dt,energy=de))
            t+=dt; e+=de
            if s!='O01':
                delivered=[b for b in boxes if b.site==s]
                t+=d.service+d.unload*len(delivered)
                for b in delivered: completion[b.id]=t
                q-=sum(b.mass for b in delivered)
            a=s
        rho=d.reserve if reserve is None else reserve
        if e>(1-rho)*d.battery+1e-9: return None
        return dict(g=g,boxes=list(ids),order=list(order),mass=mass,volume=volume,duration=t,
                    flight=sum(l['end_offset']-l['start_offset'] for l in legs),energy=e,soc=1-e/d.battery,
                    charge=self.charge_time(g,1-e/d.battery),completion=completion,legs=legs,
                    latest_start=min(self.boxes[b].hard-v for b,v in completion.items()))

    def audit_inputs(self):
        assert len(self.nodes)==16 and len(self.boxes)==80 and sum(d.count for d in self.drones.values())==8
        aggregate=Counter((b.site,b.category) for b in self.boxes.values())
        demand=list(workbook('物资需求与配送时限.xlsx')['数据'].values)[1:]
        errors=[]
        for r in demand:
            if r[0] and r[0] in self.sites and aggregate[r[0],r[1]]!=r[2]: errors.append(str(r))
        if errors: raise ValueError(errors)
        rows=[]
        for s,n in self.nodes.items():
            rr,cc,_=self.cells(n['lon'],n['lat'],n['lon'],n['lat'])
            rows.append(dict(**n,dem_height=float(self.dem[rr[0],cc[0]]),difference=n['z']-float(self.dem[rr[0],cc[0]])))
        csv('data_audit/node_elevations.csv',rows)
        csv('data_audit/legs.csv',list(self.legs.values()))
        csv('data_audit/boxes.csv',[dict(**asdict(b),hard_deadline=b.hard) for b in self.boxes.values()])
        csv('data_audit/drones.csv',[asdict(d) for d in self.drones.values()])
        manifest={str(p.relative_to(RAW)):hashlib.sha256(p.read_bytes()).hexdigest() for p in RAW.rglob('*') if p.is_file()}
        dump(RESULTS/'data_audit/input_sha256.json',manifest)
        return dict(nodes=len(self.nodes),boxes=len(self.boxes),mass=sum(b.mass for b in self.boxes.values()),
                    volume=sum(b.volume for b in self.boxes.values()),hard_boxes=sum(math.isfinite(b.hard) for b in self.boxes.values()),
                    dem_shape=self.dem.shape,dem_nodata=int(np.sum(self.dem==self.dem_data['nodata'].item())))

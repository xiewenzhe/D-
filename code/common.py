"""Shared authoritative inputs, DEM geometry and transport physics for D question."""
from __future__ import annotations
from pathlib import Path
from collections import Counter
from functools import lru_cache
import math
import openpyxl
import numpy as np
import tifffile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "数据" / "无人机应急物资运输基础数据"
KINDS = ("MED", "WAT", "FOD", "HYG")
G = 9.81
EPS = 1e-8


def workbook(part):
    path = next(DATA.glob(f"*{part}*.xlsx"))
    return openpyxl.load_workbook(path, data_only=True, read_only=True)


def read_inputs():
    w = workbook("调度中心")
    rows = list(w["数据"].values)
    nodes = {r[0]: {"id": r[0], "name": r[1], "lon": float(r[2]), "lat": float(r[3]), "z": float(r[4])}
             for r in [rows[2], *rows[6:21]]}
    w.close()
    w = workbook("物资需求")
    rows = list(w["逐箱货箱清单"].values)
    boxes = {r[0]: {"id": r[0], "area": r[1], "kind": r[0].split("-")[1],
                     "mass": float(r[3]), "volume": float(r[4]), "first": r[5] == "是",
                     "deadline": None if r[6] is None else float(r[6]),
                     "desired": None if r[7] is None else float(r[7]), "priority": float(r[8])}
             for r in rows[1:]}
    w.close()
    w = workbook("运输无人机")
    rows = list(w["数据"].values)
    names = ("id", "name", "empty_mass", "capacity", "volume", "speed", "range_empty",
             "range_full", "battery", "reserve_pct", "prepare", "load_per_box", "handover",
             "handover_per_box", "up_speed", "down_speed", "eta", "descent_eta")
    models = {r[0]: dict(zip(names, r)) for r in rows[2:5]}
    drones = {r[0]: r[1] for r in rows[8:16]}
    batteries = {r[0]: {"count": int(r[1]), "full_charge": float(r[2])} for r in rows[19:22]}
    w.close()
    w = workbook("中继无人机")
    rows = list(w["数据"].values)
    rn = ("id", "name", "empty_mass", "module_mass", "takeoff_mass", "speed", "cruise_power",
          "battery", "reserve_pct", "prepare", "link_time", "turnaround", "up_speed", "down_speed",
          "eta", "descent_eta", "hover_power", "comm_power", "max_agl")
    relay_model = dict(zip(rn, rows[2]))
    relays = [r[0] for r in rows[6:8]]
    relay_energy = {"count": int(rows[11][1]), "full_charge": float(rows[11][2])}
    w.close()
    w = workbook("通信链路")
    rows = list(w["数据"].values)
    comm = {"freq_mhz": float(rows[2][4]), "system_loss_db": float(rows[3][4]),
            "obstruction_db": float(rows[4][4]), "sensitivity_dbm": float(rows[5][4]),
            "margin_db": float(rows[6][4]), "transport": (float(rows[7][4]), float(rows[8][4])),
            "relay_access": (float(rows[9][4]), float(rows[10][4])),
            "relay_backhaul": (float(rows[11][4]), float(rows[12][4])),
            "gateway": (float(rows[13][4]), float(rows[14][4])), "gateway_agl": float(rows[15][4])}
    w.close()
    assert len(nodes) == 16 and len(boxes) == 80 and len(drones) == 8 and len(relays) == 2
    assert len(set(boxes)) == len(boxes)
    return nodes, boxes, models, drones, batteries, relay_model, relays, relay_energy, comm


def distance_m(a, b):
    """WGS84 local ellipsoidal distance, accurate at this 30 km scene scale."""
    phi = math.radians((a["lat"] + b["lat"]) / 2)
    e2, major = 6.69437999014e-3, 6378137.0
    merid = major * (1 - e2) / (1 - e2 * math.sin(phi) ** 2) ** 1.5
    prime = major / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    return math.hypot(merid * math.radians(b["lat"] - a["lat"]),
                      prime * math.cos(phi) * math.radians(b["lon"] - a["lon"]))


class Terrain:
    def __init__(self):
        path = next((ROOT / "数据").rglob("*.tif"))
        with tifffile.TiffFile(path) as tf:
            page = tf.pages[0]
            self.grid = page.asarray()
            scale = page.tags["ModelPixelScaleTag"].value
            tie = page.tags["ModelTiepointTag"].value
        self.x0, self.y0, self.dx, self.dy = tie[3], tie[4], scale[0], scale[1]
        assert self.grid.shape == (1309, 1486) and np.isfinite(self.grid).all()

    def rc(self, lon, lat):
        return (self.y0 - lat) / self.dy + 0.5, (lon - self.x0) / self.dx + 0.5

    def elevation(self, lon, lat):
        r, c = self.rc(lon, lat)
        ir, ic = math.floor(r), math.floor(c)
        if not (0 <= ir < self.grid.shape[0] and 0 <= ic < self.grid.shape[1]):
            raise ValueError("Point outside DEM")
        value = float(self.grid[ir, ic])
        if value == -32767:
            raise ValueError("DEM nodata")
        return value

    @lru_cache(maxsize=20000)
    def cells(self, lon1, lat1, lon2, lat2):
        r0, c0 = self.rc(lon1, lat1)
        r1, c1 = self.rc(lon2, lat2)
        dr, dc = r1 - r0, c1 - c0
        ts = [0.0, 1.0]
        for p, q in ((r0, r1), (c0, c1)):
            if abs(q - p) > 1e-14:
                ts += [(k - p) / (q - p) for k in range(math.ceil(min(p, q)), math.floor(max(p, q)) + 1)
                       if 0 < (k - p) / (q - p) < 1]
        ts = sorted(set(ts))
        hits = set()
        for t in [*ts, *((a + b) / 2 for a, b in zip(ts[:-1], ts[1:]))]:
            rr, cc = r0 + dr * t, c0 + dc * t
            def idx(x):
                k = round(x)
                return (k - 1, k) if abs(x - k) < 1e-9 else (math.floor(x),)
            for r in idx(rr):
                for c in idx(cc):
                    if not (0 <= r < self.grid.shape[0] and 0 <= c < self.grid.shape[1]):
                        raise ValueError("Segment outside DEM")
                    hits.add((r, c))
        return tuple(sorted(hits))

    @lru_cache(maxsize=20000)
    def high(self, lon1, lat1, lon2, lat2):
        return max(float(self.grid[r, c]) for r, c in self.cells(lon1, lat1, lon2, lat2))


class Physics:
    def __init__(self, nodes, terrain):
        self.nodes, self.terrain = nodes, terrain
        self.legs = {}
        for a in nodes:
            for b in nodes:
                if a != b:
                    self.legs[a, b] = self.make_leg(nodes[a], nodes[b], a, b)

    def make_leg(self, a, b, aid=None, bid=None):
        z1 = a["z"] + (0 if aid == "O01" else 30 if aid is not None else 0)
        z2 = b["z"] + (0 if bid == "O01" else 30 if bid is not None else 0)
        high = self.terrain.high(a["lon"], a["lat"], b["lon"], b["lat"])
        cruise = high + 50
        up, down = cruise - z1, cruise - z2
        if up < -EPS or down < -EPS:
            raise ValueError(f"Cruise lower than endpoint: {aid}, {bid}")
        return {"from": aid, "to": bid, "distance": distance_m(a, b), "cruise": cruise,
                "up": up, "down": down, "start_z": z1, "end_z": z2,
                "lon1": a["lon"], "lat1": a["lat"], "lon2": b["lon"], "lat2": b["lat"]}

    def transport_leg(self, leg, model, payload):
        g = model
        if payload < -EPS or payload > g["capacity"] + EPS:
            raise ValueError("Payload outside rating")
        L = g["range_empty"] - (g["range_empty"] - g["range_full"]) * (payload / g["capacity"]) ** 1.5
        horizontal = g["battery"] * leg["distance"] / L
        climb = G * (g["empty_mass"] + payload) * leg["up"] / (3.6e6 * g["eta"])
        duration = leg["up"] / g["up_speed"] + leg["distance"] / g["speed"] + leg["down"] / g["down_speed"]
        return horizontal + climb, duration

    def evaluate_route(self, model, boxes, order):
        """Order is a tuple of distinct area IDs; all named boxes at each area are handed over there."""
        g = model
        selected = list(boxes.values())
        mass = sum(b["mass"] for b in selected)
        volume = sum(b["volume"] for b in selected)
        if mass > g["capacity"] + EPS or volume > g["volume"] + EPS:
            return None
        if set(order) != {b["area"] for b in selected} or len(order) != len(set(order)):
            return None
        prep = g["prepare"] + len(selected) * g["load_per_box"]
        elapsed = prep
        remaining = mass
        energy = 0.0
        stages, deliveries = [], {}
        path = ("O01", *order, "O01")
        for a, b in zip(path[:-1], path[1:]):
            leg = self.legs[a, b]
            e, dur = self.transport_leg(leg, g, remaining)
            stages.append({"kind": "flight", "from": a, "to": b, "begin": elapsed,
                           "end": elapsed + dur, "payload": remaining, "energy": e})
            energy += e
            elapsed += dur
            if b != "O01":
                stop = [box for box in selected if box["area"] == b]
                service = g["handover"] + len(stop) * g["handover_per_box"]
                stages.append({"kind": "handover", "area": b, "begin": elapsed, "end": elapsed + service})
                elapsed += service
                for box in stop:
                    deliveries[box["id"]] = elapsed
                remaining -= sum(box["mass"] for box in stop)
        assert abs(remaining) < EPS
        if energy > g["battery"] * (1 - g["reserve_pct"] / 100) + EPS:
            return None
        return {"order": list(order), "boxes": sorted(boxes), "mass": mass, "volume": volume,
                "energy": energy, "soc": 1 - energy / g["battery"], "prep": prep,
                "duration": elapsed, "flight_start": prep, "delivery_offsets": deliveries,
                "stages": stages, "distance": sum(self.legs[a, b]["distance"] for a, b in zip(path[:-1], path[1:]))}


def charge_seconds(soc, full):
    if not 0 <= soc <= 1 + EPS:
        raise ValueError("SOC outside [0,1]")
    if soc < 0.9:
        return full * (0.65 * (0.9 - soc) / 0.9 + 0.35)
    return full * 0.35 * (1 - soc) / 0.1

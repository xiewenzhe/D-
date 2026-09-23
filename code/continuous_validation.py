"""Conservative continuous-time communication certificates over piecewise-affine flight.

The swept LOS to a fixed provider lies in the 3-D triangle formed by the
two moving endpoints and the provider. Clip that triangle against every
intersected DEM cell; the minimum clipped vertex altitude bounds every ray.
A failed bound is UNKNOWN, never a certified outage. Recursively subdivide.
Certificates are relative to the supplied piecewise-constant DEM and physics,
with explicit numerical guard bands, not to unmodelled real-world propagation.
"""
from __future__ import annotations
from collections import Counter
import math
from time import perf_counter
from common import EPS
from problem3 import (transport_position, gateway, link, link_limit,
                      free_space_loss, los_obstructed_exact)

DISTANCE_GUARD_M = 1e-7
HEIGHT_GUARD_M = 1e-6
MARGIN_GUARD_DB = 1e-7
CELL_GUARD = 1e-10


def distance_upper(a0, a1, b):
    # M(phi) increases with |phi|, and N(phi)*cos(phi) decreases with |phi|.
    # Bound both coefficients and both coordinate differences independently.
    lo, hi = sorted((math.radians((a0["lat"] + b["lat"]) / 2),
                     math.radians((a1["lat"] + b["lat"]) / 2)))
    least = 0.0 if lo <= 0 <= hi else min(abs(lo), abs(hi))
    greatest = max(abs(lo), abs(hi))
    e2, major = 6.69437999014e-3, 6378137.0
    merid = major * (1-e2) / (1-e2 * math.sin(greatest)**2)**1.5
    east = major * math.cos(least) / math.sqrt(1-e2 * math.sin(least)**2)
    dlat = max(abs(a["lat"]-b["lat"]) for a in (a0,a1)) * math.pi/180
    dlon = max(abs(a["lon"]-b["lon"]) for a in (a0,a1)) * math.pi/180
    dz = max(abs(a["z"]-b["z"]) for a in (a0,a1))
    return math.sqrt((merid*dlat)**2 + (east*dlon)**2 + dz**2) + DISTANCE_GUARD_M


def clip(poly, axis, bound, keep_above):
    if not poly:
        return []
    result = []
    previous = poly[-1]
    old = previous[axis] >= bound if keep_above else previous[axis] <= bound
    for current in poly:
        inside = current[axis] >= bound if keep_above else current[axis] <= bound
        if inside != old:
            f = (bound-previous[axis])/(current[axis]-previous[axis])
            result.append(tuple(previous[j]+f*(current[j]-previous[j]) for j in range(3)))
        if inside:
            result.append(current)
        previous, old = current, inside
    return result


def swept_clear(a0, a1, b, terrain):
    triangle = [(*terrain.rc(p["lon"],p["lat"]),p["z"]) for p in (a0,a1,b)]
    first = math.floor(min(p[0] for p in triangle)-CELL_GUARD)
    last = math.floor(max(p[0] for p in triangle)+CELL_GUARD)
    cells = 0
    for row in range(first,last+1):
        strip = clip(triangle,0,row-CELL_GUARD,True)
        strip = clip(strip,0,row+1+CELL_GUARD,False)
        if not strip:
            continue
        left = math.floor(min(p[1] for p in strip)-CELL_GUARD)
        right = math.floor(max(p[1] for p in strip)+CELL_GUARD)
        if not (0 <= row < terrain.grid.shape[0] and 0 <= left <= right < terrain.grid.shape[1]):
            return False,cells
        for col in range(left,right+1):
            polygon = clip(strip,1,col-CELL_GUARD,True)
            polygon = clip(polygon,1,col+1+CELL_GUARD,False)
            if not polygon:
                continue
            cells += 1
            ground = float(terrain.grid[row,col])
            if ground == -32767 or ground > min(p[2] for p in polygon)-HEIGHT_GUARD_M:
                return False,cells
    return True,cells


def link_bound(a0,a1,b,btype,physics,comm):
    limit = link_limit("transport",btype,comm)
    loss = free_space_loss(distance_upper(a0,a1,b)/1000,comm)
    blocked_margin = limit-loss-comm["obstruction_db"]
    if blocked_margin >= MARGIN_GUARD_DB:
        return True,blocked_margin,"obstruction_worst_case",0
    if limit-loss < MARGIN_GUARD_DB:
        return False,limit-loss,"distance_bound",0
    clear,cells = swept_clear(a0,a1,b,physics.terrain)
    return clear,limit-loss,"swept_dem_clearance",cells


def breakpoints(route,missions,physics,models,initial_step):
    points = set()
    g = models[route["model"]]
    for stage in route["stages"]:
        begin,end = route["start"]+stage["begin"],route["start"]+stage["end"]
        points.update((begin,end))
        if stage["kind"] == "flight":
            leg = physics.legs[stage["from"],stage["to"]]
            top = begin+leg["up"]/g["up_speed"]
            descend = top+leg["distance"]/g["speed"]
            points.update((top,descend))
    first,last = min(points),max(points)
    for mission in missions:
        for event in (mission["service_start"],mission["service_end"]):
            if first < event < last:
                points.add(event)
    coarse = sorted(points)
    for start,end in zip(coarse,coarse[1:]):
        n=max(1,math.ceil((end-start)/initial_step))
        points.update(start+(end-start)*j/n for j in range(1,n))
    return sorted(points)


def certify_schedule(schedule,missions,physics,models,comm,initial_step=30,
                     min_step=1e-4,allowed_support=None):
    started=perf_counter()
    gate=gateway(physics,comm)
    backhaul=[]
    for m in missions:
        good,margin,_=link(m["site"],"relay_backhaul",gate,"gateway",
                           physics.terrain,comm,los_test=los_obstructed_exact)
        backhaul.append((good,margin))
    records,unresolved=[],[]
    counts=Counter()
    max_depth=0
    for route in schedule:
        points=breakpoints(route,missions,physics,models,initial_step)
        def visit(left,right,depth):
            nonlocal max_depth
            max_depth=max(max_depth,depth)
            a0=transport_position(route,left,physics,models)
            a1=transport_position(route,right,physics,models)
            providers=[(-1,gate,"gateway",math.inf)]
            for j,m in enumerate(missions):
                if allowed_support is not None and route["sortie"] not in allowed_support[j]:
                    continue
                if (backhaul[j][0] and m["service_start"] <= left+1e-10
                        and right <= m["service_end"]+1e-10):
                    providers.append((j,m["site"],"relay_access",backhaul[j][1]))
            for j,target,kind,back_margin in providers:
                ok,margin,method,cells=link_bound(a0,a1,target,kind,physics,comm)
                counts["dem_cells_examined"]+=cells
                if ok:
                    records.append({"sortie":route["sortie"],"start_s":left,"end_s":right,
                                    "mode":"direct" if j<0 else "relay","mission":j,
                                    "relay":"" if j<0 else missions[j]["relay"],
                                    "margin_lower_bound_db":min(margin,back_margin),"method":method})
                    counts[method]+=1
                    return
            if right-left <= min_step:
                unresolved.append({"sortie":route["sortie"],"start_s":left,"end_s":right})
                return
            middle=(left+right)/2
            visit(left,middle,depth+1)
            visit(middle,right,depth+1)
        for left,right in zip(points,points[1:]):
            if right-left > 1e-10:
                visit(left,right,0)
    certified=sum(r["end_s"]-r["start_s"] for r in records)
    required=sum(r["duration"]-r["stages"][0]["begin"] for r in schedule)
    unknown=sum(r["end_s"]-r["start_s"] for r in unresolved)
    assert abs(certified+unknown-required) < 1e-5
    return {"passed":not unresolved,"continuous_validation_passed":not unresolved,
            "scope":"piecewise-affine flight, supplied piecewise-constant DEM, bidirectional link budget",
            "communication_margin_db":comm["margin_db"],
            "initial_step_s":initial_step,"minimum_subdivision_s":min_step,
            "certified_intervals":len(records),"unresolved_intervals":unresolved,
            "certified_duration_s":certified,"required_duration_s":required,
            "minimum_margin_lower_bound_db":min((r["margin_lower_bound_db"] for r in records),default=None),
            "maximum_subdivision_depth":max_depth,"method_counts":dict(counts),
            "distance_guard_m":DISTANCE_GUARD_M,"height_guard_m":HEIGHT_GUARD_M,
            "margin_guard_db":MARGIN_GUARD_DB,"elapsed_s":perf_counter()-started,
            "intervals":records}


def support_rows(certificate):
    assert certificate["passed"]
    return [{"sortie":r["sortie"],"time_s":(r["start_s"]+r["end_s"])/2,
             "mode":r["mode"],"relay":r["relay"]} for r in certificate["intervals"]]

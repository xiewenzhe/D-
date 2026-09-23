"""Terrain-aware bidirectional communication and relay planning for Problem 3."""
from __future__ import annotations
from collections import defaultdict
import math
import numpy as np
from common import G, EPS, distance_m, charge_seconds


def transport_position(route, absolute_t, physics, models):
    rel = absolute_t - route["start"]
    g = models[route["model"]]
    for st in route["stages"]:
        if st["begin"] - EPS <= rel <= st["end"] + EPS:
            if st["kind"] == "handover":
                node = physics.nodes[st["area"]]
                return {"lon": node["lon"], "lat": node["lat"], "z": node["z"] + 30}
            leg = physics.legs[st["from"], st["to"]]
            t = max(0.0, min(st["end"] - st["begin"], rel - st["begin"]))
            up_t = leg["up"] / g["up_speed"]
            cruise_t = leg["distance"] / g["speed"]
            if t <= up_t + EPS:
                return {"lon": leg["lon1"], "lat": leg["lat1"], "z": leg["start_z"] + g["up_speed"] * t}
            if t <= up_t + cruise_t + EPS:
                f = min(1.0, max(0.0, (t - up_t) / cruise_t))
                return {"lon": leg["lon1"] + f * (leg["lon2"] - leg["lon1"]),
                        "lat": leg["lat1"] + f * (leg["lat2"] - leg["lat1"]), "z": leg["cruise"]}
            return {"lon": leg["lon2"], "lat": leg["lat2"],
                    "z": max(leg["end_z"], leg["cruise"] - g["down_speed"] * (t - up_t - cruise_t))}
    raise ValueError(f"Time {absolute_t} outside transport operation {route['sortie']}")


def los_obstructed(a, b, terrain):
    horizontal = distance_m(a, b)
    count = max(2, math.ceil(horizontal / 7.5))
    f = np.arange(1, count, dtype=float) / count
    lon = a["lon"] + f * (b["lon"] - a["lon"])
    lat = a["lat"] + f * (b["lat"] - a["lat"])
    rr = np.floor((terrain.y0 - lat) / terrain.dy + 0.5).astype(int)
    cc = np.floor((lon - terrain.x0) / terrain.dx + 0.5).astype(int)
    if np.any(rr < 0) or np.any(rr >= terrain.grid.shape[0]) or np.any(cc < 0) or np.any(cc >= terrain.grid.shape[1]):
        raise ValueError("Communication LOS outside DEM")
    zline = a["z"] + f * (b["z"] - a["z"])
    return bool(np.any(terrain.grid[rr, cc] > zline + 1e-6))


def link_limit(atype, btype, comm):
    p1, g1 = comm[atype]
    p2, g2 = comm[btype]
    threshold = comm["sensitivity_dbm"] + comm["margin_db"]
    return min(p1 + g1 + g2 - comm["system_loss_db"] - threshold,
               p2 + g2 + g1 - comm["system_loss_db"] - threshold)


def free_space_loss(distance_km, comm):
    return 32.45 + 20 * math.log10(comm["freq_mhz"]) + 20 * math.log10(max(0.001, distance_km))


def link(a, atype, b, btype, terrain, comm, los_test=None):
    horizontal = distance_m(a, b)
    distance_km = math.hypot(horizontal, a["z"] - b["z"]) / 1000
    limit = link_limit(atype, btype, comm)
    obstructed = (los_test or los_obstructed)(a, b, terrain)
    path_loss = free_space_loss(distance_km, comm)
    path_loss += comm["obstruction_db"] if obstructed else 0
    return path_loss <= limit + 1e-9, limit - path_loss, obstructed


def gateway(physics, comm):
    home = physics.nodes["O01"]
    return {"lon": home["lon"], "lat": home["lat"], "z": home["z"] + comm["gateway_agl"]}


def sample_times(route, step=5):
    times = set()
    for st in route["stages"]:
        left, right = route["start"] + st["begin"], route["start"] + st["end"]
        times.add(left)
        times.add(right)
        n = max(1, math.ceil((right - left) / step))
        times.update(left + (right - left) * j / n for j in range(1, n))
    return sorted(times)


def direct_samples(schedule, physics, models, comm, step=5):
    gate = gateway(physics, comm)
    out = []
    for route in schedule:
        for t in sample_times(route, step):
            pos = transport_position(route, t, physics, models)
            direct, margin, obstruction = link(pos, "transport", gate, "gateway", physics.terrain, comm)
            out.append({"sortie": route["sortie"], "t": t, "position": pos,
                        "direct": direct, "margin_db": margin, "obstructed": obstruction})
    return out


def _base_sites(physics, relay_model, comm):
    """DEM sites at each task node and selected midpoints; altitude is as high as allowed."""
    terrain = physics.terrain
    raw = []
    for nid, n in physics.nodes.items():
        raw.append((nid, n["lon"], n["lat"]))
    home = physics.nodes["O01"]
    for nid, n in physics.nodes.items():
        if nid != "O01":
            raw.append((f"M{nid}", (home["lon"] + n["lon"]) / 2, (home["lat"] + n["lat"]) / 2))
    sites = []
    for sid, lon, lat in raw:
        ground = terrain.elevation(lon, lat)
        z = ground + relay_model["max_agl"]
        site = {"id": sid, "lon": lon, "lat": lat, "z": z, "ground": ground}
        if sid == "O01":
            distance = 0.0
            high = ground
        else:
            high = terrain.high(home["lon"], home["lat"], lon, lat)
            distance = distance_m(home, site)
        # Horizontal cruise is high+50. If hover is higher, finish with a vertical ascent.
        # Total vertical climb/descent equals a transfer peak of max(cruise, hover altitude).
        cruise = high + 50
        peak = max(cruise, z)
        up = peak - home["z"]
        down = peak - z
        travel = up / relay_model["up_speed"] + distance / relay_model["speed"] + down / relay_model["down_speed"]
        ret = down / relay_model["up_speed"] + distance / relay_model["speed"] + up / relay_model["down_speed"]
        flight_energy = 2 * relay_model["cruise_power"] * distance / relay_model["speed"] / 3600
        flight_energy += G * relay_model["takeoff_mass"] * (up + down) / (3.6e6 * relay_model["eta"])
        site.update({"outbound_s": travel, "return_s": ret, "flight_energy": flight_energy})
        backhaul, margin, obstruction = link(site, "relay_backhaul", gateway(physics, comm), "gateway", terrain, comm)
        site.update({"backhaul": backhaul, "backhaul_margin_db": margin,
                     "backhaul_obstructed": obstruction})
        if backhaul and flight_energy <= relay_model["battery"] * (1 - relay_model["reserve_pct"] / 100) + EPS:
            sites.append(site)
    return sites


def candidate_sites(physics, relay_model, comm, height_levels=(0.25, 0.50, 0.75, 1.0)):
    sites = _base_sites(physics, relay_model, comm)
    terrain = physics.terrain
    home = physics.nodes["O01"]
    extra = []
    for nid, n in physics.nodes.items():
        if nid == "O01":
            continue
        for frac in (0.25, 0.75):
            extra.append((f"L{nid}-{frac}", home["lon"] + frac * (n["lon"] - home["lon"]),
                          home["lat"] + frac * (n["lat"] - home["lat"])))
        for letter, dx, dy in (("N", 0, .006), ("S", 0, -.006), ("E", .006, 0), ("W", -.006, 0)):
            extra.append((f"{letter}{nid}", n["lon"] + dx, n["lat"] + dy))
    gate = gateway(physics, comm)
    for sid, lon, lat in extra:
        try:
            ground = terrain.elevation(lon, lat)
            site = {"id": sid, "lon": lon, "lat": lat, "z": ground + relay_model["max_agl"], "ground": ground}
            high = terrain.high(home["lon"], home["lat"], lon, lat)
            dist = distance_m(home, site)
            # The endpoint may require an extra vertical ascent after horizontal cruise.
            cruise = high + 50
            peak = max(cruise, site["z"])
            up, down = peak - home["z"], peak - site["z"]
            travel = up / relay_model["up_speed"] + dist / relay_model["speed"] + down / relay_model["down_speed"]
            ret = down / relay_model["up_speed"] + dist / relay_model["speed"] + up / relay_model["down_speed"]
            e = 2 * relay_model["cruise_power"] * dist / relay_model["speed"] / 3600
            e += G * relay_model["takeoff_mass"] * (up + down) / (3.6e6 * relay_model["eta"])
            ok, margin, obstruction = link(site, "relay_backhaul", gate, "gateway", terrain, comm)
            if ok and e <= relay_model["battery"] * (1 - relay_model["reserve_pct"] / 100) + EPS:
                site.update({"outbound_s": travel, "return_s": ret, "flight_energy": e,
                             "backhaul": True, "backhaul_margin_db": margin,
                             "backhaul_obstructed": obstruction})
                sites.append(site)
        except ValueError:
            continue
    # Evaluate lower hovering altitudes at the original service-area and midpoint sites.
    # The original full-height candidates remain available for feasibility.
    if any(level != 1.0 for level in height_levels):
        anchors = [site for site in sites if site["id"] in physics.nodes or
                   site["id"].startswith("M")]
        for anchor in anchors:
            for level in height_levels:
                if level == 1.0:
                    continue
                z = anchor["ground"] + level * relay_model["max_agl"]
                site = dict(anchor, id=f"{anchor['id']}-H{int(level*100)}", z=z)
                try:
                    high = terrain.high(home["lon"], home["lat"], site["lon"], site["lat"])
                    dist = distance_m(home, site)
                    peak = max(high + 50, z)
                    up, down = peak - home["z"], peak - z
                    site["outbound_s"] = (up / relay_model["up_speed"] + dist / relay_model["speed"]
                                          + down / relay_model["down_speed"])
                    site["return_s"] = (down / relay_model["up_speed"] + dist / relay_model["speed"]
                                        + up / relay_model["down_speed"])
                    site["flight_energy"] = (2 * relay_model["cruise_power"] * dist /
                                              relay_model["speed"] / 3600
                                              + G * relay_model["takeoff_mass"] * (up + down) /
                                              (3.6e6 * relay_model["eta"]))
                    ok, margin, obstruction = link(site, "relay_backhaul", gate, "gateway", terrain, comm)
                    if ok and site["flight_energy"] <= relay_model["battery"] * (
                            1 - relay_model["reserve_pct"] / 100) + EPS:
                        site.update({"backhaul": True, "backhaul_margin_db": margin,
                                     "backhaul_obstructed": obstruction})
                        sites.append(site)
                except ValueError:
                    continue
    return sites

# Relay missions are planned after the transport route list is known.  The
# constructive search delays transport starts where needed and checks every
# sampled transport position against a simultaneously active bidirectional link.
from problem2 import hard_due

BUFFER = 12.0


def profiles(routes, physics, models, sites, comm, step=5):
    gate = gateway(physics, comm)
    result = {}
    for route in routes:
        zero = dict(route, start=0.0, end=route["duration"])
        gaps = []
        for t in sample_times(zero, step):
            pos = transport_position(zero, t, physics, models)
            ok, _, _ = link(pos, "transport", gate, "gateway", physics.terrain, comm)
            if not ok:
                gaps.append((t, pos))
        cover = {}
        for site in sites:
            cover[site["id"]] = {j for j, (_, pos) in enumerate(gaps)
                                  if link(pos, "transport", site, "relay_access", physics.terrain, comm)[0]}
        result[route["sortie"]] = {"gaps": gaps, "cover": cover}
    return result


def hover_limit(site, relay_model):
    capacity = relay_model["battery"] * (1 - relay_model["reserve_pct"] / 100)
    return (capacity - site["flight_energy"]) * 3600 / (relay_model["hover_power"] + relay_model["comm_power"]) - relay_model["link_time"]


def update_mission(mission, new_end, relay_model, energy_stock):
    mission["service_end"] = max(mission["service_end"], new_end)
    duration = relay_model["link_time"] + mission["service_end"] - mission["service_start"]
    mission["energy"] = mission["site"]["flight_energy"] + duration * (relay_model["hover_power"] + relay_model["comm_power"]) / 3600
    mission["soc"] = 1 - mission["energy"] / relay_model["battery"]
    if mission["soc"] + EPS < relay_model["reserve_pct"] / 100:
        return False
    mission["end"] = mission["service_end"] + mission["site"]["return_s"]
    mission["component_ready"] = mission["end"] + charge_seconds(mission["soc"], energy_stock["full_charge"])
    return True


def new_mission(site, first, last, rid, component, drone_ready, component_ready,
                relay_model, energy_stock):
    approach = relay_model["prepare"] + site["outbound_s"] + relay_model["link_time"]
    launch = max(0.0, drone_ready, component_ready, first - BUFFER - approach)
    service_start = launch + approach
    if service_start > first - BUFFER + EPS:
        return None
    mission = {"relay": rid, "component": component, "site": site, "launch": launch,
               "service_start": service_start, "service_end": last + BUFFER}
    return mission if update_mission(mission, mission["service_end"], relay_model, energy_stock) else None


def _future_site_score(site_id, route_profiles):
    return sum(len(p["cover"][site_id]) for p in route_profiles.values())


def initial_pairs(first_routes, route_profiles, sites, relay_model):
    from itertools import combinations
    all_gaps = []
    for route in first_routes:
        p = route_profiles[route["sortie"]]
        all_gaps += [(route["sortie"], j, t) for j, (t, _) in enumerate(p["gaps"])]
    if not all_gaps:
        return [(None, None)]
    pairs = []
    for a, b in combinations(sites, 2):
        aid, bid = a["id"], b["id"]
        if any(j not in route_profiles[r]["cover"][aid] and j not in route_profiles[r]["cover"][bid]
               for r, j, _ in all_gaps):
            continue
        if min(t for _, _, t in all_gaps) < min(relay_model["prepare"] + x["outbound_s"] + relay_model["link_time"] + BUFFER
                                                for x in (a, b)):
            continue
        score = _future_site_score(aid, route_profiles) + _future_site_score(bid, route_profiles)
        pairs.append((-score, a, b))
    return [(a, b) for _, a, b in sorted(pairs, key=lambda x: x[0])]


def _asset_choice(site, first, last, missions, relays, components, relay_model, energy_stock):
    options = []
    for rid in relays:
        own = [m for m in missions if m["relay"] == rid]
        ready_d = own[-1]["end"] + relay_model["turnaround"] if own else 0.0
        for component, history in components.items():
            ready_e = history[-1]["component_ready"] if history else 0.0
            plan = new_mission(site, first, last, rid, component, ready_d, ready_e, relay_model, energy_stock)
            if plan is not None:
                options.append((plan["end"], plan))
    return min(options, key=lambda x: x[0])[1] if options else None


def _try_existing(profile, start, missions, relay_model, energy_stock):
    gaps = profile["gaps"]
    if not gaps:
        return []
    latest = {}
    for m in missions:
        latest[m["relay"]] = m
    active = list(latest.values())
    if not active:
        return None
    all_idx = set(range(len(gaps)))
    for order in ([active] if len(active) == 1 else [active, list(reversed(active))]):
        assignment = defaultdict(list)
        remaining = set(all_idx)
        for m in order:
            sid = m["site"]["id"]
            available = {j for j in profile["cover"][sid] if start + gaps[j][0] >= m["service_start"] + BUFFER - EPS
                         and start + gaps[j][0] + BUFFER <= m["service_start"] + hover_limit(m["site"], relay_model) + EPS}
            take = remaining & available
            assignment[id(m)] += [start + gaps[j][0] for j in take]
            remaining -= take
        if not remaining:
            return [(m, max(assignment[id(m)]) + BUFFER) for m in order if assignment[id(m)]]
    return None


def validate_joint(schedule, missions, boxes, models, drones, batteries, physics,
                   relay_model, relays, energy_stock, comm, step=2):
    from problem2 import validate as validate_transport
    transport = validate_transport(schedule, boxes, models, drones, batteries, physics)
    for mission in missions:
        site = mission["site"]
        assert mission["relay"] in relays
        assert site["backhaul"]
        assert abs(physics.terrain.elevation(site["lon"], site["lat"]) - site["ground"]) < 1e-6
        assert -EPS <= site["z"] - site["ground"] <= relay_model["max_agl"] + EPS
        backhaul_ok, backhaul_margin, _ = link(
            site, "relay_backhaul", gateway(physics, comm), "gateway", physics.terrain, comm)
        assert backhaul_ok and backhaul_margin >= -EPS
        assert mission["service_start"] + EPS >= mission["launch"] + relay_model["prepare"] + site["outbound_s"] + relay_model["link_time"]
        assert abs(mission["end"] - mission["service_end"] - site["return_s"]) < 1e-6
        energy = site["flight_energy"] + (relay_model["link_time"] + mission["service_end"] - mission["service_start"]) * (relay_model["hover_power"] + relay_model["comm_power"]) / 3600
        assert abs(energy - mission["energy"]) < 1e-8
        assert mission["soc"] >= relay_model["reserve_pct"] / 100 - EPS
        assert mission["service_end"] >= mission["service_start"]
        assert mission["launch"] >= -EPS
        assert abs(mission["component_ready"] - mission["end"] - charge_seconds(mission["soc"], energy_stock["full_charge"])) < 1e-6
    for key, cooldown in (("relay", "end"), ("component", "component_ready")):
        by = defaultdict(list)
        for mission in missions:
            by[mission[key]].append(mission)
        for events in by.values():
            events.sort(key=lambda x: x["launch"])
            for previous, following in zip(events[:-1], events[1:]):
                ready = previous[cooldown] + (relay_model["turnaround"] if key == "relay" else 0)
                assert ready <= following["launch"] + EPS, (key, previous["site"]["id"], following["site"]["id"])
    gate = gateway(physics, comm)
    samples = 0
    direct_count = 0
    relayed_count = 0
    coverage_rows = []
    min_margin = math.inf
    for route in schedule:
        check_times = set(sample_times(route, step))
        # Include communication handoff events and both sides of each relay window.
        for mission in missions:
            for event in (mission["service_start"], mission["service_end"]):
                for delta in (-1e-4, 0.0, 1e-4):
                    t = event + delta
                    if route["start"] + route["stages"][0]["begin"] <= t <= route["end"]:
                        check_times.add(t)
        for t in sorted(check_times):
            pos = transport_position(route, t, physics, models)
            direct, margin, _ = link(pos, "transport", gate, "gateway", physics.terrain, comm)
            if direct:
                mode, mid = "direct", ""
                direct_count += 1
                min_margin = min(min_margin, margin)
            else:
                good = []
                for mission in missions:
                    if mission["service_start"] - EPS <= t <= mission["service_end"] + EPS:
                        ok, access_margin, _ = link(pos, "transport", mission["site"], "relay_access", physics.terrain, comm)
                        if ok:
                            good.append((min(access_margin, mission["site"]["backhaul_margin_db"]), mission["relay"], mission))
                if not good:
                    raise AssertionError(("communication break", route["sortie"], t, pos))
                best = max(good, key=lambda x: x[0])
                mode, mid = "relay", best[2]["relay"]
                min_margin = min(min_margin, best[0])
                relayed_count += 1
            samples += 1
            coverage_rows.append({"sortie": route["sortie"], "time_s": t, "mode": mode, "relay": mid,
                                  "lon": pos["lon"], "lat": pos["lat"], "altitude_m": pos["z"]})
    combined = {**transport, "relay_sorties": len(missions),
                "relay_energy_kwh": sum(m["energy"] for m in missions),
                "total_energy_kwh": transport["energy_kwh"] + sum(m["energy"] for m in missions),
                "joint_makespan_s": max(max(r["end"] for r in schedule), max(m["end"] for m in missions)),
                "communication_samples": samples, "direct_samples": direct_count,
                "relayed_samples": relayed_count, "communication_breaks": 0,
                "minimum_link_margin_db": min_margin, "sample_step_s": step,
                "relay_resource_conflicts": 0,
                "sample_validation_step_s": step,
                "continuous_validation_passed": False,
                "transport_gateway_bidirectional": True,
                "transport_relay_bidirectional": True,
                "relay_gateway_bidirectional": True,
                "validation": {"passed": True, "violations": []}}
    return combined, coverage_rows


def los_obstructed_exact(a, b, terrain):
    """Conservative exact DEM-cell intersection test for a 3-D line segment."""
    r0, c0 = terrain.rc(a["lon"], a["lat"])
    r1, c1 = terrain.rc(b["lon"], b["lat"])
    dr, dc = r1 - r0, c1 - c0
    for r, c in terrain.cells(a["lon"], a["lat"], b["lon"], b["lat"]):
        lo, hi = 0.0, 1.0
        for start, delta, lower, upper in ((r0, dr, r, r + 1), (c0, dc, c, c + 1)):
            if abs(delta) < 1e-14:
                if start < lower - 1e-10 or start > upper + 1e-10:
                    hi = -1.0
                    break
            else:
                left, right = sorted(((lower - start) / delta, (upper - start) / delta))
                lo, hi = max(lo, left), min(hi, right)
        if lo > hi + 1e-10:
            continue
        low_z = min(a["z"] + lo * (b["z"] - a["z"]),
                    a["z"] + hi * (b["z"] - a["z"]))
        if float(terrain.grid[r, c]) > low_z + 1e-6:
            return True
    return False

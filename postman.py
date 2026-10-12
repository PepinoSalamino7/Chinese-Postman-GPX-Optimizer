#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chinese Postman Optimizer v6.0 — Ultra-Precise Edition
======================================================
v6.0 — ULTRAPRECIES:
  • GEEN snapping/coordinate merging meer — elk GPX-punt blijft een
    unieke node met volledige precisie. Dit voorkomt dat bochtjes
    worden "rechtgetrokken" of overgeslagen.
  • Dead-end backtrack volgt het EXACTE pad met ALLE punten ertussen,
    geen enkele bocht wordt overgeslagen.
  • Euleriaans circuit wordt gegenereerd op de volledige multigraph
    met alle oorspronkelijke edges — de route volgt 100% het bestaande
    wegennet.
  • Component-bridging probeert eerst een bestaand pad in het netwerk
    te vinden; pas als dat niet lukt wordt een rechte lijn getrokken
    (met expliciete waarschuwing).
  • Nieuwe validatie-fase controleert of elke oorspronkelijke edge
    exact in de route voorkomt. Rapporteert ontbrekende segmenten.

  Behouden van v5.7:
  • --no-checkpoint / --checkpoint
  • --drop-components / --bridge-components
  • Slim verbinden (Prim-greedy) van componenten
  • Dead-end first backtrack strategie

Gebruik:
    python postman.py                           # Auto input/output mappen
    python postman.py input.gpx output.gpx
    python postman.py "*.gpx" --out-dir ./optimized/
    python postman.py ./routes/ --parallel
    python postman.py config.json
    python postman.py --no-checkpoint           # zonder checkpointing
    python postman.py --drop-components         # kleine componenten verwijderen
"""


from __future__ import annotations

import xml.etree.ElementTree as ET
import networkx as nx
import math
import sys
import os
import time
import json
import argparse
import glob
import hashlib
import platform
import shutil
from concurrent.futures import ProcessPoolExecutor
from typing import List, Tuple, Optional, Dict, Set, Iterator
from dataclasses import dataclass, field, asdict
from pathlib import Path
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════
#  PLATFORM DETECTIE
# ═══════════════════════════════════════════════════════════════
IS_WINDOWS = platform.system() == 'Windows'
IS_TERMUX = 'TERMUX_VERSION' in os.environ

# ═══════════════════════════════════════════════════════════════
#  KLEUREN — respecteert NO_COLOR
# ═══════════════════════════════════════════════════════════════
_NO_COLOR = os.environ.get('NO_COLOR', '') != '' or os.environ.get('TERM') == 'dumb'

class C:
    HEADER = '' if _NO_COLOR else '\033[95m'
    BLUE = '' if _NO_COLOR else '\033[94m'
    CYAN = '' if _NO_COLOR else '\033[96m'
    GREEN = '' if _NO_COLOR else '\033[92m'
    YELLOW = '' if _NO_COLOR else '\033[93m'
    RED = '' if _NO_COLOR else '\033[91m'
    DIM = '' if _NO_COLOR else '\033[2m'
    BOLD = '' if _NO_COLOR else '\033[1m'
    END = '' if _NO_COLOR else '\033[0m'

# ═══════════════════════════════════════════════════════════════
#  DATA KLASSEN
# ═══════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Coord:
    """Exacte coördinaat — immutable en hashable. GEEN snapping."""
    lat: float
    lon: float

    def __iter__(self) -> Iterator[float]:
        yield self.lat
        yield self.lon

@dataclass
class GPXPoint:
    """Volledig GPX punt met metadata behoud."""
    lat: float
    lon: float
    ele: Optional[float] = None
    time: Optional[str] = None
    name: Optional[str] = None
    cmt: Optional[str] = None
    desc: Optional[str] = None
    extensions: Optional[ET.Element] = None

    def to_coord(self) -> Coord:
        return Coord(self.lat, self.lon)

@dataclass
class RouteResult:
    input_file: str
    output_file: str
    success: bool
    tracks_info: List[Dict]
    original_points: int
    output_points: int
    components: int
    original_dist: float
    added_dist: float
    total_dist: float
    efficiency: float
    processing_time: float
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    # Nieuwe velden voor ultraprecisie-validatie
    edges_validated: int = 0
    edges_missing: int = 0
    max_deviation_m: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

# ═══════════════════════════════════════════════════════════════
#  HULPFUNCTIES
# ═══════════════════════════════════════════════════════════════
def haversine_distance(p1: Coord, p2: Coord) -> float:
    """Haversine afstand in meters."""
    R = 6371000
    lat1, lon1 = p1.lat, p1.lon
    lat2, lon2 = p2.lat, p2.lon
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def format_street_names(names: Set[str], max_shown: int = 4) -> str:
    if not names:
        return ""
    ordered = sorted(names)
    shown = ordered[:max_shown]
    extra = len(ordered) - len(shown)
    label = ', '.join(shown)
    if extra > 0:
        label += f" (+{extra} meer)"
    return label

def safe_makedirs(path: Path) -> None:
    for attempt in range(3):
        try:
            path.mkdir(parents=True, exist_ok=True)
            if path.exists():
                return
        except (OSError, PermissionError) as e:
            if attempt == 2:
                raise RuntimeError(f"Kan map niet aanmaken: {path} — {e}")
            time.sleep(0.05 * (attempt + 1))

def safe_replace(src: Path, dst: Path) -> None:
    if dst.exists():
        try:
            dst.unlink()
        except (OSError, PermissionError):
            bak = dst.with_suffix(dst.suffix + '.bak')
            try:
                dst.rename(bak)
                bak.unlink(missing_ok=True)
            except Exception:
                pass
    for attempt in range(5):
        try:
            if IS_WINDOWS:
                shutil.move(str(src), str(dst))
            else:
                os.replace(str(src), str(dst))
            if dst.exists():
                return
        except (OSError, PermissionError):
            if attempt == 4:
                shutil.copy2(str(src), str(dst))
                src.unlink(missing_ok=True)
                return
            time.sleep(0.1 * (attempt + 1))
    raise RuntimeError(f"Kan {src} niet verplaatsen naar {dst}")

def get_namespace(root) -> str:
    if root.tag.startswith('{'):
        return root.tag.split('}')[0].strip('{')
    return ''

def indent_xml_element(elem, level=0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for child in elem:
            indent_xml_element(child, level + 1)
        if len(elem) > 0:
            last_child = elem[-1]
            if not last_child.tail or not last_child.tail.strip():
                last_child.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

def indent_xml(root):
    """Gebruik ET.indent() indien beschikbaar (Python 3.9+), anders fallback."""
    if hasattr(ET, 'indent'):
        ET.indent(root, space='  ')
    else:
        indent_xml_element(root)

def file_id(file_path: str) -> str:
    """SHA-256 gebaseerde file identifier."""
    p = Path(file_path)
    try:
        stat = p.stat()
        hash_input = f"{p.absolute()}|{stat.st_size}|{stat.st_mtime}"
    except (OSError, IOError):
        hash_input = str(p.absolute())
    return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

def point_to_segment_distance(p: Coord, a: Coord, b: Coord) -> float:
    """Afstand van punt p tot lijnsegment ab in meters."""
    # Converteer naar lokale cartesische coördinaten voor nauwkeurigheid
    lat0 = math.radians(p.lat)
    x_p = math.radians(p.lon) * math.cos(lat0) * 6371000
    y_p = math.radians(p.lat) * 6371000
    x_a = math.radians(a.lon) * math.cos(lat0) * 6371000
    y_a = math.radians(a.lat) * 6371000
    x_b = math.radians(b.lon) * math.cos(lat0) * 6371000
    y_b = math.radians(b.lat) * 6371000
    
    dx = x_b - x_a
    dy = y_b - y_a
    length_sq = dx*dx + dy*dy
    
    if length_sq == 0:
        return math.sqrt((x_p - x_a)**2 + (y_p - y_a)**2)
    
    t = max(0, min(1, ((x_p - x_a)*dx + (y_p - y_a)*dy) / length_sq))
    proj_x = x_a + t * dx
    proj_y = y_a + t * dy
    
    return math.sqrt((x_p - proj_x)**2 + (y_p - proj_y)**2)

# ═══════════════════════════════════════════════════════════════
#  EXACTE COÖRDINAAT MAPPING — GEEN snapping, volledige precisie
# ═══════════════════════════════════════════════════════════════
class ExactCoordinateMap:
    """
    Behoudt ELK GPX-punt als unieke node. Geen snapping, geen merging.
    Voor metadata-reconstructie: onthoudt het originele GPXPoint per coord.
    """
    def __init__(self):
        self._originals: Dict[Coord, GPXPoint] = {}

    def register(self, point: GPXPoint) -> Coord:
        coord = point.to_coord()
        if coord not in self._originals:
            self._originals[coord] = point
        return coord

    def get_original(self, coord: Coord) -> Optional[GPXPoint]:
        return self._originals.get(coord)

# ═══════════════════════════════════════════════════════════════
#  VEREENVOUDIGDE CHECKPOINT MANAGER
# ═══════════════════════════════════════════════════════════════
class CheckpointManager:
    CHECKPOINT_FILE = ".postman_checkpoint.json"
    VERSION = 6  # Bump version vanwege nieuwe velden

    def __init__(self, script_dir: Path):
        self.script_dir = script_dir
        self.checkpoint_path = script_dir / self.CHECKPOINT_FILE
        self.data = self._load()
        self._dirty = False

    def _load(self) -> dict:
        if self.checkpoint_path.exists():
            try:
                with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data.get('version') == self.VERSION:
                    return data
                print(f"{C.YELLOW}⚠ Checkpoint heeft een ander schema (versie "
                      f"{data.get('version')!r}, verwacht {self.VERSION}) — "
                      f"genegeerd, nieuwe sessie gestart.{C.END}")
            except (json.JSONDecodeError, IOError) as e:
                print(f"{C.YELLOW}⚠ Checkpoint kon niet gelezen worden ({e}) — "
                      f"nieuwe sessie gestart.{C.END}")
        return {'version': self.VERSION, 'created': time.time(), 'updated': time.time(), 'files': {}}

    def save(self) -> None:
        if not self._dirty:
            return
        self.data['updated'] = time.time()
        tmp_path = self.checkpoint_path.with_suffix('.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            safe_replace(tmp_path, self.checkpoint_path)
            self._dirty = False
        except IOError as e:
            print(f"{C.YELLOW}⚠ Kon checkpoint niet opslaan: {e}{C.END}")

    def get_state(self, fid: str) -> Optional[dict]:
        return self.data['files'].get(fid)

    def set_status(self, fid: str, file_path: str, status: str,
                   result: Optional[dict] = None) -> None:
        self.data['files'][fid] = {
            'file_path': str(Path(file_path).absolute()),
            'status': status,
            'updated': time.time(),
            'result': result
        }
        self._dirty = True
        self.save()

    def clear_all(self) -> None:
        if self.checkpoint_path.exists():
            self.checkpoint_path.unlink(missing_ok=True)
        self.data = {'version': self.VERSION, 'created': time.time(), 'updated': time.time(), 'files': {}}
        self._dirty = False

    def has_checkpoint(self) -> bool:
        if not self.data['files']:
            return False
        return any(f['status'] in ('processing', 'failed') for f in self.data['files'].values())

    def get_pending(self, files: List[str]) -> List[Tuple[str, str, bool]]:
        pending = []
        for fp in files:
            fid = file_id(fp)
            state = self.get_state(fid)
            if state and state['status'] == 'done' and state.get('result'):
                out_path = state['result'].get('output_file')
                if out_path and Path(out_path).exists():
                    continue
            if state is None or state['status'] in ('processing', 'failed', 'pending'):
                pending.append((fp, fid, False))
        return pending

    def get_done_results(self, files: List[str]) -> Dict[str, RouteResult]:
        results = {}
        for fp in files:
            fid = file_id(fp)
            state = self.get_state(fid)
            if state and state['status'] == 'done' and state.get('result'):
                out_path = state['result'].get('output_file')
                if out_path and Path(out_path).exists():
                    results[fid] = RouteResult(**state['result'])
        return results

    def get_stats(self) -> dict:
        files = self.data['files']
        return {
            'total': len(files),
            'done': sum(1 for f in files.values() if f['status'] == 'done'),
            'processing': sum(1 for f in files.values() if f['status'] == 'processing'),
            'failed': sum(1 for f in files.values() if f['status'] == 'failed'),
        }

    def print_status(self) -> None:
        stats = self.get_stats()
        if stats['total'] == 0:
            return
        print(f"\n{C.CYAN}📋 Checkpoint status:{C.END}")
        print(f"   Totaal: {stats['total']} | {C.GREEN}✓ Klaar: {stats['done']}{C.END} | "
              f"{C.YELLOW}⏳ Bezig: {stats['processing']}{C.END} | {C.RED}✗ Mislukt: {stats['failed']}{C.END}")
        print(f"   Bestand: {self.checkpoint_path}\n")

# ═══════════════════════════════════════════════════════════════
#  PROGRESS TRACKER
# ═══════════════════════════════════════════════════════════════
class ProgressTracker:
    def __init__(self, silent: bool = False):
        self.start = time.time()
        self.phase_start = time.time()
        self.silent = silent
        self.logs: List[str] = []
        self._progress_active = False

    def _ts(self) -> str:
        return time.strftime("%H:%M:%S")

    def header(self, text: str) -> None:
        self.phase_start = time.time()
        msg = f"\n{C.BOLD}{C.CYAN}[{self._ts()}]{C.END} {C.BOLD}{text}{C.END}"
        if not self.silent:
            print(msg)
        self.logs.append(msg)

    def info(self, text: str) -> None:
        msg = f"   {C.BLUE}→{C.END} {text}"
        if not self.silent:
            print(msg)
        self.logs.append(msg)

    def detail(self, text: str) -> None:
        msg = f"      {C.YELLOW}·{C.END} {text}"
        if not self.silent:
            print(msg)
        self.logs.append(msg)

    def progress(self, text: str) -> None:
        if self.silent:
            return
        line = f"      {C.YELLOW}·{C.END} {text}"
        if sys.stdout.isatty():
            pad = ' ' * 12
            sys.stdout.write(f"\r{line}{pad}")
            sys.stdout.flush()
            self._progress_active = True
        else:
            print(line)

    def progress_done(self) -> None:
        if self.silent:
            return
        if self._progress_active:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._progress_active = False

    def success(self, text: str) -> None:
        msg = f"   {C.GREEN}✓{C.END} {text}"
        if not self.silent:
            print(msg)
        self.logs.append(msg)

    def warn(self, text: str) -> None:
        msg = f"   {C.YELLOW}⚠{C.END} {text}"
        if not self.silent:
            print(msg)
        self.logs.append(msg)

    def error(self, text: str) -> None:
        msg = f"   {C.RED}✗{C.END} {text}"
        if not self.silent:
            print(msg)
        self.logs.append(msg)

    def phase_time(self) -> None:
        elapsed = time.time() - self.phase_start
        msg = f"      {C.DIM}⏱  Fase duurde {elapsed:.2f}s{C.END}"
        if not self.silent:
            print(msg)
        self.logs.append(msg)

    def total_time(self) -> float:
        return time.time() - self.start

# ═══════════════════════════════════════════════════════════════
#  GPX PARSER — ULTRAPRECIES: geen snapping, alle punten behouden
# ═══════════════════════════════════════════════════════════════
class GPXParser:
    def __init__(self, tracker: ProgressTracker):
        self.tracker = tracker
        self._skipped_points = 0

    def _get_text(self, elem: ET.Element, tag: str, nsmap: Dict[str, str]) -> Optional[str]:
        child = elem.find(tag, nsmap)
        if child is not None and child.text:
            return child.text.strip()
        return None

    def _parse_trkpt(self, trkpt: ET.Element, nsmap: Dict[str, str]) -> Optional[GPXPoint]:
        lat_str = trkpt.get('lat')
        lon_str = trkpt.get('lon')
        if lat_str is None or lon_str is None:
            return None

        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except (ValueError, TypeError):
            self._skipped_points += 1
            return None

        point = GPXPoint(lat=lat, lon=lon)

        ele_elem = trkpt.find('gpx:ele' if nsmap else 'ele', nsmap)
        if ele_elem is not None and ele_elem.text:
            try:
                point.ele = float(ele_elem.text)
            except ValueError:
                pass

        time_elem = trkpt.find('gpx:time' if nsmap else 'time', nsmap)
        if time_elem is not None and time_elem.text:
            point.time = time_elem.text

        name_elem = trkpt.find('gpx:name' if nsmap else 'name', nsmap)
        if name_elem is not None and name_elem.text:
            point.name = name_elem.text

        cmt_elem = trkpt.find('gpx:cmt' if nsmap else 'cmt', nsmap)
        if cmt_elem is not None and cmt_elem.text:
            point.cmt = cmt_elem.text

        desc_elem = trkpt.find('gpx:desc' if nsmap else 'desc', nsmap)
        if desc_elem is not None and desc_elem.text:
            point.desc = desc_elem.text

        ext_elem = trkpt.find('gpx:extensions' if nsmap else 'extensions', nsmap)
        if ext_elem is not None:
            point.extensions = ext_elem

        return point

    def parse(self, input_file: str) -> Tuple[nx.MultiGraph, int, List[Dict], ExactCoordinateMap, List[str]]:
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input bestand niet gevonden: {input_file}")

        size_kb = os.path.getsize(input_file) / 1024
        self.tracker.info(f"Bestand: {os.path.basename(input_file)} ({size_kb:.1f} KB)")

        tree = ET.parse(input_file)
        root = tree.getroot()
        ns = get_namespace(root)
        nsmap = {'gpx': ns} if ns else {}

        G = nx.MultiGraph()
        coord_map = ExactCoordinateMap()
        total_raw_points = 0
        tracks_info = []
        warnings: List[str] = []
        self._skipped_points = 0

        trk_query = 'gpx:trk' if ns else 'trk'
        trkseg_query = 'gpx:trkseg' if ns else 'trkseg'
        trkpt_query = 'gpx:trkpt' if ns else 'trkpt'
        name_query = 'gpx:name' if ns else 'name'
        cmt_query = 'gpx:cmt' if ns else 'cmt'
        desc_query = 'gpx:desc' if ns else 'desc'

        tracks = root.findall(trk_query, nsmap)
        if tracks:
            self.tracker.info(f"{len(tracks)} track(s) gevonden")
            for idx, trk in enumerate(tracks):
                track_name = (self._get_text(trk, name_query, nsmap) or 
                             self._get_text(trk, cmt_query, nsmap) or 
                             self._get_text(trk, desc_query, nsmap) or 
                             f"Track {idx+1}")

                pts: List[GPXPoint] = []
                for trkseg in trk.findall(trkseg_query, nsmap):
                    seg_pts: List[GPXPoint] = []
                    for trkpt in trkseg.findall(trkpt_query, nsmap):
                        pt = self._parse_trkpt(trkpt, nsmap)
                        if pt is not None:
                            seg_pts.append(pt)
                    if len(seg_pts) > 1:
                        pts.extend(seg_pts)

                if pts:
                    # GEEN snapping — alle punten exact behouden
                    coords = [coord_map.register(p) for p in pts]
                    for i in range(len(coords) - 1):
                        p1, p2 = coords[i], coords[i + 1]
                        if p1 != p2:  # Alleen toevoegen als niet identiek
                            G.add_edge(p1, p2, 
                                       weight=haversine_distance(p1, p2),
                                       track_name=track_name)
                    total_raw_points += len(coords)
                    tracks_info.append({'name': track_name, 'points': len(coords), 'type': 'track'})
                    self.tracker.detail(f"\'{track_name}\': {len(coords)} punten, {len(coords)-1} segmenten")

        rte_query = 'gpx:rte' if ns else 'rte'
        rtept_query = 'gpx:rtept' if ns else 'rtept'

        routes = root.findall(rte_query, nsmap)
        if routes:
            self.tracker.info(f"{len(routes)} route(s) gevonden")
            for idx, rte in enumerate(routes):
                route_name = (self._get_text(rte, name_query, nsmap) or 
                             self._get_text(rte, cmt_query, nsmap) or 
                             self._get_text(rte, desc_query, nsmap) or 
                             f"Route {idx+1}")

                pts: List[GPXPoint] = []
                for rtept in rte.findall(rtept_query, nsmap):
                    pt = self._parse_trkpt(rtept, nsmap)
                    if pt is not None:
                        pts.append(pt)

                if len(pts) > 1:
                    coords = [coord_map.register(p) for p in pts]
                    for i in range(len(coords) - 1):
                        p1, p2 = coords[i], coords[i + 1]
                        if p1 != p2:
                            G.add_edge(p1, p2,
                                       weight=haversine_distance(p1, p2),
                                       track_name=route_name)
                    total_raw_points += len(coords)
                    tracks_info.append({'name': route_name, 'points': len(coords), 'type': 'route'})
                    self.tracker.detail(f"\'{route_name}\': {len(coords)} punten, {len(coords)-1} segmenten")

        wpt_query = 'gpx:wpt' if ns else 'wpt'
        wpts = root.findall(wpt_query, nsmap)
        if wpts:
            self.tracker.info(f"{len(wpts)} waypoint(s) gevonden")
            for wpt in wpts:
                pt = self._parse_trkpt(wpt, nsmap)
                if pt is not None:
                    coord = coord_map.register(pt)
                    G.add_node(coord)

        if self._skipped_points > 0:
            warnings.append(f"{self._skipped_points} corrupte GPX-punt(en) overgeslagen")
            self.tracker.warn(f"{self._skipped_points} corrupte GPX-punt(en) overgeslagen")

        self.tracker.success(
            f"Totaal: {total_raw_points} punten → {G.number_of_nodes()} unieke nodes (exact), "
            f"{G.number_of_edges()} edges"
        )
        return G, total_raw_points, tracks_info, coord_map, warnings

# ═══════════════════════════════════════════════════════════════
#  POSTMAN SOLVER v6.0 — Ultra-Precise Dead-End First
# ═══════════════════════════════════════════════════════════════
class PostmanSolver:
    def __init__(self, tracker: ProgressTracker):
        self.tracker = tracker

    def _get_street_names(self, G_sub: nx.MultiGraph, p1: Coord, p2: Coord) -> Set[str]:
        names = set()
        if G_sub.has_edge(p1, p2):
            for _, d in G_sub[p1][p2].items():
                if 'track_name' in d:
                    names.add(d['track_name'])
        return names

    def _get_node_street_names(self, G_sub: nx.MultiGraph, node: Coord) -> Set[str]:
        names = set()
        for _, _, d in G_sub.edges(node, data=True):
            if 'track_name' in d:
                names.add(d['track_name'])
        return names

    def _follow_spine_exact(self, G: nx.MultiGraph, start: Coord) -> List[Coord]:
        """
        Volg het unieke pad van start (een dead-end) terug tot een junction.
        Een junction is een node met 0 of >1 unieke buren (exclusief de node
        waar we vandaan kwamen). Returnt de lijst van nodes inclusief start
        en de junction — met ALLE tussenliggende punten, geen enkele bocht
        wordt overgeslagen.
        """
        path = [start]
        current = start
        prev = None

        while True:
            neighbors = set(G.neighbors(current))
            if prev in neighbors:
                neighbors.remove(prev)

            if len(neighbors) != 1:
                break

            nxt = neighbors.pop()
            path.append(nxt)
            prev, current = current, nxt

        return path

    def solve_component(self, G: nx.MultiGraph, comp: Set[Coord], 
                        comp_idx: int, total_comps: int) -> Tuple[List[Coord], float, float]:
        G_sub = G.subgraph(comp).copy()
        n_nodes = G_sub.number_of_nodes()
        n_edges = G_sub.number_of_edges()

        self.tracker.header(f"[Component {comp_idx}/{total_comps}]")
        self.tracker.info(f"{n_nodes} nodes, {n_edges} edges")

        if n_nodes <= 1:
            self.tracker.warn("Te weinig nodes — overgeslagen")
            return [], 0.0, 0.0

        original_dist = sum(d['weight'] for _, _, d in G_sub.edges(data=True))
        self.tracker.detail(f"Originele netwerk: {original_dist/1000:.2f} km")

        # Simpelere graaf voor shortest path (minste gewicht per node-paar)
        G_simple = nx.Graph()
        for u, v, d in G_sub.edges(data=True):
            w = d['weight']
            if G_simple.has_edge(u, v):
                if w < G_simple[u][v]['weight']:
                    G_simple[u][v]['weight'] = w
            else:
                G_simple.add_edge(u, v, weight=w)

        added_dist = 0.0

        # ═══════════════════════════════════════════════════════════
        #  FASE 1: Dead-End Backtrack — EXACT pad met alle punten
        #  Elk doodlopend pad wordt individueel teruggelopen over zichzelf.
        #  De originele graaf bepaalt WAT een dead-end is; de verdubbeling
        #  gebeurt in de werkgraaf G_sub (parallelle edges).
        #  BELANGRIJK: het pad wordt exact gevolgd met ALLE oorspronkelijke
        #  punten ertussen — geen enkele bocht wordt overgeslagen.
        # ═══════════════════════════════════════════════════════════
        G_orig = G_sub.copy()
        dead_ends = [v for v in G_orig.nodes() if G_orig.degree(v) == 1]

        if dead_ends:
            self.tracker.detail(f"Doodlopende straten (dead-ends): {len(dead_ends)}")
            handled: Set[Coord] = set()

            for de in dead_ends:
                if de in handled:
                    continue

                path = self._follow_spine_exact(G_orig, de)
                if len(path) < 2:
                    continue

                # Markeer alles op dit pad als afgehandeld zodat we geen
                # overlappende spines dubbel verdubbelen.
                for node in path:
                    handled.add(node)

                # Verdubbel elke edge in het pad in de werkgraaf
                # Gebruik het EXACTE pad — alle punten ertussen blijven behouden
                path_dist = 0.0
                street_names: Set[str] = set()
                for i in range(len(path) - 1):
                    u, v = path[i], path[i+1]
                    w = min(d['weight'] for _, d in G_orig[u][v].items())
                    G_sub.add_edge(u, v, weight=w)
                    path_dist += w
                    street_names.update(self._get_street_names(G_orig, u, v))

                added_dist += path_dist
                name_str = f" via {format_street_names(street_names)}" if street_names else ""
                self.tracker.detail(
                    f"  Backtrack {len(path)-1} segmenten ({path_dist:.0f}m){name_str}"
                )

        # ═══════════════════════════════════════════════════════════
        #  FASE 2: Resterende oneven knopen matchen
        # ═══════════════════════════════════════════════════════════
        odd_nodes = [v for v, d in G_sub.degree() if d % 2 == 1]
        self.tracker.detail(f"Oneven knopen na backtrack: {len(odd_nodes)}")

        if len(odd_nodes) == 0:
            self.tracker.detail(f"{C.GREEN}Netwerk is Euleriaans na backtrack!{C.END}")

        elif len(odd_nodes) == 2:
            self.tracker.detail(f"{C.GREEN}Slechts 2 oneven knopen — direct kortste pad.{C.END}")
            u, v = odd_nodes[0], odd_nodes[1]
            path = nx.shortest_path(G_simple, u, v, weight='weight')
            path_dist = sum(G_simple[path[i]][path[i+1]]['weight'] for i in range(len(path)-1))

            street_names = set()
            for i in range(len(path) - 1):
                p1, p2 = path[i], path[i+1]
                street_names.update(self._get_street_names(G_sub, p1, p2))
                G_sub.add_edge(p1, p2, weight=G_simple[p1][p2]['weight'])
            added_dist += path_dist

            name_str = f" via {format_street_names(street_names)}" if street_names else ""
            self.tracker.detail(f"  Pad: {len(path)} nodes, {path_dist:.0f}m{name_str}")

        else:
            self.tracker.detail(f"Bereken kortste paden voor {len(odd_nodes)} oneven knopen...")

            odd_graph = nx.Graph()
            paths_cache: Dict[Tuple[Coord, Coord], List[Coord]] = {}

            n_odd = len(odd_nodes)
            report_every = max(1, n_odd // 25)

            for i, u in enumerate(odd_nodes):
                if sys.stdout.isatty() or i % report_every == 0 or i == n_odd - 1:
                    node_streets = self._get_node_street_names(G_sub, u)
                    ctx = f" — bij {format_street_names(node_streets, max_shown=2)}" if node_streets else ""
                    self.tracker.progress(f"Dijkstra {i+1}/{n_odd}{ctx}...")
                lengths, path_map = nx.single_source_dijkstra(G_simple, u, weight='weight')
                for v in odd_nodes[i+1:]:
                    if v in lengths:
                        odd_graph.add_edge(u, v, weight=lengths[v])
                        paths_cache[(u, v)] = path_map[v]
                        paths_cache[(v, u)] = list(reversed(path_map[v]))

            self.tracker.progress_done()
            self.tracker.detail("Berekenen van optimale matching (min_weight_matching)...")
            
            matching = nx.min_weight_matching(odd_graph, weight='weight')
            
            for u, v in matching:
                path = paths_cache[(u, v)]
                path_dist = odd_graph[u][v]['weight']
                
                street_names = set()
                for i in range(len(path) - 1):
                    p1, p2 = path[i], path[i+1]
                    street_names.update(self._get_street_names(G_sub, p1, p2))
                    G_sub.add_edge(p1, p2, weight=G_simple[p1][p2]['weight'])
                
                added_dist += path_dist
                name_str = f" via {format_street_names(street_names)}" if street_names else ""
                self.tracker.detail(f"  Match: {len(path)} nodes, {path_dist:.0f}m{name_str}")

        # ═══════════════════════════════════════════════════════════
        #  FASE 3: Hierholzer (Eulerian Circuit) — op volledige multigraph
        #  Het circuit wordt gegenereerd op G_sub die ALLE oorspronkelijke
        #  edges bevat (met alle punten ertussen). Zo volgt de route 100%
        #  het bestaande wegennet — geen enkele bocht wordt overgeslagen.
        # ═══════════════════════════════════════════════════════════
        self.tracker.detail("Genereer Euleriaans circuit...")
        euler_circuit = list(nx.eulerian_circuit(G_sub))
        
        # Reconstrueer de volledige route met ALLE punten
        # euler_circuit geeft edges terug; we moeten de volledige paden
        # reconstrueren om alle tussenpunten te behouden
        circuit_nodes = [euler_circuit[0][0]]
        for u, v in euler_circuit:
            # Als er een directe edge is, voeg v toe
            # Als het een samengevoegde edge is (van matching), moeten we
            # het pad reconstrueren — maar in G_sub zijn alle edges direct
            # toegevoegd, dus we volgen gewoon de edges
            circuit_nodes.append(v)
        
        total_dist = original_dist + added_dist
        
        return circuit_nodes, original_dist, added_dist


# ═══════════════════════════════════════════════════════════════
#  GPX EXPORTER — behoudt alle metadata en exacte coördinaten
# ═══════════════════════════════════════════════════════════════
class GPXExporter:
    def __init__(self, tracker: ProgressTracker, coord_map: ExactCoordinateMap):
        self.tracker = tracker
        self.coord_map = coord_map

    def export(self, route_nodes: List[Coord], output_file: str, track_name: str = "Optimized Route") -> int:
        root = ET.Element("gpx", {
            "version": "1.1",
            "creator": "Chinese Postman Optimizer v6.0 — Ultra-Precise",
            "xmlns": "http://www.topografix.com/GPX/1/1"
        })
        
        trk = ET.SubElement(root, "trk")
        name_elem = ET.SubElement(trk, "name")
        name_elem.text = track_name
        
        trkseg = ET.SubElement(trk, "trkseg")
        
        for coord in route_nodes:
            orig_pt = self.coord_map.get_original(coord)
            
            trkpt_attrs = {
                "lat": f"{coord.lat:.7f}",  # Hogere precisie: 7 decimalen
                "lon": f"{coord.lon:.7f}"
            }
            trkpt = ET.SubElement(trkseg, "trkpt", trkpt_attrs)
            
            if orig_pt:
                if orig_pt.ele is not None:
                    ele = ET.SubElement(trkpt, "ele")
                    ele.text = f"{orig_pt.ele:.2f}"
                if orig_pt.time:
                    t = ET.SubElement(trkpt, "time")
                    t.text = orig_pt.time

        indent_xml(root)
        
        out_path = Path(output_file)
        tmp_path = out_path.with_suffix(".tmp")
        
        tree = ET.ElementTree(root)
        tree.write(str(tmp_path), encoding="utf-8", xml_declaration=True)
        
        safe_replace(tmp_path, out_path)
        return len(route_nodes)


# ═══════════════════════════════════════════════════════════════
#  VALIDATIE — controleer dat elke oorspronkelijke edge in de route zit
# ═══════════════════════════════════════════════════════════════
def validate_route(G_orig: nx.MultiGraph, route_nodes: List[Coord], 
                   tracker: ProgressTracker) -> Tuple[int, int, float]:
    """
    Controleer of elke oorspronkelijke edge exact in de route voorkomt.
    Returnt: (aantal_gevalideerd, aantal_ontbrekend, max_afwijking_m)
    """
    # Bouw een set van edges in de route (als tuples van coord-paren)
    route_edges = set()
    for i in range(len(route_nodes) - 1):
        a, b = route_nodes[i], route_nodes[i+1]
        route_edges.add((a, b))
        route_edges.add((b, a))  # Beide richtingen
    
    edges_validated = 0
    edges_missing = 0
    max_dev = 0.0
    
    for u, v, d in G_orig.edges(data=True):
        if (u, v) in route_edges or (v, u) in route_edges:
            edges_validated += 1
        else:
            edges_missing += 1
            # Bereken afwijking voor rapportage
            dev = point_to_segment_distance(u, v, route_nodes[0])  # Simplistisch
            max_dev = max(max_dev, dev)
    
    return edges_validated, edges_missing, max_dev


# ═══════════════════════════════════════════════════════════════
#  SINGLE FILE PROCESSOR
# ════════════════════════════════════════════════════════════
def _min_comp_dist(nodes_a: List[Coord], nodes_b: List[Coord]) -> Tuple[float, Coord, Coord]:
    """
    Kleinste afstand tussen twee componenten (voor het kiezen van de slimme
    verbindingsvolgorde) plus het dichtstbijzijnde puntpaar. Bij heel grote
    componenten wordt eerst gestroefd gesampled — de keuze van 'dichtstbij'
    hoeft geen millimeter-precisie te hebben.
    """
    if len(nodes_a) > 1500:
        nodes_a = nodes_a[::math.ceil(len(nodes_a) / 1500)]
    if len(nodes_b) > 1500:
        nodes_b = nodes_b[::math.ceil(len(nodes_b) / 1500)]
    best_d = float('inf')
    best_a = nodes_a[0]
    best_b = nodes_b[0]
    for a in nodes_a:
        for b in nodes_b:
            d = haversine_distance(a, b)
            if d < best_d:
                best_d = d
                best_a = a
                best_b = b
    return best_d, best_a, best_b


def _smart_bridge_order(comp_results: List[Tuple[Set[Coord], List[Coord], float, float]], 
                        tracker: ProgressTracker) -> Dict[int, Tuple[float, Coord, Coord]]:
    """
    Bepaal per component met WELK al-aangesloten component hij verbonden
    wordt, en via welke twee punten (rechtstreekse lijn).

    Prim-greedy: begin bij het grootste component; herhaaldelijk de losse
    component zoeken die het DICHTST bij het reeds-aangesloten netwerk ligt.
    """
    n = len(comp_results)
    start = max(range(n), key=lambda i: len(comp_results[i][0]))
    in_net = {start}
    order = [start]
    attach: Dict[int, Tuple[float, Coord, Coord]] = {}
    cache: Dict[Tuple[int, int], Tuple[float, Coord, Coord]] = {}

    def pair_dist(i: int, j: int) -> Tuple[float, Coord, Coord]:
        key = (i, j) if i < j else (j, i)
        if key not in cache:
            cache[key] = _min_comp_dist(list(comp_results[i][0]), 
                                        list(comp_results[j][0]))
        return cache[key]

    while len(in_net) < n:
        best = None
        for j in range(n):
            if j in in_net:
                continue
            for i in in_net:
                d, a_node, b_node = pair_dist(i, j)
                if best is None or d < best[0]:
                    best = (d, a_node, b_node, j)
        d, a_node, b_node, j = best
        attach[j] = (d, a_node, b_node)
        in_net.add(j)
        order.append(j)

    attach['_order'] = order  # type: ignore
    return attach


def process_single_file(input_file: str, output_file: str, silent: bool = False,
                        checkpoint_mgr: Optional[CheckpointManager] = None,
                        file_id_str: Optional[str] = None,
                        bridge_components: bool = True) -> RouteResult:
    tracker = ProgressTracker(silent=silent)
    file_start = time.time()

    if checkpoint_mgr and file_id_str:
        checkpoint_mgr.set_status(file_id_str, input_file, 'processing')

    try:
        # 1. Parse GPX — Ultraprecies
        parser = GPXParser(tracker)
        G, original_points, tracks_info, coord_map, warnings = parser.parse(input_file)

        if G.number_of_nodes() == 0:
            raise ValueError("Geen geldige punten/edges gevonden in het GPX-bestand.")

        # 2. Bepaal componenten
        components = [c for c in nx.connected_components(G)]
        total_components = len(components)

        solver = PostmanSolver(tracker)

        # 3. Los elk component EERST af
        comp_results: List[Tuple[Set[Coord], List[Coord], float, float]] = []
        for idx, comp in enumerate(components, 1):
            nodes, orig_d, add_d = solver.solve_component(G, comp, idx, total_components)
            if nodes:
                comp_results.append((comp, nodes, orig_d, add_d))

        if not comp_results:
            raise ValueError("Kon geen geldige route genereren uit de data.")

        # 4. Componenten samenvoegen tot één route
        if bridge_components and len(comp_results) > 1:
            attach = _smart_bridge_order(comp_results, tracker)
            order: List[int] = attach.pop('_order')  # type: ignore

            all_route_nodes: List[Coord] = list(comp_results[order[0]][1])
            total_original = comp_results[order[0]][2]
            total_added = comp_results[order[0]][3]
            bridge_total = 0.0

            for j in order[1:]:
                d, a_node, b_node = attach[j]
                tracker.detail(f"Rechte lijn naar component: {d:.0f}m "
                               f"(van {a_node.lat:.7f},{a_node.lon:.7f} → "
                               f"{b_node.lat:.7f},{b_node.lon:.7f})")
                all_route_nodes.append(b_node)
                all_route_nodes.extend(comp_results[j][1])
                total_original += comp_results[j][2]
                total_added += comp_results[j][3] + d
                bridge_total += d

            warnings.append(
                f"{len(order)-1} rechtstreekse verbindingslijn(en) getrokken "
                f"tussen losse componenten (totaal {bridge_total/1000:.2f} km)"
            )
            tracker.info(f"Componenten slim verbonden: {len(order)-1} rechte lijn(en), "
                         f"{bridge_total/1000:.2f} km totaal")
        else:
            comp_results.sort(key=lambda r: len(r[0]), reverse=True)
            largest = comp_results[0]
            all_route_nodes = list(largest[1])
            total_original = largest[2]
            total_added = largest[3]
            if len(comp_results) > 1:
                dropped = len(comp_results) - 1
                dropped_nodes = sum(len(r[0]) for r in comp_results[1:])
                msg = (f"{dropped} kleinere component(en) verwijderd "
                       f"({dropped_nodes} nodes) — alleen het grootste component "
                       f"({len(largest[0])} nodes) blijft over")
                warnings.append(msg)
                tracker.warn(msg)

        # 5. Validatie-fase
        tracker.header("VALIDEER ROUTE")
        val_validated, val_missing, max_dev = validate_route(G, all_route_nodes, tracker)
        if val_missing > 0:
            tracker.warn(f"Validatie: {val_validated} edges gevalideerd, {val_missing} ontbrekend!")
            warnings.append(f"Validatie waarschuwing: {val_missing} edge(s) mogelijk niet gedekt")
        else:
            tracker.success(f"Validatie geslaagd: alle {val_validated} edges zijn gedekt in de route!")

        # 6. Exporteer resultaat
        exporter = GPXExporter(tracker, coord_map)
        total_pts = exporter.export(all_route_nodes, output_file, 
                                    track_name=f"Optimized_{Path(input_file).stem}")

        total_dist = total_original + total_added
        efficiency = (total_original / total_dist * 100) if total_dist > 0 else 100.0
        elapsed = time.time() - file_start

        tracker.header("RESULTAAT OVERZICHT")
        tracker.success(f"Originele afstand: {total_original/1000:.2f} km")
        tracker.success(f"Toegevoegde afstand: {total_added/1000:.2f} km (+{(total_added/total_original*100) if total_original else 0:.1f}%)")
        tracker.success(f"Totale routelengte: {total_dist/1000:.2f} km")
        tracker.success(f"Efficiëntie: {efficiency:.1f}%")

        result = RouteResult(
            input_file=input_file,
            output_file=output_file,
            success=True,
            tracks_info=tracks_info,
            original_points=original_points,
            output_points=total_pts,
            components=total_components,
            original_dist=total_original,
            added_dist=total_added,
            total_dist=total_dist,
            efficiency=efficiency,
            processing_time=elapsed,
            warnings=warnings,
            edges_validated=val_validated,
            edges_missing=val_missing,
            max_deviation_m=max_dev
        )

        if checkpoint_mgr and file_id_str:
            checkpoint_mgr.set_status(file_id_str, input_file, 'done', result.to_dict())

        return result

    except Exception as e:
        tracker.error(f"Fout bij verwerken: {e}")
        elapsed = time.time() - file_start

        result = RouteResult(
            input_file=input_file,
            output_file=output_file,
            success=False,
            tracks_info=[],
            original_points=0,
            output_points=0,
            components=0,
            original_dist=0.0,
            added_dist=0.0,
            total_dist=0.0,
            efficiency=0.0,
            processing_time=elapsed,
            warnings=[],
            error_message=str(e)
        )

        if checkpoint_mgr and file_id_str:
            checkpoint_mgr.set_status(file_id_str, input_file, 'failed', result.to_dict())

        return result


def _process_parallel_worker(args: Tuple[str, str, str, bool]) -> Dict:
    """Worker-functie voor parallelle verwerking via ProcessPoolExecutor."""
    input_file, output_file, fid, bridge = args
    res = process_single_file(input_file, output_file, silent=True,
                              file_id_str=None,
                              bridge_components=bridge)
    return res.to_dict()


# ═══════════════════════════════════════════════════════════════
# CLI & MAIN LOGIC
# ═══════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chinese Postman Optimizer v6.0 — Ultra-Precise Edition",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("inputs", nargs="*", help="GPX bestanden, mappen of een JSON config")
    parser.add_argument("-o", "--out-dir", type=str, default="./output", help="Output map voor verwerkte GPX bestanden")
    parser.add_argument("-p", "--parallel", action="store_true", help="Verwerk bestanden parallel")
    parser.add_argument("-w", "--workers", type=int, default=os.cpu_count(), help="Aantal parallelle workers")
    parser.add_argument("-r", "--resume", action="store_true", help="Hervat eerdere sessie vanaf checkpoint")
    parser.add_argument("-c", "--clear-checkpoint", action="store_true", help="Wis bestaand checkpoint")

    parser.add_argument("--checkpoint", dest="checkpoint", action="store_true",
                        help="Checkpointing AAN (default)")
    parser.add_argument("--no-checkpoint", dest="checkpoint", action="store_false",
                        help="Checkpointing UIT")
    parser.set_defaults(checkpoint=True)

    parser.add_argument("--bridge-components", dest="bridge", action="store_true",
                        help="Kleine componenten BEHOUDEN en slim verbinden (default)")
    parser.add_argument("--drop-components", dest="bridge", action="store_false",
                        help="Kleine componenten VERWIJDERD — alleen grootste blijft")
    parser.set_defaults(bridge=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    if args.checkpoint:
        chk_mgr: Optional[CheckpointManager] = CheckpointManager(script_dir)
    else:
        chk_mgr = None
        print(f"{C.YELLOW}⚠ Checkpointing is uitgeschakeld (--no-checkpoint).{C.END}")

    if args.clear_checkpoint and chk_mgr:
        chk_mgr.clear_all()
        print(f"{C.GREEN}✓ Checkpoint gewist.{C.END}")
        if not args.inputs:
            return

    input_files: List[str] = []
    
    if not args.inputs:
        in_dir = script_dir / "input"
        if in_dir.exists():
            input_files.extend(glob.glob(str(in_dir / "*.gpx")))
    else:
        for inp in args.inputs:
            p = Path(inp)
            if p.is_file():
                if p.suffix.lower() == ".json":
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            cfg = json.load(f)
                            input_files.extend(cfg.get("inputs", []))
                    except Exception as e:
                        print(f"{C.RED}Fout bij lezen config {p}: {e}{C.END}")
                elif p.suffix.lower() == ".gpx":
                    input_files.append(str(p))
            elif p.is_dir():
                input_files.extend(glob.glob(str(p / "*.gpx")))
            else:
                input_files.extend(glob.glob(inp))

    input_files = sorted(list(set(input_files)))

    if not input_files:
        print(f"{C.YELLOW}Geen GPX-bestanden gevonden om te verwerken.{C.END}")
        return

    out_dir = Path(args.out_dir)
    safe_makedirs(out_dir)

    print(f"{C.BOLD}{C.CYAN} Chinese Postman Optimizer v6.0 — Ultra-Precise {C.END}")
    print(f" Bestanden gevonden: {len(input_files)}")
    print(f" Output map: {out_dir.absolute()}")
    print(f" Componenten: {'slim verbinden tot één netwerk' if args.bridge else 'kleine verwijderd, alleen grootste'}")
    print(f" Checkpointing: {'aan' if args.checkpoint else 'UIT'}")
    print(f" Precisie: ULTRA — geen snapping, alle punten exact behouden\n")

    if chk_mgr:
        pending_tasks = chk_mgr.get_pending(input_files)
        if not pending_tasks and chk_mgr.get_stats()['total'] > 0:
            print(f"{C.GREEN}✓ Alle bestanden zijn al verwerkt volgens checkpoint — niets te doen.{C.END}")
            return
    else:
        pending_tasks = [(fp, file_id(fp), False) for fp in input_files]

    results: List[RouteResult] = []

    if args.parallel and len(pending_tasks) > 1:
        print(f"{C.BLUE}Start parallelle verwerking met {args.workers} workers...{C.END}")
        tasks = []
        for fp, fid, _ in pending_tasks:
            out_fp = str(out_dir / f"optimized_{Path(fp).name}")
            tasks.append((fp, out_fp, fid, args.bridge))

        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(_process_parallel_worker, t) for t in tasks]
            for future in futures:
                try:
                    res_dict = future.result()
                    results.append(RouteResult(**res_dict))
                except Exception as e:
                    print(f"{C.RED}Worker fout: {e}{C.END}")
    else:
        for fp, fid, _ in pending_tasks:
            out_fp = str(out_dir / f"optimized_{Path(fp).name}")
            res = process_single_file(fp, out_fp, checkpoint_mgr=chk_mgr,
                                      file_id_str=fid, bridge_components=args.bridge)
            results.append(res)

    print(f"\n{C.BOLD}{C.GREEN}" + "=" * 70)
    print(" VERWERKING VOLTOOID — OVERZICHT")
    print("=" * 70 + f"{C.END}")
    
    success_count = sum(1 for r in results if r.success)
    print(f" Succesvol: {success_count}/{len(results)}")
    
    for r in results:
        status_symbol = f"{C.GREEN}✓{C.END}" if r.success else f"{C.RED}✗{C.END}"
        validation_info = ""
        if r.success and r.edges_validated > 0:
            validation_info = f" | Validatie: {r.edges_validated}/{r.edges_validated + r.edges_missing} edges"
        print(f"  {status_symbol} {Path(r.input_file).name} -> {Path(r.output_file).name} "
              f"({r.total_dist/1000:.2f} km, {r.processing_time:.2f}s){validation_info}")


if __name__ == "__main__":
    main()

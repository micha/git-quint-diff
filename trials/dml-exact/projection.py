"""Check erasure for every state of two closed TLC DOT graphs of exact DML.

Only the top-level qdSite assignment is removed. Compare all four values,
normalizing TLC's record-field order and layout. Repeated DOT edge rows count
toward closure but not toward successor sets.
"""

import copy
from functools import lru_cache
import json
import re
import sys


HEADER = ["strict digraph DiskGraph {", "node [shape=box,style=rounded]", "nodesep=0.35;",
          "subgraph cluster_graph {", 'color="white";']
NODE = re.compile(r'(-?\d+) \[label=("(?:[^"\\]|\\.)*")(,style = filled|,tooltip=.*)\];?')
EDGE = re.compile(r'(-?\d+) -> (-?\d+) \[label="",color="black",fontcolor="black"\];')
RANK = re.compile(r'\{rank = same; (?:-?\d+;? ?)+\}')
STATS = re.compile(r'^(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue\.$', re.M)
VARIABLES = ("event", "returning", "source", "worker")
TOKEN = re.compile(r'\s*(\|->|-?\d+|[A-Za-z]\w*|"(?:[^"\\]|\\.)*"|[\[\]{},])')


@lru_cache(maxsize=65536)
def canonical(text):
    """Normalize the record/int-set/str/int/bool subset in these snapshots."""
    pos = 0
    def scan():
        nonlocal pos
        if pos == len(text):
            return None
        match = TOKEN.match(text, pos)
        if not match:
            raise ValueError(f"unexpected TLC value: {text}")
        pos = match.end()
        return match[1]

    token = scan()
    def take():
        nonlocal token
        previous, token = token, scan()
        return previous

    def expect(expected):
        if take() != expected:
            raise ValueError(f"expected {expected} in TLC value: {text}")

    def value():
        item = take()
        if item in ("[", "{"):
            end = "]" if item == "[" else "}"
            fields = {}
            if token != end:
                while True:
                    key = take()
                    if key is None or not re.fullmatch(r'[A-Za-z]\w*' if item == "[" else r'-?\d+', key) or key in fields:
                        raise ValueError(f"invalid or duplicate field/member in TLC value: {text}")
                    if item == "[":
                        expect("|->")
                        fields[key] = f"{key}|->{value()}"
                    else:
                        fields[key] = key
                    if token != ",":
                        break
                    take()
            expect(end)
            return item + ",".join(sorted(fields.values())) + end
        if item is None or not re.fullmatch(r'-?\d+|TRUE|FALSE|"(?:[^"\\]|\\.)*"', item):
            raise ValueError(f"unexpected TLC atom: {text}")
        return item

    out = value()
    if token is not None:
        raise ValueError(f"extra tokens in TLC value: {text}")
    return sys.intern(out)


def state_key(bindings):
    if set(bindings) != set(VARIABLES):
        raise ValueError("expected exactly the four original DML variables")
    return tuple(canonical(bindings[var]) for var in VARIABLES)


def entries(path):
    with path.open(encoding="utf8") as dot:
        if [dot.readline().rstrip("\n") for _ in HEADER] != HEADER:
            raise ValueError(f"unexpected DOT header: {path}")
        for line in dot:
            row = line.rstrip("\n")
            if row == "}":
                if dot.readline().rstrip("\n") != "}" or dot.read():
                    raise ValueError(f"unexpected DOT trailer: {path}")
                return
            yield row
    raise ValueError(f"missing DOT trailer: {path}")


def nodes(directory, native=None):
    tagged = native is not None
    log = (directory / "tlc.log").read_text(encoding="utf8")
    stats = STATS.findall(log)
    if len(stats) != 1 or stats[0][-1] != "0" or "Model checking completed. No error has been found." not in log:
        raise ValueError(f"no TLC closure: {directory}")
    generated, distinct, _ = map(int, stats[0])
    fingerprints, states, initial = {}, {}, set()
    tags = {0, *map(int, json.loads((directory / "sites.json").read_text()))} if tagged else {0}
    edge_rows = 0
    for row in entries(directory / "graph.dot"):
        if match := NODE.fullmatch(row):
            fp, label, style = match.groups()
            label = json.loads(label)
            if not label.startswith("/\\ "):
                raise ValueError(f"expected TLC state with four original variables: {fp}")
            fields = [field.split(" = ", 1) for field in label[3:].split("\n/\\ ")]
            bindings = dict(fields)
            initial_state = style == ",style = filled"
            site = int(bindings.pop("qdSite")) if tagged else 0
            if (len(fields) != len(VARIABLES) + tagged or site not in tags
                    or (tagged and (site == 0) != initial_state)):
                raise ValueError(f"wrong state variables or tag: {fp}")
            key = state_key(bindings)
            if tagged:
                if key not in native:
                    raise ValueError(f"tagged state has no native projection: {fp}")
                key = (native[key], site)
            if fp in fingerprints or key in states:
                raise ValueError(f"duplicate TLC state: {fp}")
            fingerprints[fp] = states[key] = len(states)
            if initial_state:
                initial.add(states[key])
        elif EDGE.fullmatch(row):
            edge_rows += 1
        elif not RANK.fullmatch(row):
            raise ValueError(f"unexpected DOT row: {row[:100]}")
    if len(states) != distinct or len(initial) != 1 or len(initial) + edge_rows != generated:
        raise ValueError(f"DOT state/edge rows do not agree with closure: {directory}")
    return fingerprints, states, initial


def edges(directory, fingerprints):
    outgoing = [set() for _ in fingerprints]
    for row in entries(directory / "graph.dot"):
        if match := EDGE.fullmatch(row):
            a, b = (fingerprints[fp] for fp in match.groups())
            outgoing[a].add(b)
    return outgoing


def check(native, tagged, project):
    for i, (source, targets) in enumerate(zip(project, tagged, strict=True)):
        if {project[j] for j in targets} != native[source]:
            raise ValueError(f"successors differ under erasure at tagged state {i} over native state {source}")


def replay(native, initial, frames):
    if frames[0] not in initial:
        raise ValueError("witness does not start at native init")
    for i, (source, target) in enumerate(zip(frames, frames[1:]), 1):
        if target not in native[source]:
            raise ValueError(f"witness has no native edge at frame {i}")


def verify(native_dir, tagged_dir, witnesses=()):
    native_ids, native_states, native_initial = nodes(native_dir)
    tracked_ids, tracked_states, tracked_initial = nodes(tagged_dir, native_states)
    # states are in the insertion order of their dense indices.
    project = [source for source, _ in tracked_states]
    if {project[i] for i in tracked_initial} != native_initial or set(project) != set(native_states.values()):
        raise ValueError("initial or reachable states differ under erasure")
    def path(witness):
        frames = [witness["initial"], *(step["state"] for step in witness["steps"])]
        receipt = re.search(r',receipt\|->(-?\d+)[,\]]', canonical(frames[-1]["event"]))
        if not receipt or int(receipt[1]) != witness["outcome"]:
            raise ValueError("witness has the wrong native receipt")
        return [native_states[state_key(frame)] for frame in frames]

    paths = [path(witness) for witness in witnesses]
    tagged_paths = []
    if witnesses:
        sites = json.loads((tagged_dir / "sites.json").read_text())
        for witness, frames in zip(witnesses, paths, strict=True):
            tags = [0]
            for step in witness["steps"]:
                tag, = (int(key) for key, item in sites.items() if item == {k: step[k] for k in ("site", "label")})
                tags.append(tag)
            tagged_paths.append([tracked_states[key] for key in zip(frames, tags, strict=True)])
        bad = copy.deepcopy(witnesses[0])
        reset = bad["steps"][2]["state"]
        reset["source"], count = re.subn(r'main \|-> 3\b', 'main |-> 0', reset["source"])
        assert count == 1
        bad_path = path(bad)  # All its frames are reachable; not all its edges.
    del native_states, tracked_states
    native = edges(native_dir, native_ids)
    del native_ids
    for frames in paths:
        replay(native, native_initial, frames)
    if witnesses:
        try:
            replay(native, native_initial, bad_path)
        except ValueError as error:
            if str(error) != "witness has no native edge at frame 3":
                raise
        else:
            raise AssertionError("native replay accepted a reachable state on the wrong witness edge")
    tracked = edges(tagged_dir, tracked_ids)
    for frames in tagged_paths:
        replay(tracked, tracked_initial, frames)
    if witnesses:
        print(f"{native_dir.name}: replayed {len(paths)} witnesses in both graphs; rejected a changed report-reset frame",
              flush=True)
    check(native, tracked, project)
    native_edges, tracked_edges = sum(map(len, native)), sum(map(len, tracked))

    # Check the regression's precision on the real graph: remove a projected
    # successor from one tagged state, retaining it at a shadow of that state.
    seen = {}
    for i, source in enumerate(project):
        if source in seen and tracked[i]:
            removed = min(project[j] for j in tracked[i])
            tracked[i] = {j for j in tracked[i] if project[j] != removed}
            assert any(project[j] == removed for j in tracked[seen[source]])
            try:
                check(native, tracked, project)
            except ValueError:
                break
            raise AssertionError("erasure accepted loss from a single tagged state")
        seen[source] = i
    else:
        raise AssertionError("no distinct tags over a native state with a successor")

    print(f"{tagged_dir.name}: projected {len(tracked):,} tagged states / {tracked_edges:,} edges onto "
          f"{len(native):,} native states / {native_edges:,} edges; rejected a tag-dependent edge loss", flush=True)

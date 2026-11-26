"""Independent native graph and replay oracle for the pinned consensus instance.

The runtime's binders, compiled actions, and DOT reader are not used here. The
only Quint adapter instantiates constants and leaves init/step unchanged.
"""

from collections import deque, namedtuple
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import socket
import subprocess

from consensus_fixture import ENTRYPOINT, SCHEDULER, git


FIELDS = ("round", "stage", "crashed", "newlyCrashed", "correctProcsMessages",
          "crashedProcsMessages", "procState")
State = namedtuple("State", FIELDS)
TOKEN = re.compile(r'\s*(<<|>>|\|->|[{}\[\],]|-?[0-9]+|[A-Za-z][A-Za-z0-9_]*|"UNIT")')
ASSIGNMENT = re.compile(r'^/\\ (\w+) = ', re.M)
QUOTED = r'"(?:\\.|[^"\\])*"'
NODE = re.compile(rf'(-?\d+) \[label=({QUOTED}),(style = filled|tooltip={QUOTED})\];?')
EDGE = re.compile(r'(-?\d+) -> (-?\d+) \[label="",color="black",fontcolor="black"\];')
RANK = re.compile(r'\{rank = same; (?:-?\d+;)+}')


@dataclass(frozen=True)
class Record:
    fields: tuple

    def __getitem__(self, key):
        return dict(self.fields)[key]


@dataclass
class Graph:
    initial: set
    outgoing: dict


def read_value(text):
    """Parse only the literal forms TLC emits for these exact snapshots."""
    remaining = text.strip()
    tokens = []
    while remaining:
        match = TOKEN.match(remaining)
        if not match:
            raise ValueError(f"unexpected consensus TLC value: {text}")
        tokens.append(match[1])
        remaining = remaining[match.end():]
    tokens = deque(tokens)

    def expect(token):
        if not tokens or tokens.popleft() != token:
            raise ValueError(f"expected {token!r} in {text}")

    def items(end, item):
        result = []
        if tokens and tokens[0] != end:
            result.append(item())
            while tokens and tokens[0] == ",":
                expect(",")
                result.append(item())
        expect(end)
        return result

    def field():
        key = tokens.popleft()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
            raise ValueError(f"unexpected record key in {text}")
        expect("|->")
        return key, value()

    def value():
        token = tokens.popleft()
        if token == "[":
            pairs = items("]", field)
            if not pairs or len(dict(pairs)) != len(pairs):
                raise ValueError(f"empty or duplicate record fields in {text}")
            return Record(tuple(sorted(pairs)))
        if token == "{":
            values = items("}", value)
            if len(set(values)) != len(values):
                raise ValueError(f"duplicate set elements in {text}")
            return frozenset(values)
        if token == "<<":
            return tuple(items(">>", value))
        if token == '"UNIT"':
            return "UNIT"
        if re.fullmatch(r"-?[0-9]+", token):
            return int(token)
        raise ValueError(f"unexpected token {token!r} in {text}")

    try:
        decoded = value()
    except IndexError as error:
        raise ValueError(f"missing token in {text}") from error
    if tokens:
        raise ValueError(f"trailing tokens in {text}")
    return decoded


def state_values(literals):
    values = {}
    for name, raw in literals.items():
        fields = [field for field in FIELDS if name == field or name.endswith("_" + field)]
        if len(fields) != 1 or fields[0] in values:
            raise ValueError(f"unexpected or duplicate native variable: {name}")
        values[fields[0]] = read_value(raw)
    if values.keys() != set(FIELDS):
        raise ValueError(f"incomplete state: expected all seven native variables, got {list(values)}")
    return State(**values)


def node_state(raw):
    label = json.loads(raw)
    assignments = list(ASSIGNMENT.finditer(label))
    if not assignments or assignments[0].start() != 0:
        raise ValueError("invalid native TLC state node")
    ends = [match.start() for match in assignments[1:]] + [len(label)]
    values = {match[1]: label[match.end():end] for match, end in zip(assignments, ends, strict=True)}
    if len(values) != len(assignments):
        raise ValueError("duplicate native TLC state node variable")
    return state_values(values)


def read_graph(path, generated, distinct):
    lines = path.read_text(encoding="utf8").strip().splitlines()
    header = ["strict digraph DiskGraph {", "node [shape=box,style=rounded]", "nodesep=0.35;",
              "subgraph cluster_graph {", 'color="white";']
    if lines[:5] != header or lines[-2:] != ["}", "}"]:
        raise ValueError("unexpected native TLC graph framing")
    nodes, initial, edges = {}, set(), []
    for line in lines[5:-2]:
        if match := NODE.fullmatch(line):
            key, raw, style = match.groups()
            if key in nodes:
                raise ValueError("duplicate native TLC state ID")
            nodes[key] = node_state(raw)
            if style == "style = filled":
                initial.add(key)
        elif match := EDGE.fullmatch(line):
            edges.append(match.groups())
        elif not RANK.fullmatch(line):
            raise ValueError(f"unexpected native TLC graph row: {line}")
    if (not initial or len(nodes) != distinct or len(set(nodes.values())) != distinct
            or len(initial) + len(edges) != generated):
        raise ValueError("native TLC graph does not match closure counts")
    graph = Graph({nodes[key] for key in initial}, {state: set() for state in nodes.values()})
    for source, target in edges:
        graph.outgoing[nodes[source]].add(nodes[target])
    reached, frontier = set(graph.initial), list(graph.initial)
    while frontier:
        unseen = graph.outgoing[frontier.pop()] - reached
        reached.update(unseen)
        frontier.extend(unseen)
    if reached != graph.outgoing.keys():
        raise ValueError("native TLC graph contains unreachable states")
    return graph


def native_graph(repo, commit, work, env):
    work.mkdir()
    for path in (ENTRYPOINT, SCHEDULER):
        (work / Path(path).name).write_bytes(git(repo, env, "cat-file", "blob", f"{commit}:{path}"))
    (work / "oracle.qnt").write_text('''module oracle {
  import KSetAgreementConsensus(N = 3, F = 1, ACTUAL_FAULTS = 1, K = 1, MAX_ROUNDS = 2).* from "./KSetAgreementConsensus"
}
''', encoding="utf8")

    def run(*args):
        result = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(f"Independent {args[0]} failed:\n{result.stdout}{result.stderr}")
        return result.stdout

    if run("quint", "--version").strip() != "0.33.1":
        raise AssertionError("Native oracle requires Quint 0.33.1 from nix develop")
    # Quint starts its own Apalache server. Pick a local free port instead of
    # accidentally using a concurrently running server of a different version.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    tla = run("quint", "compile", "oracle.qnt", "--target", "tlaplus", "--verbosity", "0",
              "--apalache-version", "0.62.4", "--server-endpoint", f"127.0.0.1:{port}")
    (work / "oracle.tla").write_text(tla, encoding="utf8")
    (work / "oracle.cfg").write_text("INIT q_init\nNEXT q_step\n", encoding="utf8")
    jar = Path(env["QUINT_HOME"]) / "apalache-dist-0.62.4/apalache/lib/apalache.jar"
    log = run("java", "-Xmx512m", "-XX:+UseParallelGC", "-Duser.language=en", "-Duser.country=US",
              f"-Djava.io.tmpdir={work}", "-cp", str(jar), "tlc2.TLC", "-deadlock", "-workers", "1", "-fp", "0",
              "-noGenerateSpecTE", "-dump", "dot", "graph.dot", "oracle.tla")
    stats = re.findall(r"^(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue\.$",
                       log, re.M)
    if (len(stats) != 1 or stats[0][2] != "0" or "Model checking completed. No error has been found." not in log):
        raise AssertionError(f"Independent TLC did not establish native closure:\n{log}")
    return read_graph(work / "graph.dot", *map(int, stats[0][:2]))


def edge_call(source, target):
    """Independent call identity from the original stage/round routing."""
    (stage, _), = source.stage.fields
    (after, _), = target.stage.fields
    if source.round > 2:
        if source != target:
            raise ValueError("non-stuttering edge after MAX_ROUNDS")
        return "stuttering", None
    call, expected_stage, advance = {
        "Starting": ("crash", "Sending", 0), "Sending": ("sendMessages", "Receiving", 0),
        "Receiving": ("receiveMessages", "Computing", 0), "Computing": ("computeAction", "Starting", 1),
    }[stage]
    if source.round not in (1, 2) or after != expected_stage or target.round != source.round + advance:
        raise ValueError("edge does not follow original stage/round routing")
    return call, f"receive_round_{source.round}" if call == "receiveMessages" else None


def omissions(state):
    return sum(frozenset() in proc["S"] for proc in state.procState)


def shortest(native, history):
    """Independent outcomes and shortest native lengths for one exact history."""
    frontier = deque((state, 0, 0) for state in native.initial)
    seen = {(state, 0) for state in native.initial}
    lengths = {}
    while frontier:
        source, prefix, depth = frontier.popleft()
        if prefix == len(history):
            lengths.setdefault(omissions(source), depth)
            continue
        for target in native.outgoing[source]:
            _, label = edge_call(source, target)
            if label is not None and label != history[prefix]:
                continue
            index = prefix + (label is not None)
            item = (target, index)
            if item not in seen:
                seen.add(item)
                frontier.append((*item, depth + 1))
    return lengths

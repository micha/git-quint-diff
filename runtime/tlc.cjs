'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { fail } = require('./quint-model.cjs');

const TIMEOUT = 60000;
const VERSION = '0.62.4';
const joinOr = terms => terms.length ? terms.map(t => `(${t})`).join(' \\/ ') : 'FALSE';
const set = items => `{${items.join(', ')}}`;
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;

function findJar() {
  const home = process.env.QUINT_HOME;
  const jar = home && path.resolve(home, `apalache-dist-${VERSION}`, 'apalache/lib/apalache.jar');
  if (!jar || !fs.existsSync(jar)) fail('backend', `missing Apalache ${VERSION} / TLC jar; use nix develop`);
  return jar;
}

function java(jar, cwd, ...args) {
  return spawnSync('java', ['-Xmx512m', '-XX:+UseParallelGC', `-Djava.io.tmpdir=${cwd}`, '-cp', jar, ...args], {
    cwd, timeout: TIMEOUT, killSignal: 'SIGKILL', maxBuffer: 8 * 1024 * 1024, encoding: 'utf8',
  });
}

function summary(log) {
  return log.slice(log.indexOf('\nError:') >= 0 ? log.indexOf('\nError:') + 1 : 0).trim().slice(0, 1800);
}

function translate(jar, cwd, module, ir) {
  fs.writeFileSync(path.join(cwd, 'model.json'), ir);
  const proc = java(jar, cwd, path.join(__dirname, 'Translate.java'), 'model.json', `${module}.tla`);
  if (proc.error || proc.status !== 0) {
    fail('compile', proc.error?.message ?? (summary(proc.stderr) || `translator exited ${proc.status ?? proc.signal}`));
  }
  const names = proc.stdout.trim() ? proc.stdout.trim().split('\n') : [];
  // The pinned pretty-printer emits qualified IR names with underscores. Check
  // the resulting declarations rather than trusting a guessed witness key.
  const variables = names.map(v => v.replaceAll('::', '_'));
  const tla = fs.readFileSync(path.join(cwd, `${module}.tla`), 'utf8');
  const declared = [...tla.matchAll(/^VARIABLE (\w+)$/gm)].map(m => m[1]);
  if (variables.some(v => !/^\w+$/.test(v) || ['qdPrefix', 'qdSite', 'qdValue'].includes(v)) ||
      new Set(variables).size !== variables.length || variables.join(' ') !== declared.join(' ')) {
    fail('compile', 'unsupported compiled variable names or collision with history tracker');
  }
  if (!tla.startsWith('-') || !/^=+\s*$/.test(tla.trimEnd().split('\n').at(-1))) fail('compile', 'malformed compiled module');
  return { variables: variables.sort(), tla };
}

function prefixes(histories) {
  const root = { id: 0, children: new Map(), history: [], selected: false };
  const nodes = [root];
  for (const history of histories) {
    let parent = root;
    for (const label of history) {
      if (!parent.children.has(label)) {
        const child = { id: nodes.length, children: new Map(), history: [...parent.history, label], selected: false };
        parent.children.set(label, child);
        nodes.push(child);
      }
      parent = parent.children.get(label);
    }
    parent.selected = true;
  }
  return nodes;
}

// This relation is also exercised before history filtering in the erasure
// regression. Guards refer only to pre-state operators in the selected instance.
function transition({ branch, id, when, unless }) {
  const guard = when ?? (unless?.length ? `~(${joinOr(unless)})` : null);
  const call = `qdBranch${branch ?? id}`;
  return guard ? `(${guard}) /\\ ${call}` : call;
}

function product(model, leaves, nodes) {
  const hiddenFrom = nodes.filter(n => n.children.size).map(n => n.id);
  const choices = [];
  for (const leaf of leaves) {
    if (leaf.label === undefined) continue;
    const phase = leaf.label === null ? (hiddenFrom.length ? `qdPrefix \\in ${set(hiddenFrom)} /\\ UNCHANGED qdPrefix` : null) :
      joinOr(nodes.filter(n => n.children.has(leaf.label)).map(n =>
        `qdPrefix = ${n.id} /\\ qdPrefix' = ${n.children.get(leaf.label).id}`));
    if (phase && phase !== 'FALSE') choices.push(`(${phase}) /\\ (${transition(leaf)}) /\\ qdSite' = ${leaf.id}`);
  }
  const completed = nodes.filter(n => n.selected).map(n => n.id);
  const endSites = [0, ...leaves.filter(l => typeof l.label === 'string').map(l => l.id)];
  const body = `
VARIABLES qdPrefix, qdSite, qdValue
qdStart == q_init /\\ qdPrefix = 0 /\\ qdSite = 0 /\\ qdValue = {}
qdNative == qdValue = {} /\\ UNCHANGED qdValue /\\ (${joinOr(choices)})
qdCapture == /\\ qdValue = {}
             /\\ qdPrefix \\in ${set(completed)} /\\ qdSite \\in ${set(endSites)}
             /\\ qdValue' = {qdObservation}
             /\\ UNCHANGED <<qdPrefix, qdSite${model.variables.map(v => `, ${v}`).join('')}>>
qdNext == qdNative \\/ qdCapture
`;
  return extend(model.tla, body);
}

function extend(tla, body) {
  return `${tla.trimEnd().replace(/\n=+$/, '')}\n${body}\n====\n`;
}

function runGraph(jar, cwd, module, model, init, next) {
  const tla = `${module}.tla`;
  fs.writeFileSync(path.join(cwd, tla), model.tla);
  fs.writeFileSync(path.join(cwd, `${module}.cfg`), `INIT ${init}\nNEXT ${next}\n`);
  const graphPath = path.join(cwd, 'graph.dot');
  fs.rmSync(graphPath, { force: true });
  const proc = java(jar, cwd, 'tlc2.TLC', '-deadlock', '-workers', '1', '-fp', '0', '-seed', '0',
    '-noGenerateSpecTE', '-dump', 'dot', 'graph.dot', tla);
  if (proc.error) fail('exploration', proc.error.message);
  const log = `${proc.stdout}\n${proc.stderr}`;
  const report = [...log.matchAll(/^(\d+) states generated, (\d+) distinct states found, (\d+) states left on queue\.$/gm)];
  if (proc.status !== 0 || !log.includes('Model checking completed. No error has been found.') ||
      report.length !== 1 || Number(report[0][3]) !== 0) {
    const captureLine = model.tla.split('\n').findIndex(line => line.includes("qdValue' = {qdObservation}")) + 1;
    const captureError = captureLine > 0 && new RegExp(`line ${captureLine},`).test(log);
    fail(captureError ? 'observation' : 'exploration', `TLC did not complete (exit ${proc.status ?? proc.signal}): ${summary(log)}`);
  }
  const generated = Number(report[0][1]), distinct = Number(report[0][2]);
  const initials = /^Finished computing initial states: (\d+) distinct states? generated at /m.exec(log) ??
    /^Finished computing initial states: (\d+) states generated, with (\d+) of them distinct at /m.exec(log);
  if (!initials) fail('evidence', 'missing TLC initial-state counts');
  const [initialGenerated, initialDistinct] = [Number(initials[1]), Number(initials[2] ?? initials[1])];
  if (!fs.existsSync(graphPath) || fs.statSync(graphPath).size > 32 * 1024 * 1024) fail('evidence', 'missing or oversized TLC graph');
  const g = graph(fs.readFileSync(graphPath, 'utf8'), model.variables, distinct);
  const edges = [...g.outgoing.values()].reduce((n, next) => n + next.length, 0);
  if (edges !== generated - initialGenerated || g.initial.length !== initialDistinct) {
    fail('evidence', 'TLC graph counts do not agree with the completed search');
  }
  return { ...g, stats: { generated, distinct, queued: 0 } };
}

// Read the pinned TLC DOT interchange format; unexpected evidence is an error,
// not an empty relation. Graph node IDs are opaque fingerprint strings.
function graph(text, variables, distinct) {
  const bad = () => fail('evidence', 'malformed or incomplete TLC state graph');
  const states = new Map(), outgoing = new Map(), initial = [];
  const lines = text.trimEnd().split('\n');
  if (lines[0] !== 'strict digraph DiskGraph {' || lines.slice(-2).some(l => l !== '}')) bad();
  for (const line of lines.slice(1, -2)) {
    const s = /^(-?\d+) \[label=("(?:[^"\\]|\\.)*")(,style = filled|,tooltip="(?:[^"\\]|\\.)*")\];?$/.exec(line);
    const e = /^(-?\d+) -> (-?\d+) \[label="",color="black",fontcolor="black"\];$/.exec(line);
    if (s) {
      const [, id, raw, info] = s;
      if (states.has(id)) bad();
      let label;
      try { label = JSON.parse(raw); } catch { bad(); }
      const framed = label.startsWith('/\\ ') ? label.slice(3).split('\n/\\ ') : [label];
      const state = Object.create(null);
      for (const part of framed) {
        const binding = /^(\w+) = ([\s\S]+)$/.exec(part);
        if (!binding || Object.hasOwn(state, binding[1])) bad();
        state[binding[1]] = binding[2];
      }
      if (Object.keys(state).sort().join(' ') !== variables.join(' ')) bad();
      states.set(id, Object.fromEntries(variables.map(v => [v, state[v]])));
      if (info === ',style = filled') initial.push(id);
    } else if (e) {
      if (!outgoing.has(e[1])) outgoing.set(e[1], []);
      outgoing.get(e[1]).push(e[2]);
    } else if (!['node [shape=box,style=rounded]', 'nodesep=0.35;', 'subgraph cluster_graph {', 'color="white";'].includes(line) &&
               !/^\{rank = same; [-\d;]*\}$/.test(line)) bad();
  }
  if (states.size !== distinct || (states.size > 0 && !initial.length)) bad();
  for (const [from, to] of outgoing) if (!states.has(from) || to.some(id => !states.has(id))) bad();
  const key = id => JSON.stringify(states.get(id));
  const byState = (a, b) => compare(key(a), key(b));
  initial.sort(byState);
  for (const next of outgoing.values()) next.sort(byState);
  const order = [...initial], predecessor = new Map(initial.map(id => [id, null]));
  for (let i = 0; i < order.length; i++) {
    for (const id of outgoing.get(order[i]) ?? []) {
      if (predecessor.has(id)) continue;
      predecessor.set(id, order[i]);
      order.push(id);
    }
  }
  if (order.length !== distinct) bad();
  return { states, outgoing, initial, order, predecessor };
}

function scalar(raw, type) {
  const text = /^\{(.*)\}$/.exec(raw)?.[1]?.trim();
  if (type === 'int' && /^-?\d+$/.test(text) && Number.isSafeInteger(Number(text))) return Number(text);
  if (type === 'bool' && (text === 'TRUE' || text === 'FALSE')) return text === 'TRUE';
  if (type === 'str' && text?.startsWith('"')) {
    try { const value = JSON.parse(text); if (typeof value === 'string') return value; } catch { /* fail below */ }
  }
  fail('observation', `unsupported or malformed ${type} observation: ${raw}`);
}

function results(g, nodes, leaves, type, variables) {
  const byPrefix = nodes.map(() => new Map());
  const reached = new Set();
  const site = new Map(leaves.map(l => [String(l.id), l]));
  const state = id => Object.fromEntries(variables.map(v => [v, g.states.get(id)[v]]));
  const nativeIds = g.order.filter(id => g.states.get(id).qdValue === '{}');
  const initial = new Set(g.initial);
  const captures = new Set();
  for (const id of nativeIds) {
    const from = g.states.get(id);
    const prefix = nodes[Number(from.qdPrefix)];
    if (!prefix || String(prefix.id) !== from.qdPrefix ||
        (initial.has(id) ? prefix.id !== 0 || from.qdSite !== '0' : site.get(from.qdSite)?.label === undefined)) {
      fail('evidence', 'invalid history progress or site in TLC state');
    }
    reached.add(prefix.id);
    const isEnd = prefix.selected && (from.qdSite === '0' || typeof site.get(from.qdSite)?.label === 'string');
    const observed = new Set();
    for (const next of g.outgoing.get(id) ?? []) {
      const to = g.states.get(next);
      if (to.qdValue !== '{}') {
        observed.add(next);
        continue;
      }
      const label = site.get(to.qdSite)?.label;
      const expected = label === null && prefix.children.size ? prefix.id : prefix.children.get(label)?.id;
      if (expected === undefined || to.qdPrefix !== String(expected)) fail('evidence', 'invalid history edge in TLC graph');
    }
    if (observed.size !== Number(isEnd)) fail('evidence', 'missing or unexpected endpoint observation');
    if (!isEnd) continue;
    const [capture] = observed;
    const row = g.states.get(capture);
    if (row.qdPrefix !== from.qdPrefix || row.qdSite !== from.qdSite ||
        variables.some(v => row[v] !== from[v]) || (g.outgoing.get(capture)?.length ?? 0) !== 0) {
      fail('evidence', 'invalid observation capture edge');
    }
    captures.add(capture);
    const outcome = scalar(row.qdValue, type);
    const frontier = byPrefix[prefix.id];
    if (frontier.has(outcome)) continue;
    const steps = [];
    let current = id;
    while (g.predecessor.get(current) !== null) {
      const leaf = site.get(g.states.get(current).qdSite);
      if (!leaf || leaf.label === undefined || g.states.get(current).qdValue !== '{}') fail('evidence', 'invalid witness site');
      steps.push({ state: state(current), label: leaf.label, site: leaf.site });
      current = g.predecessor.get(current);
    }
    steps.reverse();
    if (g.states.get(current).qdSite !== '0' ||
        JSON.stringify(steps.flatMap(s => s.label === null ? [] : [s.label])) !== JSON.stringify(prefix.history)) {
      fail('evidence', 'witness does not replay the selected history');
    }
    frontier.set(outcome, { initial: state(current), steps });
  }
  if (nativeIds.length + captures.size !== g.states.size) fail('evidence', 'unexpected TLC graph state');
  return { byPrefix, reached };
}

function explore(jar, cwd, module, compiled, leaves, nodes, type) {
  const model = translate(jar, cwd, module, compiled);
  const tracked = ['qdPrefix', 'qdSite', 'qdValue'];
  const g = runGraph(jar, cwd, module, { tla: product(model, leaves, nodes),
    variables: [...model.variables, ...tracked].sort() }, 'qdStart', 'qdNext');
  return { ...results(g, nodes, leaves, type, model.variables), stats: g.stats };
}

module.exports = { findJar, translate, runGraph, extend, transition, prefixes, explore, compare, TIMEOUT };

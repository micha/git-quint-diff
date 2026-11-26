'use strict';

const { createRequire } = require('node:module');
const path = require('node:path');
const { relative } = require('./git-snapshot.cjs');

class ReviewError extends Error {
  constructor(phase, message) { super(message); this.phase = phase; }
}
const fail = (phase, message) => { throw new ReviewError(phase, message); };
const IDENT = /^[a-zA-Z_][a-zA-Z_0-9]*$/;
const OBS = 'qdObservation';
const INIT = 'q::init'; // The public Quint init-to-predicate pass uses this entry name.

function quintApi() {
  try {
    const root = process.env.QUINT_DIFF_QUINT_PACKAGE;
    if (!root) throw new Error('QUINT_DIFF_QUINT_PACKAGE is unset');
    const req = createRequire(path.join(root, 'package.json'));
    if (req('./package.json').version !== '0.33.1') throw new Error('expected Quint 0.33.1');
    return {
      ...req('./dist/src/index.js'),
      ...req('./dist/src/flattening/fullFlattener.js'),
      ...req('./dist/src/ir/initToPredicate.js'),
      right: req('@sweet-monads/either').right,
      serialize: req('./dist/src/cliReporting.js').jsonStringOfOutputStage,
    };
  } catch (error) {
    fail('backend', `${error.message}; use nix develop`);
  }
}

const siteAt = (sourceMap, id) => {
  const loc = sourceMap.get(id);
  if (!loc) fail('binding', 'Quint did not supply a source location');
  return { path: loc.source, line: loc.start.line + 1, column: loc.start.col + 1 };
};
const describe = ({ path, line, column }) => `${path}:${line}:${column}`;

function parseModel(q, snap, config) {
  const ids = q.newIdGenerator();
  const check = (errors, sourceMap, phase) => {
    if (!errors.length) return;
    const e = errors[0];
    const loc = sourceMap.get(e.reference);
    fail(loc?.source === '<observation>' ? 'observation' : phase,
      `${loc ? `${describe(siteAt(sourceMap, e.reference))}: ` : ''}${e.code}: ${e.message}`);
  };
  const lookup = (base, file) => {
    try {
      const key = relative(base, file);
      return { normalizedPath: key, toSourceName: () => key };
    } catch (error) { fail('snapshot', error.message); }
  };
  const load = ({ normalizedPath: name }) => {
    let text;
    try { text = snap.load(name); } catch (error) { fail('snapshot', error.message); }
    const local = q.parsePhase1fromText(q.newIdGenerator(), text, name);
    // The pinned import pass does not forward errors from imported files.
    check(local.errors, local.sourceMap, 'parse');
    return q.right(text);
  };
  const entry = lookup('.', config.entrypoint);
  const initial = q.parsePhase1fromText(ids, load(entry).value, entry.normalizedPath);
  const parsed = q.parsePhase2sourceResolution(ids, {
    lookupPath: lookup, load, stempath: file => path.posix.dirname(file.normalizedPath),
  }, entry, initial);
  check(parsed.errors, parsed.sourceMap, 'parse');
  const location = node => siteAt(parsed.sourceMap, node.id);
  const byName = new Map(parsed.modules.map(m => [m.name, m]));
  for (const m of parsed.modules) {
    for (const d of m.declarations) {
      if (!d.fromSource) continue;
      const from = lookup(path.posix.dirname(location(m).path), `${d.fromSource}.qnt`).normalizedPath;
      const target = byName.get(d.protoName);
      if (!target || location(target).path !== from) {
        fail('snapshot', `module ${d.protoName} is not declared in imported ${from}`);
      }
    }
  }
  const main = byName.get(config.module);
  if (!main || location(main).path !== entry.normalizedPath) fail('binding', `no module ${config.module} in ${entry.normalizedPath}`);
  for (const m of parsed.modules) {
    if (m.declarations.some(d => d.name === INIT || d.name === 'q_init' || d.name?.split('::').some(s => s.startsWith('qd')))) {
      fail('binding', 'names beginning with qd, q::init, and q_init are reserved by this backend');
    }
  }
  const observe = q.parseExpressionOrDeclaration(`val ${OBS} = (\n${config.observe}\n)`, '<observation>', ids, parsed.sourceMap);
  if (observe.kind === 'error') check(observe.errors, parsed.sourceMap, 'observation');
  if (observe.kind !== 'declaration' || observe.decls.length !== 1 || observe.decls[0].name !== OBS) {
    fail('observation', 'expected one read-only Quint expression');
  }
  const obs = observe.decls[0];
  const action = name => {
    const def = main.declarations.find(d => d.name === name && d.kind === 'def' && d.qualifier === 'action');
    if (!def || def.expr.kind === 'lambda') fail('binding', `expected a local nullary action ${name} in ${config.module}`);
    return def;
  };
  const scheduler = action(config.step);
  action(config.init);
  const init = q.parseDefOrThrow(`action ${INIT} = ${config.init}`, ids, parsed.sourceMap);
  main.declarations.push(obs, init);
  const resolved = q.parsePhase4toposort(q.parsePhase3importAndNameResolution(parsed));
  check(resolved.errors, resolved.sourceMap, 'parse');
  const [errors, analysis] = q.analyzeModules(resolved.table, resolved.modules);
  check(errors, resolved.sourceMap, 'typecheck');
  const type = analysis.types.get(obs.id)?.type?.kind;
  const effect = analysis.effects.get(obs.id)?.effect;
  if (!['int', 'str', 'bool'].includes(type) || effect?.kind !== 'concrete' || effect.components.some(c => c.kind !== 'read')) {
    fail('observation', 'expected a read-only integer, string, or Boolean observation');
  }
  return { ids, resolved, location, scheduler, analysis, type };
}

const opcode = (e, name) => e.kind === 'app' && e.opcode === name;
const scalar = e => ['int', 'str', 'bool'].includes(e.kind) ||
  ((opcode(e, 'iuminus') || opcode(e, 'ineg')) && e.args.length === 1 && e.args[0].kind === 'int');
const atPosition = (site, selector) => site.line === selector.line && site.column === selector.column;

function bind(model, config) {
  const { location, scheduler, resolved, analysis } = model;
  const branches = opcode(scheduler.expr, 'actionAny') ? scheduler.expr.args : [scheduler.expr];
  if (!branches.length) fail('binding', 'expected a nonempty scheduler');
  const definitions = new Map();
  for (const module of resolved.modules) {
    for (const d of module.declarations) {
      if (d.kind === 'def' && d.qualifier === 'action') definitions.set(d.id, { module: module.name, action: d.name, ...location(d) });
    }
  }
  const directCall = expr => {
    if (expr.kind !== 'name' && expr.kind !== 'app') return null;
    const def = resolved.table.get(expr.id);
    const declaration = def && definitions.get(def.id);
    return declaration && { expr, site: { ...location(expr), callee: `${declaration.module}::${declaration.action}`, declaration } };
  };
  // Any other action call in a public leaf (including a nested or locally
  // bound one) would make this more than the supported single-call leaf.
  function calls(expr) {
    const own = directCall(expr);
    const children = expr.kind === 'app' ? expr.args : expr.kind === 'let' ? [expr.opdef.expr, expr.expr] :
      expr.kind === 'lambda' ? [expr.expr] : [];
    return [...(own ? [own] : []), ...children.flatMap(calls)];
  }
  const leaves = branches.map((expr, index) => ({ id: index + 1, label: undefined, expr, site: location(expr) }));
  const bindable = leaves.flatMap(leaf => (opcode(leaf.expr, 'actionAll') ? leaf.expr.args : [leaf.expr])
    .map(directCall).filter(Boolean).map(c => ({ ...c, leaf })));
  const used = new Set();
  const bindings = Object.fromEntries(Object.entries(config.bindings).map(([label, selector]) => {
    if (selector === null) return [label, null];
    const matches = c => c.site.callee === selector.callee &&
      (selector.line === undefined || atPosition(c.site, selector));
    const candidates = bindable.filter(matches);
    if (candidates.length !== 1) {
      if (!candidates.length && leaves.some(l => calls(l.expr).some(matches))) {
        fail('binding', `${label}: unsupported scheduler nesting or locally bound call for ${selector.callee}`);
      }
      fail('binding', `${label}: ${candidates.length ? 'ambiguous' : 'no matching'} direct call site for ${selector.callee}`);
    }
    const { leaf, expr, site } = candidates[0];
    if (used.has(leaf)) fail('binding', `${label}: duplicate or conflicting selector at ${describe(site)}`);
    const guardOrAssignment = term => {
      if (opcode(term, 'assign')) return true;
      const effect = analysis.effects.get(term.id)?.effect;
      return effect?.kind === 'concrete' && effect.components.every(c => c.kind === 'read');
    };
    if (calls(leaf.expr).length !== 1 || expr.args?.some(arg => !scalar(arg)) ||
        (opcode(leaf.expr, 'actionAll') && leaf.expr.args.some(term => term !== expr && !guardOrAssignment(term)))) {
      fail('binding', `${label}: unsupported public leaf or arguments at ${describe(site)}; use one direct call with scalar literals`);
    }
    used.add(leaf);
    leaf.label = label;
    leaf.site = site;
    return [label, site];
  }));
  const hidden = config.hidden.map(selector => {
    const candidates = leaves.filter(leaf => atPosition(location(leaf.expr), selector));
    if (candidates.length !== 1 || used.has(candidates[0])) {
      fail('binding', `hidden selector ${selector.line}:${selector.column} is missing or conflicts with another binding`);
    }
    const leaf = candidates[0];
    if (['actionAny', 'ite', 'matchVariant'].some(op => opcode(leaf.expr, op))) {
      fail('binding', `unsupported nested scheduler at ${describe(leaf.site)}`);
    }
    used.add(leaf);
    leaf.label = null;
    return leaf.site;
  });
  return { leaves, bindings, hidden, scheduler: location(scheduler) };
}

function compilation(q, model, binding, config) {
  const { ids, resolved, analysis, scheduler } = model;
  const { flattenedModules, flattenedAnalysis, flattenedTable } = q.flattenModules(
    resolved.modules, resolved.table, ids, resolved.sourceMap, analysis,
  );
  const module = flattenedModules.find(m => m.name === config.module);
  const result = q.convertInit({ ...module, declarations: module.declarations.filter(d => d.qualifier !== 'run') },
    flattenedTable, flattenedAnalysis.modes);
  if (result.isLeft()) fail('compile', result.value.map(e => `${e.code}: ${e.message}`).join('; '));
  const native = result.value;
  const flatStep = native.declarations.find(d => d.id === scheduler.id);
  const flatBranches = flatStep && (opcode(flatStep.expr, 'actionAny') ? flatStep.expr.args : [flatStep.expr]);
  if (!flatBranches || flatBranches.length !== binding.leaves.length ||
      flatBranches.some((b, i) => b.id !== binding.leaves[i].expr.id)) {
    fail('compile', 'cannot carry scheduler source identities through Quint flattening');
  }
  // Add independent aliases for whole alternatives, not replacements for the
  // original scheduler. The converter receives the same typed branch IR.
  const helpers = flatBranches.map((expr, i) => {
    const id = ids.nextId();
    flattenedAnalysis.types.set(id, flattenedAnalysis.types.get(expr.id));
    return { id, kind: 'def', name: `qdBranch${i + 1}`, qualifier: 'action', expr };
  });
  return q.serialize({ stage: 'compiling', modules: [{ ...native, declarations: [...native.declarations, ...helpers] }],
    types: flattenedAnalysis.types, table: flattenedTable });
}

module.exports = { ReviewError, fail, IDENT, quintApi, parseModel, bind, compilation };

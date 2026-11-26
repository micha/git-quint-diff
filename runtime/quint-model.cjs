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
const STEP = 'qdScheduler';
const INSTANCE = 'qdReview';
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
      walkModule: req('./dist/src/ir/IRVisitor.js').walkModule,
      right: req('@sweet-monads/either').right,
      serialize: req('./dist/src/cliReporting.js').jsonStringOfOutputStage,
    };
  } catch (error) {
    fail('backend', `cannot load the pinned Quint package: ${error.message}`);
  }
}

const siteAt = (sourceMap, id) => {
  const loc = sourceMap.get(id);
  if (!loc) fail('binding', 'Quint did not supply a source location');
  return { path: loc.source, line: loc.start.line + 1, column: loc.start.col + 1 };
};
const describe = ({ path, line, column }) => `${path}:${line}:${column}`;

function parseModel(q, snap, config, { discovery = false } = {}) {
  const ids = q.newIdGenerator();
  const check = (errors, sourceMap, phase) => {
    if (!errors.length) return;
    const e = errors[0];
    const loc = sourceMap.get(e.reference);
    const source = loc?.source;
    const stage = source === '<observation>' ? 'observation' :
      ['<label predicate>', '<instance>', '<action selector>'].includes(source) ? 'binding' : phase;
    fail(stage, `${loc ? `${describe(siteAt(sourceMap, e.reference))}: ` : ''}${e.code}: ${e.message}`);
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
    if (m.name.startsWith('qd') || m.declarations.some(d => d.name === INIT || d.name === 'q_init' ||
        d.name?.split('::').some(s => s.startsWith('qd')))) {
      fail('binding', 'names beginning with qd, q::init, and q_init are reserved by this backend');
    }
  }
  const definitions = new Map();
  for (const m of parsed.modules) {
    for (const d of m.declarations) {
      if (d.kind === 'def' && d.qualifier === 'action') definitions.set(d.id, { module: m.name, action: d.name, ...location(d) });
    }
  }
  // Instantiate the entry module using normal Quint resolution, including constants
  // re-exported by the entrypoint. Do not substitute text into the model declarations.
  let selected = main;
  const constants = Object.entries(config.constants ?? {});
  if (constants.length) {
    const args = constants.map(([name]) => `${name} = 0`).join(', ');
    const wrapper = q.parsePhase1fromText(ids, `module ${INSTANCE} { import ${main.name}(${args}).* }`, '<instance>');
    check(wrapper.errors, wrapper.sourceMap, 'binding');
    [selected] = wrapper.modules;
    const values = new Map(constants);
    // Construct typed scalar syntax directly: a JSON-escaped string does not
    // necessarily have the same value when read as a Quint source literal.
    const instance = selected.declarations[0];
    instance.overrides = instance.overrides.map(([name, { id }]) => {
      const value = values.get(name.name);
      return [name, typeof value === 'number' ? { id, kind: 'int', value: BigInt(value) } :
        { id, kind: typeof value === 'string' ? 'str' : 'bool', value }];
    });
    for (const [id, loc] of wrapper.sourceMap) parsed.sourceMap.set(id, loc);
    parsed.modules.push(selected);
  }
  const expression = (name, text, source, phase) => {
    const p = q.parseExpressionOrDeclaration(`val ${name} = (\n${text}\n)`, source, ids, parsed.sourceMap);
    if (p.kind === 'error') check(p.errors, parsed.sourceMap, phase);
    if (p.kind !== 'declaration' || p.decls.length !== 1 || p.decls[0].name !== name) {
      fail(phase, 'expected one read-only Quint expression');
    }
    return p.decls[0];
  };
  const selectAction = (alias, name) => {
    const p = q.parseExpressionOrDeclaration(`action ${alias} = ${name}`, '<action selector>', ids, parsed.sourceMap);
    if (p.kind === 'error') check(p.errors, parsed.sourceMap, 'binding');
    if (p.kind !== 'declaration' || p.decls.length !== 1 || p.decls[0].expr?.kind !== 'name') {
      fail('binding', `expected action name ${name}`);
    }
    return p.decls[0];
  };
  const predicates = new Map();
  let obs, init;
  if (!discovery) {
    obs = expression(OBS, config.observe, '<observation>', 'observation');
    for (const [label, selector] of Object.entries(config.bindings)) {
      if (selector?.when === undefined) continue;
      const def = expression(`qdWhen${predicates.size + 1}`, selector.when, '<label predicate>', 'binding');
      predicates.set(label, def);
    }
    init = selectAction(INIT, config.init);
    selected.declarations.push(obs, ...predicates.values(), init);
  }
  const step = selectAction(STEP, config.step);
  selected.declarations.push(step);
  const resolved = q.parsePhase4toposort(q.parsePhase3importAndNameResolution(parsed));
  check(resolved.errors, resolved.sourceMap, 'parse');
  const { table } = resolved;
  const originalAction = (ref, name) => {
    const def = table.get(ref.expr.id);
    if (!definitions.has(def?.id) || def.expr.kind === 'lambda') {
      fail('binding', `expected a visible nullary action ${name} in ${config.module}`);
    }
    return def;
  };
  if (init) originalAction(init, config.init);
  const scheduler = originalAction(step, config.step);
  const [errors, analysis] = q.analyzeModules(table, resolved.modules);
  check(errors, resolved.sourceMap, 'typecheck');
  const type = obs && analysis.types.get(obs.id)?.type?.kind;
  if (obs && (!['int', 'str', 'bool'].includes(type) || !readOnly(analysis, obs))) {
    fail('observation', 'expected a read-only integer, string, or Boolean observation');
  }
  return { ids, resolved, location, scheduler, definitions, predicates, analysis, type, module: selected.name };
}

const opcode = (e, name) => e.kind === 'app' && e.opcode === name;
const scalar = e => ['int', 'str', 'bool'].includes(e.kind) ||
  ((opcode(e, 'iuminus') || opcode(e, 'ineg')) && e.args.length === 1 && e.args[0].kind === 'int');
const atPosition = (site, selector, entrypoint) => site.path === (selector.path ?? entrypoint) &&
  site.line === selector.line && site.column === selector.column;
const readOnly = (analysis, expr) => {
  const effect = analysis.effects.get(expr.id)?.effect;
  return effect?.kind === 'concrete' && effect.components.every(c => c.kind === 'read');
};

// Follow action positions only. A route records the actual indices (not a
// computed condition or call name), and is reused after instance flattening.
function schedulerLeaves(expr, analysis, location, flattened = false, route = []) {
  const branch = (op, i, child) => schedulerLeaves(child, analysis, location, flattened, [...route, { op, i }]);
  if (opcode(expr, 'actionAny')) return expr.args.flatMap((arg, i) => branch('actionAny', i, arg));
  if (opcode(expr, 'ite')) {
    if (expr.args.length !== 3 || !readOnly(analysis, expr.args[0])) {
      fail('binding', `expected a read-only scheduler condition at ${describe(location(expr))}`);
    }
    return [1, 2].flatMap(i => branch('ite', i, expr.args[i]));
  }
  if (opcode(expr, 'matchVariant')) {
    const [value, ...arms] = expr.args;
    const unit = type => type?.kind === 'tup' && (type.fields.kind === 'empty' ||
      (type.fields.kind === 'row' && type.fields.fields.length === 0 && type.fields.other.kind === 'empty'));
    if (!value || !readOnly(analysis, value) || !arms.length || arms.length % 2 !== 0 || arms.some((arm, i) => {
      if (i % 2 === 0) return arm.kind !== 'str' || arm.value === '_';
      return arm.kind !== 'lambda' || arm.params.length !== 1 || (!flattened && arm.params[0].name !== '_') ||
        !unit(analysis.types.get(arm.id)?.type?.args?.[0]);
    })) fail('binding', `unsupported scheduler match at ${describe(location(expr))}; expected payload-free arms`);
    return arms.flatMap((arm, i) => i % 2 === 0 ? [] : branch('matchVariant', i + 1, arm.expr));
  }
  return [{ expr, route, site: location(expr), cases: [] }];
}

function labelPredicate(model, label, when) {
  const { predicates, resolved, analysis } = model;
  const def = predicates.get(label);
  const e = def.expr;
  const [lhs, rhs] = e.args ?? [];
  const variable = lhs?.kind === 'name' && resolved.table.get(lhs.id);
  if (!opcode(e, 'eq') || e.args.length !== 2 || variable?.kind !== 'var' || !scalar(rhs) ||
      !readOnly(analysis, def)) {
    fail('binding', `${label}: expected a pre-state scalar variable == scalar literal predicate`);
  }
  const value = rhs.kind === 'app' ? -rhs.args[0].value : rhs.value;
  return { helper: def.name, variable: variable.id, name: lhs.name, value, when };
}

function schedulerSites(model) {
  const { location, scheduler, resolved, analysis, definitions } = model;
  const branches = schedulerLeaves(scheduler.expr, analysis, location);
  if (!branches.length) fail('binding', 'expected a nonempty scheduler');
  const directCall = expr => {
    if (expr.kind !== 'name' && expr.kind !== 'app') return null;
    const def = resolved.table.get(expr.id);
    const declaration = def && definitions.get(def.id);
    return declaration && { expr, site: { ...location(expr), callee: `${declaration.module}::${declaration.action}`, declaration } };
  };
  function collectCalls(expr, found) {
    const call = directCall(expr);
    if (call) found.push(call);
    const children = expr.kind === 'app' ? expr.args : expr.kind === 'let' ? [expr.opdef.expr, expr.expr] :
      expr.kind === 'lambda' ? [expr.expr] : [];
    for (const child of children) collectCalls(child, found);
  }
  const guardOrAssignment = term => opcode(term, 'assign') || readOnly(analysis, term);
  return branches.map(leaf => {
    const terms = opcode(leaf.expr, 'actionAll') ? leaf.expr.args : [leaf.expr];
    const direct = terms.map(directCall).filter(Boolean);
    const calls = [];
    collectCalls(leaf.expr, calls);
    const expr = direct[0]?.expr;
    const publicCall = direct.length === 1 && calls.length === 1 && !expr.args?.some(arg => !scalar(arg)) &&
      terms.every(term => term === expr || guardOrAssignment(term)) ? direct[0] : null;
    return { ...leaf, direct, calls, publicCall };
  });
}

function discover(model) {
  const branches = schedulerSites(model);
  const counts = new Map();
  const callKey = ({ path, line, column, callee }) => JSON.stringify([path, line, column, callee]);
  for (const branch of branches) {
    for (const { site } of branch.direct) {
      const key = callKey(site);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return {
    scheduler: model.definitions.get(model.scheduler.id),
    leaves: branches.map(branch => {
      const site = branch.publicCall?.site;
      if (!site || counts.get(callKey(site)) !== 1) return { leaf: branch.site, call: null };
      const { declaration, ...selector } = site;
      return { leaf: branch.site, call: { selector, declaration } };
    }),
  };
}

function bind(model, config) {
  const entrypoint = relative('.', config.entrypoint);
  const branches = schedulerSites(model);
  const direct = branches.flatMap(leaf => leaf.direct.map(c => ({ ...c, leaf })));
  const bindings = Object.fromEntries(Object.entries(config.bindings).map(([label, selector]) => {
    if (selector === null) return [label, null];
    const matches = c => c.site.callee === selector.callee &&
      (selector.line === undefined || atPosition(c.site, selector, entrypoint));
    const candidates = direct.filter(matches);
    if (candidates.length !== 1) {
      if (!candidates.length && branches.some(l => l.calls.some(matches))) {
        fail('binding', `${label}: unsupported scheduler nesting or locally bound call for ${selector.callee}`);
      }
      fail('binding', `${label}: ${candidates.length ? 'ambiguous' : 'no matching'} direct call site for ${selector.callee}`);
    }
    const { leaf, site } = candidates[0];
    if (!leaf.publicCall) {
      fail('binding', `${label}: unsupported public leaf or arguments at ${describe(site)}; use one direct call with scalar literals`);
    }
    const predicate = selector.when === undefined ? null : labelPredicate(model, label, selector.when);
    if (leaf.cases.some(c => !predicate || !c.predicate || predicate.variable !== c.predicate.variable ||
        predicate.name !== c.predicate.name || predicate.value === c.predicate.value)) {
      fail('binding', `${label}: duplicate or conflicting selector at ${describe(site)}; shared sites need distinct literals of one variable`);
    }
    const resolvedSite = predicate ? { ...site, when: predicate.when } : site;
    leaf.cases.push({ label, site: resolvedSite, predicate });
    return [label, resolvedSite];
  }));
  const hidden = config.hidden.map(selector => {
    const candidates = branches.filter(leaf => atPosition(leaf.site, selector, entrypoint));
    if (candidates.length !== 1 || candidates[0].cases.length) {
      fail('binding', `hidden selector ${selector.path ?? entrypoint}:${selector.line}:${selector.column} is missing or conflicts with another binding`);
    }
    const leaf = candidates[0];
    leaf.cases.push({ label: null, site: leaf.site, predicate: null });
    return leaf.site;
  });
  let extra = branches.length;
  const leaves = branches.flatMap((leaf, i) => {
    // Unlisted sites (or unmatched predicate values) retain their native edges
    // in the unfiltered relation, but aren't permitted in the history product.
    const cases = leaf.cases.map(c => ({ label: c.label, site: c.site, when: c.predicate?.helper }));
    if (!cases.length || cases.some(c => c.when)) cases.push({ site: leaf.site, unless: cases.map(c => c.when) });
    return cases.map((c, j) => ({ ...c, branch: i + 1, id: j === 0 ? i + 1 : ++extra }));
  });
  return { branches, leaves, bindings, hidden, scheduler: model.definitions.get(model.scheduler.id) };
}

function compilation(q, model, binding) {
  const { ids, resolved, analysis } = model;
  const { flattenedModules, flattenedAnalysis, flattenedTable } = q.flattenModules(
    resolved.modules, resolved.table, ids, resolved.sourceMap, analysis,
  );
  const module = flattenedModules.find(m => m.name === model.module);
  if (module.declarations.some(d => d.kind === 'const')) fail('compile', 'selected instance has unassigned constants');
  const result = q.convertInit({ ...module, declarations: module.declarations.filter(d => d.qualifier !== 'run') },
    flattenedTable, flattenedAnalysis.modes);
  if (result.isLeft()) fail('compile', result.value.map(e => `${e.code}: ${e.message}`).join('; '));
  const native = result.value;
  const alias = native.declarations.find(d => d.name === STEP);
  const flatStep = flattenedTable.get(alias?.expr.id);
  const { sourceMap } = resolved;
  const checkSource = (actual, expected) => {
    if (!actual || describe(siteAt(sourceMap, actual.id)) !== describe(expected)) {
      fail('compile', 'cannot carry scheduler source identities through Quint flattening');
    }
  };
  checkSource(flatStep, binding.scheduler);
  const flatBranches = schedulerLeaves(flatStep.expr, flattenedAnalysis, model.location, true);
  const routeKey = JSON.stringify;
  if (flatBranches.length !== binding.branches.length) fail('compile', 'scheduler structure changed during Quint flattening');
  flatBranches.forEach((leaf, i) => {
    const original = binding.branches[i];
    checkSource(leaf.expr, original.site);
    if (routeKey(leaf.route) !== routeKey(original.route)) fail('compile', 'scheduler route changed during Quint flattening');
    const site = original.cases[0]?.site;
    if (site?.declaration) {
      const terms = opcode(leaf.expr, 'actionAll') ? leaf.expr.args : [leaf.expr];
      const call = terms.find(term => describe(model.location(term)) === describe(site));
      checkSource(call && flattenedTable.get(call.id), site.declaration);
    }
  });
  const disabled = term => {
    const id = ids.nextId();
    flattenedAnalysis.types.set(id, flattenedAnalysis.types.get(term.id));
    return { id, kind: 'bool', value: false };
  };
  // Select an occurrence by specializing only branching positions. Reuse the
  // original typed conditions, scrutinee, lambdas and leaf; unselected arms
  // cannot step. The native scheduler is also compiled, unchanged.
  const restrict = (expr, route, depth = 0) => {
    if (depth === route.length) return expr;
    const { op, i } = route[depth];
    if (op === 'actionAny') return restrict(expr.args[i], route, depth + 1);
    if (op === 'ite') return { ...expr, args: expr.args.map((arg, j) =>
      j === 0 ? arg : j === i ? restrict(arg, route, depth + 1) : disabled(arg)) };
    return { ...expr, args: expr.args.map((arg, j) => j < 2 || j % 2 !== 0 ? arg :
      { ...arg, expr: j === i ? restrict(arg.expr, route, depth + 1) : disabled(arg.expr) }) };
  };
  const helpers = flatBranches.map(({ route }, i) => {
    const expr = restrict(flatStep.expr, route);
    const id = ids.nextId();
    flattenedAnalysis.types.set(id, flattenedAnalysis.types.get(expr.id));
    return { id, kind: 'def', name: `qdBranch${i + 1}`, qualifier: 'action', expr };
  });
  // The pinned TLA pretty-printer places string contents inside quotes without
  // escaping them. Reject literals that it cannot pass through losslessly.
  q.walkModule({ enterLiteral: expr => {
    if (expr.kind === 'str' && /["\\\x00-\x1f\x7f\p{Surrogate}]/u.test(expr.value)) {
      fail('compile', `${describe(model.location(expr))}: string literal cannot be translated losslessly`);
    }
  } }, native);
  return q.serialize({ stage: 'compiling', modules: [{ ...native, declarations: [...native.declarations, ...helpers] }],
    types: flattenedAnalysis.types, table: flattenedTable });
}

module.exports = { ReviewError, fail, IDENT, quintApi, parseModel, discover, bind, compilation };

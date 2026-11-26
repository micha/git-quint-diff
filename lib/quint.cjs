const { createRequire } = require('node:module');
const { join, posix } = require('node:path');
const { repoPath } = require('./snapshot.cjs');

// Type- and effect-check the adapter calls before passing runtime values to them.
const contractModule = 'gitQuintDiffContract';
const contractPath = '<git-quint-diff adapter contract>';
const contract = `module ${contractModule} {
  import review as model
  pure val labels: Set[str] = model::publicActions
  pure def text(value: str): str = value
  pure def start(scenario) = model::initialStates(text(scenario))
  pure def advance(state, label) = model::successors(state, text(label))
  pure def observeState(state) = text(model::observe(state))
  pure def compatible(scenario: str, label: str): Set[str] = {
    val initial = start(scenario)
    initial.union(initial.map(state => advance(state, label)).flatten()).map(state => observeState(state))
  }
}`;

const maxSetElements = 10_000n;

function unwrap(result, context) {
  if (result.isLeft()) {
    const { code, message } = result.value;
    throw new Error(`${context}: ${code} ${message}`);
  }
  return result.value;
}

function check(errors, sourceMap) {
  if (!errors.length) return;
  throw new Error(errors.map(({ code, message, reference }) => {
    const loc = sourceMap.get(reference);
    const where = loc ? `${loc.source}:${loc.start.line + 1}:${loc.start.col + 1}: ` : '';
    return `${where}${code} ${message}`;
  }).join('\n'));
}

function byText(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

function sortEncoded(values) {
  return values.map(value => [JSON.stringify(value), value])
    .sort(([a], [b]) => byText(a, b)).map(([, value]) => value);
}

// Encode evaluated data, not source snippets or pretty-printed expressions.
function encode(expr) {
  if (expr.kind === 'bool' || expr.kind === 'str') return expr.value;
  if (expr.kind === 'int') return { '#bigint': String(expr.value) };
  if (expr.kind === 'app') {
    const args = expr.args.map(encode);
    switch (expr.opcode) {
      case 'List': return args;
      case 'Tup': return { '#tup': args };
      case 'Set': return { '#set': sortEncoded(args) };
      case 'Map': return { '#map': sortEncoded(args.map(tuple => tuple['#tup'])) };
      case 'variant': return { '#variant': args };
      case 'Rec': {
        const fields = [];
        for (let i = 0; i < args.length; i += 2) fields.push([args[i], args[i + 1]]);
        return Object.fromEntries(fields.sort(([a], [b]) => byText(a, b)));
      }
    }
  }
  throw new Error(`unsupported state value (${expr.kind === 'app' ? expr.opcode : expr.kind})`);
}

function elements(value, operation) {
  if (!value.isSetLike) throw new Error(`${operation} must return a set`);
  const size = unwrap(value.cardinality(), operation);
  if (size > maxSetElements) throw new Error(`${operation} exceeds the ${maxSetElements}-element set limit`);
  return [...value];
}

function compileReview(snapshot, entry) {
  const packagePath = process.env.QUINT_DIFF_QUINT_PACKAGE;
  if (!packagePath) throw new Error('Quint runtime unavailable; run inside nix develop');
  const load = createRequire(join(packagePath, 'package.json'));
  if (load('./package.json').version !== '0.33.1') throw new Error('expected pinned Quint 0.33.1');
  const quint = load('./dist/src/index.js');
  const { flattenModules } = load('./dist/src/flattening/fullFlattener.js');
  const { Builder, buildDef } = load('./dist/src/runtime/impl/builder.js');
  const { Context } = load('./dist/src/runtime/impl/Context.js');
  const { rv } = load('./dist/src/runtime/impl/runtimeValue.js');
  const { newTraceRecorder } = load('./dist/src/runtime/trace.js');
  const { right } = load('@sweet-monads/either');
  const gen = quint.newIdGenerator();
  const lookup = path => ({ normalizedPath: path, toSourceName: () => path });
  const parse = (source, path, ids = gen) => {
    const parsed = quint.parsePhase1fromText(ids, source, path);
    check(parsed.errors, parsed.sourceMap);
    return parsed;
  };
  const resolver = {
    lookupPath: (stem, name) => lookup(repoPath(stem, name)),
    stempath: path => posix.dirname(path.normalizedPath),
    load(path) {
      const source = snapshot.read(path.normalizedPath);
      // The pinned parser's phase 2 does not propagate syntax errors from imports.
      parse(source, path.toSourceName(), quint.newIdGenerator());
      return right(source);
    },
  };
  const source = parse(snapshot.read(entry), entry);
  if (!source.modules.some(module => module.name === 'review')) throw new Error(`${entry} must define module review`);
  const resolved = quint.parsePhase2sourceResolution(gen, resolver, lookup(entry), source);
  check(resolved.errors, resolved.sourceMap);
  if (resolved.modules.some(module => module.name === contractModule)) {
    throw new Error(`module name ${contractModule} is reserved`);
  }
  const wrapper = parse(contract, contractPath);
  const named = quint.parsePhase3importAndNameResolution({
    modules: resolved.modules.concat(wrapper.modules),
    sourceMap: new Map([...resolved.sourceMap, ...wrapper.sourceMap]),
    errors: [],
  });
  check(named.errors, named.sourceMap);
  const sorted = quint.parsePhase4toposort(named);
  check(sorted.errors, sorted.sourceMap);
  const [errors, analysis] = quint.analyzeModules(sorted.table, sorted.modules);
  check(errors, sorted.sourceMap);
  const { flattenedModules, flattenedTable } = flattenModules(sorted.modules, sorted.table, gen, sorted.sourceMap, analysis);
  const declarations = flattenedModules.find(module => module.name === contractModule).declarations;
  const builder = new Builder(flattenedTable, false);
  const noRandomChoice = () => { throw new Error('random choice is not supported in a review adapter'); };
  const rng = { next: noRandomChoice, setState: noRandomChoice, getState: () => 0n };
  const context = new Context(newTraceRecorder(0, rng), noRandomChoice, builder.varStorage);
  const build = name => buildDef(builder, declarations.find(def => def.name === name));
  const call = (name, evaluation, ...args) => unwrap(
    unwrap(evaluation(context), name).toArrow()(context, args), name,
  );
  const start = build('start');
  const advance = build('advance');
  const observe = build('observeState');

  return {
    labels: new Set(elements(unwrap(build('labels')(context), 'publicActions'), 'publicActions').map(value => value.toStr())),
    initialStates: scenario => elements(call('initialStates', start, rv.mkStr(scenario)), 'initialStates'),
    successors: (state, label) => elements(call('successors', advance, state, rv.mkStr(label)), 'successors'),
    observe: state => call('observe', observe, state).toStr(),
    encodeState: state => encode(rv.toQuintEx(state)),
  };
}

module.exports = { compileReview };

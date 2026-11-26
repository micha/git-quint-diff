'use strict';

// Compare the original flattened scheduler with the whole alternatives reused
// by the CLI history product, before applying a history filter. A separate,
// hand-derived graph prevents a common compilation bug from passing both sides.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { snapshot } = require('../runtime/git-snapshot.cjs');
const { quintApi, parseModel, bind, compilation } = require('../runtime/quint-model.cjs');
const { findJar, translate, runGraph, extend } = require('../runtime/tlc.cjs');

const [revision, commit, input] = process.argv.slice(2);
const config = JSON.parse(input);
const q = quintApi();
const parsed = parseModel(q, snapshot(commit), config);
const bound = bind(parsed, config);
const ir = compilation(q, parsed, bound, config);
const jar = findJar();
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'quint-projection-'));

function graphSets(graph, variable, labelBySite) {
  const states = new Set(), initial = new Set(), edges = new Set(), tagged = new Set();
  const projected = new Map();
  for (const [id, state] of graph.states) {
    const from = state[variable];
    const targets = new Set();
    states.add(from);
    projected.set(id, targets);
    for (const target of graph.outgoing.get(id) ?? []) {
      const successor = graph.states.get(target);
      const to = successor[variable];
      targets.add(to);
      edges.add(`${from}->${to}`);
      if (labelBySite) tagged.add(`${from}-${labelBySite.get(successor.qdSite)}->${to}`);
    }
  }
  for (const id of graph.initial) initial.add(graph.states.get(id)[variable]);
  return { states, initial, edges, tagged, projected };
}

function checkErasure(native, taggedGraph, augmented, variable) {
  assert.deepEqual(augmented.initial, native.initial, 'initial projection differs');
  assert.deepEqual(augmented.states, native.states, 'reachable state projection differs');
  for (const [id, state] of taggedGraph.states) {
    const from = state[variable];
    const targets = new Set([...native.edges].filter(edge => edge.startsWith(`${from}->`)).map(e => e.split('->')[1]));
    assert.deepEqual(augmented.projected.get(id), targets,
      `outgoing native projection differs from x=${from}, site=${state.qdSite}`);
  }
}

try {
  const model = translate(jar, dir, config.module, ir);
  assert.equal(model.variables.length, 1);
  const [variable] = model.variables;
  const original = runGraph(jar, dir, config.module, model, 'q_init', config.step);
  const native = graphSets(original, variable);
  const changed = revision === 'changed';
  assert.deepEqual(native.initial, new Set(['0']));
  assert.deepEqual(native.states, new Set(changed ? ['0', '1', '2', '3', '4'] : ['0', '1', '2', '3']));
  const expected = new Set(['0->1', '0->2', '1->3', '2->3', '3->0']);
  if (changed) for (const edge of ['1->4', '2->4', '4->0']) expected.add(edge);
  assert.deepEqual(native.edges, expected);

  function taggedGraph(suppressInitialChoice = false) {
    const branches = bound.leaves.map(({ id }) => {
      const keep = suppressInitialChoice && id === 1 ? ` /\\ ~(qdSite = 0 /\\ ${variable}' = 2)` : '';
      return `(qdBranch${id} /\\ qdSite' = ${id}${keep})`;
    });
    const tla = extend(model.tla, `
VARIABLE qdSite
qdFullInit == q_init /\\ qdSite = 0
qdFullNext == ${branches.join(' \\/ ')}
`);
    return runGraph(jar, dir, config.module, { tla, variables: [...model.variables, 'qdSite'].sort() },
      'qdFullInit', 'qdFullNext');
  }

  // Verify occurrence identity directly: swapped equal-argument calls cannot be
  // distinguished by before/after edges even when the labels are observed.
  const actualLabels = new Map(bound.leaves.map(({ id, label }) => [String(id), label ?? 'hidden']));
  const expectedOrder = revision === 'old' ? ['hidden', 'alpha', 'beta', 'hidden'] : ['hidden', 'beta', 'alpha', 'hidden'];
  const expectedLabels = new Map(expectedOrder.map((label, index) => [String(index + 1), label]));
  const expectedTagged = new Set([
    '0-hidden->1', '0-hidden->2', '3-hidden->0', '1-alpha->3', '2-alpha->3',
    `1-beta->${changed ? 4 : 3}`, `2-beta->${changed ? 4 : 3}`,
  ]);
  if (changed) expectedTagged.add('4-hidden->0');
  const checkLabels = (augmented, labels) => {
    assert.deepEqual(augmented.tagged, expectedTagged, 'unexpected labeled native edges');
    assert.deepEqual(labels, expectedLabels, 'unexpected physical call-site identity');
  };
  const tagged = taggedGraph();
  const augmented = graphSets(tagged, variable, actualLabels);
  checkErasure(native, tagged, augmented, variable);
  checkLabels(augmented, actualLabels);

  if (revision === 'old') {
    const dropped = taggedGraph(true);
    const projection = graphSets(dropped, variable, actualLabels);
    assert.deepEqual(projection.edges, native.edges, 'control should retain the global edge union');
    assert.throws(() => checkErasure(native, dropped, projection, variable), /outgoing native projection differs/);
    const swapped = new Map(actualLabels);
    swapped.set('2', 'beta');
    swapped.set('3', 'alpha');
    const mislabeled = graphSets(tagged, variable, swapped);
    checkErasure(native, tagged, mislabeled, variable);
    assert.deepEqual(mislabeled.tagged, augmented.tagged, 'equal-effect control should retain even the tagged edge union');
    assert.throws(() => checkLabels(mislabeled, swapped), /unexpected physical call-site identity/);
  }
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

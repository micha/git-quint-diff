'use strict';

// Exercise the actual compiled and classified branches, before the history
// filter. The Python test checks them against a separately compiled scheduler.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { snapshot } = require('../runtime/git-snapshot.cjs');
const { quintApi, parseModel, bind, compilation } = require('../runtime/quint-model.cjs');
const { findJar, translate, runGraph, extend, transition } = require('../runtime/tlc.cjs');

const [revision, input] = process.argv.slice(2);
const config = JSON.parse(input);
const api = quintApi();
const parsed = parseModel(api, snapshot(revision), config);
const bound = bind(parsed, config);
const jar = findJar();
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'quint-consensus-projection-'));
try {
  const model = translate(jar, dir, parsed.module, compilation(api, parsed, bound));
  const choices = bound.leaves.map(leaf => `(${transition(leaf)} /\\ qdSite' = ${leaf.id})`);
  const tla = extend(model.tla, `
VARIABLE qdSite
qdFullInit == q_init /\\ qdSite = 0
qdFullNext == ${choices.join(' \\/ ')}
`);
  const graph = runGraph(jar, dir, parsed.module, { tla, variables: [...model.variables, 'qdSite'].sort() },
    'qdFullInit', 'qdFullNext');
  console.log(JSON.stringify({
    initial: graph.initial,
    states: Object.fromEntries(graph.states),
    outgoing: Object.fromEntries(graph.outgoing),
    sites: Object.fromEntries(bound.leaves.map(({ id, label, site }) => [id, { label, site }])),
  }));
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

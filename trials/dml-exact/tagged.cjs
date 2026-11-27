'use strict';

// Emit the actual classified branches before applying a history filter. Unlike
// the CLI's review search, this graph is too large for its bounded DOT reader.
const fs = require('node:fs');
const path = require('node:path');
const [cliRoot, revision, review, side, dir] = process.argv.slice(2);
const runtime = path.join(cliRoot, 'runtime');
const { snapshot } = require(path.join(runtime, 'git-snapshot.cjs'));
const { quintApi, parseModel, bind, compilation } = require(path.join(runtime, 'quint-model.cjs'));
const { findJar, translate, extend, transition } = require(path.join(runtime, 'tlc.cjs'));

const config = JSON.parse(fs.readFileSync(review, 'utf8'))[side];
const api = quintApi();
const model = parseModel(api, snapshot(revision), config);
const bound = bind(model, config);
fs.mkdirSync(dir);
const { tla } = translate(findJar(), dir, model.module, compilation(api, model, bound));
const choices = bound.leaves.map(leaf => `(${transition(leaf)} /\\ qdSite' = ${leaf.id})`);
fs.writeFileSync(path.join(dir, `${model.module}.tla`), extend(tla, `
VARIABLE qdSite
qdFullInit == q_init /\\ qdSite = 0
qdFullNext == ${choices.join(' \\/ ')}
`));
fs.writeFileSync(path.join(dir, `${model.module}.cfg`), 'INIT qdFullInit\nNEXT qdFullNext\n');
fs.writeFileSync(path.join(dir, 'sites.json'), JSON.stringify(Object.fromEntries(
  bound.leaves.map(({ id, site, label }) => [id, { site, label }])
), null, 2) + '\n');

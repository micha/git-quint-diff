'use strict';

const { spawnSync } = require('node:child_process');
const path = require('node:path').posix;

function git(...args) {
  const proc = spawnSync('git', ['--no-replace-objects', '--literal-pathspecs', ...args], {
    timeout: 10000, maxBuffer: 16 * 1024 * 1024,
    // Read locally available objects only, even in a partial clone. Deny all
    // transports as a second line of defense for Git without the lazy flag.
    env: { ...process.env, GIT_NO_LAZY_FETCH: '1', GIT_ALLOW_PROTOCOL: '' },
  });
  if (proc.error || proc.status !== 0) {
    throw new Error(proc.error?.message ?? (proc.stderr.toString('utf8').trim() || `Git exited ${proc.status ?? proc.signal}`));
  }
  return proc.stdout;
}

function resolve(revision) {
  try {
    const result = git('rev-parse', '--verify', '--end-of-options', `${revision}^{commit}`).toString('ascii').trim();
    if (!/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(result)) throw new Error('expected a commit ID');
    return result;
  } catch (error) {
    throw new Error(`cannot resolve revision ${JSON.stringify(revision)}: ${error.message}`);
  }
}

function relative(base, input) {
  if (!input || input.includes('\0') || input.includes('\\') || path.isAbsolute(input) || /^[a-zA-Z]:/.test(input)) {
    throw new Error(`not a repository-relative source path: ${JSON.stringify(input)}`);
  }
  const result = path.normalize(path.join(base, input));
  if (!result || result === '.' || result === '..' || result.startsWith('../')) {
    throw new Error(`source path leaves the snapshot: ${JSON.stringify(input)}`);
  }
  return result;
}

function snapshot(revision) {
  const sources = new Map();
  const blobs = new Map();
  return {
    sources, blobs,
    load(file) {
      if (sources.has(file)) return sources.get(file);
      try {
        const record = git('ls-tree', '--full-tree', '-z', revision, '--', file).toString('utf8');
        const tab = record.indexOf('\t');
        const oid = /^100(?:644|755) blob ((?:[0-9a-f]{40}|[0-9a-f]{64}))$/.exec(record.slice(0, tab))?.[1];
        if (!oid || record.slice(tab + 1) !== `${file}\0`) throw new Error('not a regular committed blob');
        const content = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(git('cat-file', 'blob', oid));
        sources.set(file, content);
        blobs.set(file, oid);
        return content;
      } catch (error) {
        throw new Error(`${file} at ${revision}: ${error.message}`);
      }
    },
  };
}

module.exports = { resolve, snapshot, relative };

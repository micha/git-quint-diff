const { execFileSync } = require('node:child_process');
const { posix } = require('node:path');

const maxBlobBytes = 8 * 1024 * 1024;

// All paths in the resolver are repository-relative Git paths, not filesystem paths.
function repoPath(stem, name) {
  if (!name || posix.isAbsolute(name) || /[\\\0]/u.test(name) || /^[A-Za-z]:/u.test(name)) {
    throw new Error(`not a relative repository path: ${JSON.stringify(name)}`);
  }
  const path = posix.join(stem, name);
  if (path === '.' || path === '..' || path.startsWith('../')) {
    throw new Error(`path escapes the repository: ${JSON.stringify(name)} from ${JSON.stringify(stem)}`);
  }
  return path;
}

function git(...args) {
  try {
    return execFileSync('git', ['--no-replace-objects', '--literal-pathspecs', ...args], {
      maxBuffer: maxBlobBytes,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (error) {
    const detail = error.stderr?.toString().trim() || error.code || error.message;
    throw new Error(`git ${args[0]}: ${detail}`, { cause: error });
  }
}

function openSnapshot(ref) {
  const revision = git('rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`).toString().trim();
  const cache = new Map();
  return {
    revision,
    read(path) {
      if (cache.has(path)) return cache.get(path);
      const entries = git('ls-tree', '-z', '--full-tree', revision, '--', path).toString();
      const entry = /^(100644|100755) blob ([a-f0-9]+)\t([^\0]*)\0$/u.exec(entries);
      if (!entry || entry[3] !== path) throw new Error(`not a regular file in the snapshot: ${JSON.stringify(path)}`);
      const bytes = git('cat-file', 'blob', entry[2]);
      const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/\r\n?/gu, '\n');
      cache.set(path, text);
      return text;
    },
  };
}

module.exports = { openSnapshot, repoPath };

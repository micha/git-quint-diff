const maxHistories = 10_000;
const maxFrontier = 10_000;

function checkHistoryBudget(actions, maxDepth) {
  let atDepth = 1;
  let count = 1;
  for (let depth = 1; depth <= maxDepth; depth++) {
    atDepth *= actions.length;
    count += atDepth;
    if (count > maxHistories) throw new Error(`requested scope exceeds the ${maxHistories}-history limit`);
  }
}

function orderStates(model, states) {
  return states.map(state => {
    const encoded = model.encodeState(state);
    return { state, encoded, key: JSON.stringify(encoded) };
  }).sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0);
}

function start(model, scenario) {
  const states = orderStates(model, model.initialStates(scenario));
  if (!states.length) throw new Error(`scenario ${JSON.stringify(scenario)} has no initial states`);
  return {
    frontier: states.map(state => ({ state: state.state, path: [state.encoded] })),
    stop: null,
  };
}

function advance(model, replay, label, step) {
  if (replay.stop) return replay;
  if (!model.labels.has(label)) return { frontier: [], stop: { reason: 'missing_action', step } };
  const frontier = new Map();
  for (const { state, path } of replay.frontier) {
    for (const next of orderStates(model, model.successors(state, label))) {
      if (!frontier.has(next.key)) {
        frontier.set(next.key, { state: next.state, path: [...path, next.encoded] });
        if (frontier.size > maxFrontier) throw new Error(`frontier exceeds the ${maxFrontier}-state limit`);
      }
    }
  }
  return {
    frontier: [...frontier.values()],
    stop: frontier.size ? null : { reason: 'disabled_action', step },
  };
}

function outcomes(model, replay) {
  const paths = new Map();
  for (const { state, path } of replay.frontier) {
    const outcome = model.observe(state);
    if (!paths.has(outcome)) paths.set(outcome, path);
  }
  return paths;
}

function onSide(side, history, run) {
  try {
    return run();
  } catch (error) {
    throw new Error(`${side} at history ${JSON.stringify(history)}: ${error.message}`, { cause: error });
  }
}

function* compare(oldModel, newModel, { scenario, actions, maxDepth }) {
  // Queue entries reference the previous history's replay so each prefix is computed once.
  const queue = [{ history: [] }];
  for (let i = 0; i < queue.length; i++) {
    const { history, parent } = queue[i];
    queue[i] = null;
    const replay = (side, model) => onSide(side, history, () => {
      const result = parent
        ? advance(model, parent[side], history.at(-1), history.length)
        : start(model, scenario);
      return { result, paths: outcomes(model, result) };
    });
    const old = replay('old', oldModel);
    const fresh = replay('new', newModel);
    const oldOutcomes = [...old.paths.keys()].sort();
    const newOutcomes = [...fresh.paths.keys()].sort();
    const added = newOutcomes.filter(outcome => !old.paths.has(outcome));
    const removed = oldOutcomes.filter(outcome => !fresh.paths.has(outcome));
    yield {
      history,
      old: { outcomes: oldOutcomes, stop: old.result.stop },
      new: { outcomes: newOutcomes, stop: fresh.result.stop },
      added,
      removed,
      witnesses: [
        ...removed.map(outcome => ({ side: 'old', outcome, states: old.paths.get(outcome) })),
        ...added.map(outcome => ({ side: 'new', outcome, states: fresh.paths.get(outcome) })),
      ],
    };
    if (history.length < maxDepth) {
      const parent = { old: old.result, new: fresh.result };
      for (const action of actions) queue.push({ history: [...history, action], parent });
    }
  }
}

module.exports = { checkHistoryBudget, compare };

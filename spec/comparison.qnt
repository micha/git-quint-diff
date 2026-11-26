module comparison {
  import fixture_models.* from "./fixture_models"

  type Stop = Reached | MissingAction(int) | DisabledAction(int)
  type Replay = { frontier: Set[State], stop: Stop }

  pure def advance(model: Model, replay: Replay, label: str, index: int): Replay =
    if (replay.stop != Reached) replay
    else if (not(label.in(publicActions(model)))) { frontier: Set(), stop: MissingAction(index) }
    else {
      val reached = replay.frontier.map(state => successors(model, state, label)).flatten()
      { frontier: reached, stop: if (reached == Set()) DisabledAction(index) else Reached }
    }

  // TLC enumerates every history over the selected pair's alphabet through this depth.
  pure val maxDepth = 2
  var selected: Comparison
  var history: List[str]
  var oldReplay: Replay
  var newReplay: Replay

  val selection = selectComparison(selected)
  val alphabet = publicActions(selection.oldModel).union(publicActions(selection.newModel))

  action init = {
    nondet chosen = comparisons.oneOf()
    val models = selectComparison(chosen)
    all {
      selected' = chosen,
      history' = List(),
      oldReplay' = { frontier: initialStates(models.oldModel, models.scenario), stop: Reached },
      newReplay' = { frontier: initialStates(models.newModel, models.scenario), stop: Reached },
    }
  }

  action step = if (history.length() < maxDepth) {
    nondet label = alphabet.oneOf()
    val index = history.length() + 1
    all {
      selected' = selected,
      history' = history.append(label),
      oldReplay' = advance(selection.oldModel, oldReplay, label, index),
      newReplay' = advance(selection.newModel, newReplay, label, index),
    }
  } else all {
    // Stutter at the bound so TLC's driver does not report a deadlock.
    selected' = selected,
    history' = history,
    oldReplay' = oldReplay,
    newReplay' = newReplay,
  }

  val oldOutcomes = oldReplay.frontier.map(state => observe(selection.oldModel, state))
  val newOutcomes = newReplay.frontier.map(state => observe(selection.newModel, state))
  val added = newOutcomes.exclude(oldOutcomes)
  val removed = oldOutcomes.exclude(newOutcomes)

  val deltaLaw = all {
    added.intersect(removed) == Set(),
    oldOutcomes.exclude(removed).union(added) == newOutcomes,
    newOutcomes.exclude(added).union(removed) == oldOutcomes,
    (oldReplay.stop == Reached) == (oldOutcomes != Set()),
    (newReplay.stop == Reached) == (newOutcomes != Set()),
  }

  // Literal expected results, independent of the transition and observation functions.
  def matches(expectedOld: (Set[str], Stop), expectedNew: (Set[str], Stop), plus: Set[str], minus: Set[str]): bool = all {
    (oldOutcomes, oldReplay.stop) == expectedOld,
    (newOutcomes, newReplay.stop) == expectedNew,
    added == plus,
    removed == minus,
  }

  val approvalOracle =
    if (history == List())
      matches((Set("denied"), Reached), (Set("denied"), Reached), Set(), Set())
    else if (history == List("obtain_ticket"))
      matches((Set("approved"), Reached), (Set("denied"), Reached), Set("denied"), Set("approved"))
    else if (history == List("obtain_training"))
      matches((Set(), MissingAction(1)), (Set("denied"), Reached), Set("denied"), Set())
    else if (history == List("obtain_ticket", "obtain_ticket"))
      matches((Set(), DisabledAction(2)), (Set(), DisabledAction(2)), Set(), Set())
    else if (history == List("obtain_ticket", "obtain_training"))
      matches((Set(), MissingAction(2)), (Set("approved"), Reached), Set("approved"), Set())
    else if (history == List("obtain_training", "obtain_ticket"))
      matches((Set(), MissingAction(1)), (Set("approved"), Reached), Set("approved"), Set())
    else if (history == List("obtain_training", "obtain_training"))
      matches((Set(), MissingAction(1)), (Set(), DisabledAction(2)), Set(), Set())
    else false

  val reviewOracle =
    if (history == List())
      matches((Set("pending"), Reached), (Set("pending"), Reached), Set(), Set())
    else if (history == List("request_review")) {
      val both = (Set("approved", "denied"), Reached)
      if (selected == ReviewSelf) matches(both, both, Set(), Set())
      else matches(both, (Set("denied"), Reached), Set(), Set("approved"))
    } else if (history == List("request_review", "request_review"))
      matches((Set(), DisabledAction(2)), (Set(), DisabledAction(2)), Set(), Set())
    else false

  val fixtureOracle = match selected {
    | ApprovalChange => approvalOracle
    | ReviewSelf => reviewOracle
    | ReviewRemoval => reviewOracle
  }

  // Negative control: comparing arbitrary paired executions is not sound.
  // This intentionally fails when the self-comparison admits distinct outcomes.
  val naivePairedEquivalence = if (selected == ReviewSelf)
    oldOutcomes.forall(oldChoice => newOutcomes.forall(newChoice => oldChoice == newChoice))
  else true
}

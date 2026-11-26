module review {
  pure val finishesAvailable = true
  pure val publicActions = Set("branch", "finish_left", "finish_right")

  pure def initialStates(scenario: str): Set[str] =
    if (scenario == "start") Set("initial") else Set()

  pure def successors(state: str, label: str): Set[str] =
    if (state == "initial" and label == "branch") Set("left_path", "right_path")
    else if (finishesAvailable and state == "left_path" and label == "finish_left") Set("left_done")
    else if (finishesAvailable and state == "right_path" and label == "finish_right") Set("right_done")
    else Set()

  // Both branch states share this observation but enable different public steps.
  pure def observe(state: str): str =
    if (state.in(Set("left_path", "right_path"))) "pending" else state
}

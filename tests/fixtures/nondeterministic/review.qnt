module review {
  pure val approvalsPossible = true
  pure val publicActions = Set("request_review")

  pure def initialStates(scenario: str): Set[str] =
    if (scenario == "pending_review") Set("pending") else Set()

  pure def successors(state: str, label: str): Set[str] =
    if (state == "pending" and label == "request_review")
      if (approvalsPossible) Set("approved", "denied") else Set("denied")
    else Set()

  pure def observe(state: str): str = state
}

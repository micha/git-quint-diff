module review {
  import policy.* from "./policy"

  type State = { ticket: bool, trained: bool }

  pure val publicActions = if (permitsTraining)
    Set("obtain_ticket", "obtain_training")
  else Set("obtain_ticket")

  pure def initialStates(scenario: str): Set[State] = if (scenario == "new_user")
    Set({ ticket: false, trained: false })
  else Set()

  pure def successors(state: State, label: str): Set[State] =
    if (label == "obtain_ticket" and not(state.ticket))
      Set({ ticket: true, trained: state.trained })
    else if (label == "obtain_training" and permitsTraining and not(state.trained))
      Set({ ticket: state.ticket, trained: true })
    else Set()

  pure def observe(state: State): str =
    if (standardApproval(state.ticket, state.trained)) "approved" else "denied"
}

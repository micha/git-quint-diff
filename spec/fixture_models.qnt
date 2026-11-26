module fixture_models {
  type Model = ApprovalOld | ApprovalNew | ReviewBoth | ReviewDeniedOnly
  type State = Approval({ ticket: bool, trained: bool }) | Review(str)
  type Comparison = ApprovalChange | ReviewSelf | ReviewRemoval
  type Selection = { scenario: str, oldModel: Model, newModel: Model }

  pure val comparisons: Set[Comparison] = Set(ApprovalChange, ReviewSelf, ReviewRemoval)

  pure def selectComparison(comparison: Comparison): Selection = match comparison {
    | ApprovalChange => { scenario: "new_user", oldModel: ApprovalOld, newModel: ApprovalNew }
    | ReviewSelf => { scenario: "pending_review", oldModel: ReviewBoth, newModel: ReviewBoth }
    | ReviewRemoval => { scenario: "pending_review", oldModel: ReviewBoth, newModel: ReviewDeniedOnly }
  }

  pure def initialStates(model: Model, scenario: str): Set[State] = match model {
    | ApprovalOld => if (scenario == "new_user") Set(Approval({ ticket: false, trained: false })) else Set()
    | ApprovalNew => if (scenario == "new_user") Set(Approval({ ticket: false, trained: false })) else Set()
    | ReviewBoth => if (scenario == "pending_review") Set(Review("pending")) else Set()
    | ReviewDeniedOnly => if (scenario == "pending_review") Set(Review("pending")) else Set()
  }

  pure def publicActions(model: Model): Set[str] = match model {
    | ApprovalOld => Set("obtain_ticket")
    | ApprovalNew => Set("obtain_ticket", "obtain_training")
    | ReviewBoth => Set("request_review")
    | ReviewDeniedOnly => Set("request_review")
  }

  pure def successors(model: Model, state: State, name: str): Set[State] = match state {
    | Approval(s) =>
      if (name == "obtain_ticket" and not(s.ticket))
        Set(Approval({ ticket: true, trained: s.trained }))
      else if (name == "obtain_training" and model == ApprovalNew and not(s.trained))
        Set(Approval({ ticket: s.ticket, trained: true }))
      else Set()
    | Review(decision) =>
      if (name == "request_review" and decision == "pending")
        if (model == ReviewBoth) Set(Review("approved"), Review("denied"))
        else Set(Review("denied"))
      else Set()
  }

  pure def observe(model: Model, state: State): str = match state {
    | Approval(s) => if (s.ticket and (model == ApprovalOld or s.trained)) "approved" else "denied"
    | Review(decision) => decision
  }
}

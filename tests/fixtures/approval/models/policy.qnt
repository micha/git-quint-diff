module policy {
  import rule.* from "../shared/rule"

  pure val permitsTraining = trainingAvailable
  pure def standardApproval(ticket: bool, trained: bool): bool = eligible(ticket, trained)
}

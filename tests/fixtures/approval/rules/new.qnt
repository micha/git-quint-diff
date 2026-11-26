module rule {
  pure val trainingAvailable = true
  pure def eligible(ticket: bool, trained: bool): bool = ticket and trained
}

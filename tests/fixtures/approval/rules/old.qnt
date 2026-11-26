module rule {
  pure val trainingAvailable = false
  pure def eligible(ticket: bool, _trained: bool): bool = ticket
}

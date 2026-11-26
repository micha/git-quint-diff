module rule {
  pure val trainingAvailable = true
  pure def eligible(_ticket: bool, _trained: bool): bool = true
}

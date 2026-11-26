module native_oracle {
  // Keep the whole original scheduler; only its constants are instantiated here.
  import KSetAgreementConsensus(N = 3, F = 1, ACTUAL_FAULTS = 1, K = 1, MAX_ROUNDS = 2).* from "./KSetAgreementConsensus"

  val firstReceive = stage == Computing and round == 1
  val secondReceive = stage == Computing and round == 2
  val omissions = Procs.filter(p => procState.get(p).S.contains(Set())).size()

  // Violation witnesses establish presence; the bounds exclude other results.
  val neverDeliveredAll = not(firstReceive and omissions == 0)
  val neverOmittedOne = not(firstReceive and omissions == 1)
  val neverOmittedBoth = not(firstReceive and omissions == 2)
  val neverSecondReceive = not(secondReceive and omissions == 0)
  val crashScope = (firstReceive implies newlyCrashed.size() == 1) and
                   (secondReceive implies newlyCrashed.size() == 0)
  val oldBounds = crashScope and ((firstReceive or secondReceive) implies omissions == 0)
  val newBounds = crashScope and (firstReceive implies (0 <= omissions and omissions <= 2)) and
                                (secondReceive implies omissions == 0)

  // The test helper is declared, but step never calls it. Pair it with the
  // same stage update to compare *all* successor variables, not just omissions.
  action lookalike = all { receiveMessage(Set()), stage' = Computing }
  temporal sameEffect = always(
    ((stage == Receiving and next(stage) == Computing and next(omissions) == 0)
      implies lookalike).orKeep(stage)
  )
  // Intentionally false: a state-pair matcher would falsely attribute this
  // witness to receiveMessage(Set()), although the scheduler calls receiveMessages.
  temporal disjoint = always(
    ((stage == Receiving and next(stage) == Computing)
      implies not(lookalike)).orKeep(stage)
  )
}

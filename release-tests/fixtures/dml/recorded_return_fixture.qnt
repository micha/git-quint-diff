// Small DML-derived return and publish scheduler. See README.md for scope.
module recorded_return_fixture {
  pure val absent = 0
  pure val previousMain = 3
  pure val competingMain = 4
  pure val planned = 11
  pure val alternate = 12
  pure val plannedFactor = 3
  pure val alternateFactor = -2
  pure val noEvent = (0, 0, 0, 0, 0)

  var returning: bool
  var main: int
  var staged: int
  var receipt: int
  // (command, candidate, expected main, expected factor or 0, failure mode)
  var event: (int, int, int, int, int)

  action init = all {
    returning' = false,
    main' = previousMain,
    staged' = absent,
    receipt' = absent,
    event' = noEvent
  }

  action startReturn = all {
    returning' = true,
    main' = main, staged' = staged, receipt' = receipt, event' = event
  }

  action clearEvent = all {
    event' = noEvent,
    receipt' = absent,
    returning' = returning, main' = main, staged' = staged
  }

  action stage(root: int): bool = {
    val open = staged == absent
    all {
      staged' = if (open) root else staged,
      receipt' = if (open) root else absent,
      event' = (1, root, 0, 0, 0),
      returning' = returning, main' = main
    }
  }

  action publish(root: int, expectedMain: int, aliasesMain: bool, failAt: int): bool = {
    val validated = not(aliasesMain)
    val committed = validated and main == expectedMain and staged == root and failAt == 0
    all {
      main' = if (committed) root else main,
      staged' = if (committed) absent else staged,
      receipt' = if (committed) root else absent,
      event' = (2, root, expectedMain, 0, if (aliasesMain) 3 else failAt),
      returning' = returning
    }
  }

  action step = if (not(returning)) startReturn
    else if (event != noEvent) clearEvent
    else any {
      nondet root = Set(planned, alternate).oneOf()
      stage(root),
      nondet root = Set(planned, alternate).oneOf()
      nondet expectedMain = Set(absent, previousMain, planned).oneOf()
      nondet mode = Set(0, 1, 2, 3).oneOf()
      publish(root, expectedMain, mode == 3, if (mode == 3) 0 else mode),
      nondet target = Set(absent, previousMain, competingMain).oneOf()
      all { main' = target, returning' = returning, staged' = staged, receipt' = receipt, event' = event }
    }
}

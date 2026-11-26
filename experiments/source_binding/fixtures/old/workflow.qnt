module workflow {
  import marks.* from "./marks"

  action init = x' = 0
  action step = any {
    all {
      x == 0,
      nondet v = Set(1, 2).oneOf()
      x' = v,
    },
    // Public intake
    all { x.in(Set(1, 2)), mark(3) },
    // Public recovery
    all { x.in(Set(1, 2)), mark(3) },
    all { x.in(Set(3, 4)), x' = 0 },
  }
}

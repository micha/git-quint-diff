module workflow {
  import marks.* from "./marks"

  action init = x' = 0

  action dispatch = any {
    all {
      x == 0,
      nondet v = Set(1, 2).oneOf()
      x' = v,
    },
    // Public recovery moved ahead of intake
    all {
      x.in(Set(1, 2)),
      record(3),
    },
    // Public intake
    all { x.in(Set(1, 2)), record(3) },
    all { x.in(Set(3, 4)), x' = 0 },
  }
}

# Finite DML-derived publication fixture

This is a small, first-party model based on the return/publication scenario in
[DML `819ac9d`](https://github.com/micha/dml/blob/819ac9d9c496bf652ea85af12b3369844df2b1e4/tests/recorded_return_design.qnt)
and its factor check in
[`c540078`](https://github.com/micha/dml/blob/c540078318bf52313a33d856c7825d6b09566b17/tests/recorded_return_design.qnt).
It is **not** a reconstruction of those commits. Quint 0.33.1 does not parse
their `observation` declarations, and their full native state graphs are too
large for this routine regression.

The fixture models handoff, staging, publication, report clearing, and a
competing write to main. It keeps the `any`/`if` routing and the locally
chosen stage and publish operands, including the alias/failure expressions.
It omits worker/producer object graphs, selection, export, collection,
invariants, and other competing operations. Candidates `11` and `12` stand
for well-formed objects; a matching staging ref suffices to model their
availability. Failure after tentative writes is modeled by an unchanged
committed ref state, not separate transaction steps. The report tuple exposes
request arguments to the **independent** graph oracle; the review classifies
by binding the scheduled call, not by reading the report. The observation
is the receipt (`12` for successful alternate publication, `0` for denial).

[`test_dml.py`](../../test_dml.py) constructs a fresh Git repository with
these exact local commits:

| Side | Commit | Model blob |
| --- | --- | --- |
| OLD | `d3525cc2f98964fa0a04949fb6736b3da03610f5` | `5760ebf8c5845cf4cde50d41bbb5203200823443` |
| NEW | `fab07489fc91c6b447b6bd7d2b5bbd5541cae5b3` | `22861dd5426d24552a7ba807ae762113b72f04a2` |

OLD is [`recorded_return_fixture.qnt`](recorded_return_fixture.qnt). NEW
applies [`check-requested-factor.diff`](check-requested-factor.diff) at
commit creation, not at review or oracle time. Each selected review stages
candidate `12`, then asks to publish candidate `12` against main `3` in
ordinary mode (`aliasesMain=false`, `failAt=0`). The OLD request has no
factor. The two separate reviews select either a mismatched factor `3` or
the matching factor `−2` on NEW. Only start handoff, clear report, and move
main are allowed as hidden steps; no other stage/publish argument tuple can
serve as hidden progress. Measure immediately after stage or publication.

| History | OLD | NEW | Difference |
| --- | --- | --- | --- |
| Stage only | `{12}` | `{12}` | None |
| Stage then publish, factor `3` | `{0,12}` | `{0}` | `− 12` |
| Stage then publish, factor `−2` | `{0,12}` | `{0,12}` | None |

OLD's success needs four original transitions. Its competing-main denial
needs five. NEW can deny the factor-`3` request in four transitions with
main still at `3`; factor `−2` retains both paths. These checks support this
finite fixture and these histories, not the original DML model or its
implementation.

## Routed derivative

A second disposable repository uses the same model and review histories,
but takes the ready branch through a named action. OLD applies
[`route-scheduler.diff`](route-scheduler.diff) to the base fixture. NEW
applies the factor check and [`add-ready-router.diff`](add-ready-router.diff).
Handoff and report clearing stay in `step`; it calls `sourceStep` in OLD
and `readyStep → sourceStep` in NEW. The routed copies are separate committed
snapshots, not rewrites applied by the reviewer.

| Side | Commit | Model blob | Explicit `routing` |
| --- | --- | --- | --- |
| OLD | `2e2a3ec087c0cf05e8d29129a1330909778e7223` | `762100a594848f945368fb3503e8e1815c8b9085` | `recorded_return_fixture::sourceStep` |
| NEW | `125ee395267dd1c618aeb27487d9a98831de1026` | `08eec339a37d48f63a75248eb7b9e855cc8d019a` | `recorded_return_fixture::readyStep`, `recorded_return_fixture::sourceStep` |

The predicted outcome sets and witness lengths are unchanged. The oracle
compiles the original `step`, checks every reachable tracked state's
outgoing states after removing its tag, and independently checks labels and
ordered routing hops in witnesses. Discovery supplies copyable selectors with
`via` positions. Omitting `readyStep` or `sourceStep` from the authorization
needed on NEW leaves the unlisted action opaque; using OLD's single-hop
selector path on NEW fails binding rather than reporting an empty outcome.

Run the direct and routed checks in the development shell:

```sh
nix develop --command python3 -B -m unittest discover -s release-tests -p test_dml.py -v
```

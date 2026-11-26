"""Check the independent consensus projection and full-state witness replay."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from projection_oracle import (
    COMPUTING, RECEIVING, Graph, NativeState, TaggedState, UNIT, Record,
    check_projection, check_revision, read_value,
)


class ProjectionUnitTests(unittest.TestCase):
    def test_nested_tlc_values_keep_record_set_and_sequence_types(self):
        self.assertEqual(read_value('{[sender |-> 1, values |-> {1, 2}]}'),
                         read_value('{[values |-> {2, 1}, sender |-> 1]}'))
        self.assertNotEqual(read_value('{1, 2}'), read_value('<< 1, 2 >>'))
        self.assertNotEqual(read_value('<< 1, 2 >>'), read_value('<< 2, 1 >>'))
        with self.assertRaisesRegex(ValueError, 'duplicate TLC record'):
            read_value('[sender |-> 1, sender |-> 2]')
        with self.assertRaisesRegex(ValueError, 'unsupported TLC value syntax'):
            read_value('{1..3}')
        with self.assertRaisesRegex(ValueError, 'duplicate TLC set element'):
            read_value('{1, 1}')

    def test_checks_each_tagged_state_not_just_the_projected_edge_union(self):
        start = NativeState(1, Record((("Starting", UNIT),)), *([frozenset()] * 4), ())
        receive = start._replace(stage=RECEIVING)
        compute = start._replace(stage=COMPUTING)
        native = Graph({start}, {start: {receive}, receive: {compute}, compute: set()}, {})
        tagged_start = TaggedState(start, 0)
        choice_preserved = TaggedState(receive, 0)
        choice_lost = TaggedState(receive, 1)
        tagged_end = TaggedState(compute, 1)
        tagged = Graph({tagged_start}, {tagged_start: {choice_preserved, choice_lost},
                                       choice_preserved: {tagged_end}, choice_lost: set(), tagged_end: set()}, {})
        projected = {(s.native, t.native) for s, targets in tagged.outgoing.items() for t in targets}
        self.assertEqual(projected, {(start, receive), (receive, compute)})
        with self.assertRaisesRegex(ValueError, 'tag erasure changed outgoing native transitions'):
            check_projection(native, tagged)


@unittest.skipUnless(os.environ.get("QUINT_HOME") and os.environ.get("CONSENSUS_CHECKOUT"),
                     "run in nix develop with CONSENSUS_CHECKOUT set to upstream Quint")
class ProjectionLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = tempfile.TemporaryDirectory(prefix="quint-consensus-projection-test-")
        cls.addClassCleanup(scratch.cleanup)
        cls.root = Path(scratch.name)
        cls.upstream = Path(os.environ["CONSENSUS_CHECKOUT"]).resolve()
        command = [sys.executable, "-B", str(Path(__file__).with_name("source_actions.py"))]
        cls.self_report = json.loads(subprocess.check_output([
            *command, "compare", str(cls.upstream), "--json", "--self",
        ], timeout=120))
        cls.report = json.loads(subprocess.check_output([
            *command, "compare", str(cls.upstream), "--json",
        ], timeout=120))
        for case in ("old", "new"):
            subprocess.run([*command, "stage", str(cls.upstream), case, str(cls.root / case)],
                           check=True, stdout=subprocess.DEVNULL, timeout=120)

    def test_closes_full_native_and_tagged_graphs_and_replays_both_reports(self):
        old = {"generated": 171, "distinct": 153, "edges": 162}
        new = {"generated": 339, "distinct": 267, "edges": 330}
        for case, report, stats, count in (("old", self.self_report, old, 4),
                                           ("old", self.report, old, 2), ("new", self.report, new, 4)):
            with self.subTest(case=case, witnesses=count):
                result = check_revision(self.upstream, case, self.root / case, report)
                self.assertEqual(result["native"], {**stats, "initial": 9, "depth": 9, "queued": 0})
                self.assertEqual(result["tagged"], result["native"])
                self.assertEqual(result["replayed_witnesses"], count)

    def test_projection_rejects_hidden_receive_even_with_same_native_effect(self):
        stage = self.root / "wrong-tag"
        shutil.copytree(self.root / "old", stage)
        imported = stage / "ConsensusAlg.qnt"
        text = imported.read_text(encoding="utf-8")
        tag = "reviewReceiveRound' = round"
        self.assertEqual(text.count(tag), 1)
        imported.write_text(text.replace(tag, "reviewReceiveRound' = 0"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, 'incorrect receive tag'):
            check_revision(self.upstream, "old", stage)

    def test_replay_rejects_a_reachable_witness_frame_that_is_not_the_next_state(self):
        report = deepcopy(self.report)
        trace = report["histories"][0]["outcomes"]["old"][0]["trace"]
        (slot0,) = [v[0] for k, v in trace[1]["state"].items() if k.endswith("_procState")]
        # A different proposal is also legitimate in a different execution,
        # but the crash step cannot change the proposal fixed by this init.
        slot0["x"] = slot0["x"] % 3 + 1
        slot0["V"] = [slot0["x"]]
        with self.assertRaisesRegex(ValueError, 'does not replay through the original scheduler at frame 1'):
            check_revision(self.upstream, "old", self.root / "old", report)


if __name__ == "__main__":
    unittest.main()

"""Check DML's unfiltered projection and native witness replay."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from source_projection_oracle import (
    EDGE, HEADER, LABELS, MODEL, REVISIONS, Event, Graph, Native, Source, Tagged, Worker,
    check_projection, check_report, check_revision, dot_state, native_outcomes, read_graph, replay,
)

RAW = ('/\\ returning = FALSE\n'
       '/\\ source = [main |-> 3, returned |-> 0, producerPin |-> 1, objects |-> {101, 3, 1}]\n'
       '/\\ worker = [pin |-> 11, objects |-> {11}, selected |-> 0, bundle |-> 0]\n'
       '/\\ event = [command |-> "", wanted |-> 0, receipt |-> 0, oldBundle |-> 0, '
       'before |-> [main |-> 3, returned |-> 0, producerPin |-> 1, objects |-> {1, 3, 101}], '
       'expectedMain |-> 0, aliasesMain |-> FALSE, failAt |-> 0]')


def graph(states, outgoing):
    return Graph(states, {s: i for i, s in enumerate(states)}, {0}, outgoing, {})


def native_fixture():
    source = Source(3, 0, 1, frozenset({1, 3, 101}))
    no_event = Event("", 0, 0, 0, source, 0, None, False, 0)
    start = Native(False, Worker(11, frozenset({11}), 0, 0), source, no_event)
    stage = start._replace(returning=True, source=source._replace(returned=12),
                           event=no_event._replace(command="stage", wanted=12, receipt=12))
    reset = stage._replace(event=no_event)
    publish = reset._replace(source=source._replace(main=12),
                             event=no_event._replace(command="publish", wanted=12, receipt=12, expectedMain=3))
    # The same report can be reachable with a different worker on another path.
    rogue = publish._replace(worker=start.worker._replace(bundle=11))
    blocked = reset._replace(worker=start.worker._replace(bundle=11),
                             event=no_event._replace(command="collect"))
    return graph([start, stage, reset, publish, rogue, blocked], [(1, 5), (2,), (3,), (), (), (4,)])


def frame(native, tag, phase, action):
    def thaw(value):
        if isinstance(value, frozenset):
            return sorted(value)
        if isinstance(value, tuple):
            return {k: thaw(v) for k, v in value._asdict().items() if v is not None}
        return value

    return {"action": action, "state": {**thaw(native), "reviewCall": tag, "reviewPhase": phase}}


class SourceProjectionUnitTests(unittest.TestCase):
    def test_dot_state_schema_and_typed_set_values(self):
        self.assertEqual(dot_state(json.dumps(RAW), tagged=False, old=True), native_fixture().states[0])
        self.assertEqual(dot_state(json.dumps(RAW + '\n/\\ reviewCall = 0'), tagged=True, old=True),
                         Tagged(native_fixture().states[0], 0))
        with self.assertRaisesRegex(ValueError, 'duplicate set members'):
            dot_state(json.dumps(RAW.replace('{11}', '{11, 11}')), tagged=False, old=True)
        with self.assertRaisesRegex(ValueError, 'expected bool'):
            dot_state(json.dumps(RAW.replace('aliasesMain |-> FALSE', 'aliasesMain |-> 0')), tagged=False, old=True)
        with self.assertRaisesRegex(ValueError, 'unexpected Event fields'):
            dot_state(json.dumps(RAW), tagged=False, old=False)

    def test_dot_reader_accounts_for_every_generated_edge_including_self_loops(self):
        text = '\n'.join((*HEADER, f'11 [label={json.dumps(RAW)},style = filled]',
                          f'11 -> 11 {EDGE}', f'11 -> 11 {EDGE}', '{rank = same; 11;}', '}', '}'))
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / 'graph.dot'
            path.write_text(text, encoding='utf-8')
            result = read_graph(path, {'generated': 3, 'distinct': 1}, tagged=False, old=True)
            self.assertEqual(result.outgoing, [(0,)])  # count both, compare one unique edge
            with self.assertRaisesRegex(ValueError, 'does not account for the complete search'):
                read_graph(path, {'generated': 4, 'distinct': 1}, tagged=False, old=True)
            path.write_text(text.replace(f'11 -> 11 {EDGE}', f'12 -> 11 {EDGE}', 1), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'references an unknown node'):
                read_graph(path, {'generated': 3, 'distinct': 1}, tagged=False, old=True)

    def test_projection_checks_each_tagged_sources_successors_not_their_union(self):
        first, choice, end = native_fixture().states[:3]
        native = graph([first, choice, end], [(1,), (2,), ()])
        tagged = graph([Tagged(first, 0), Tagged(choice, 1), Tagged(choice, 4), Tagged(end, 0)],
                       [(1, 2), (3,), (), ()])
        projected = {(tagged.states[s].native, tagged.states[t].native)
                     for s, targets in enumerate(tagged.outgoing) for t in targets}
        self.assertEqual(projected, {(first, choice), (choice, end)})
        with self.assertRaisesRegex(ValueError, 'tag erasure changed outgoing native transitions'):
            check_projection(native, tagged)

    def test_erasure_alone_cannot_detect_a_misclassified_call(self):
        native = native_fixture()
        tags = [0, 1, 0, 5, 5, 4]
        tagged = graph([Tagged(state, tag) for state, tag in zip(native.states, tags, strict=True)], native.outgoing)
        check_projection(native, tagged)
        tags[3] = 2  # wrongly treated the legacy call as only one of the two labels
        wrong = graph([Tagged(state, tag) for state, tag in zip(native.states, tags, strict=True)], native.outgoing)
        with self.assertRaisesRegex(ValueError, 'incorrect call tag'):
            check_projection(native, wrong)

    def test_native_replay_requires_every_full_edge_not_just_a_reachable_receipt(self):
        native = native_fixture()
        first, stage, reset, publish, rogue = native.states[:5]
        self.assertEqual(native_outcomes(native), {2: {12: 3}, 3: {12: 3}})
        for factor in (2, 3):
            with self.subTest(factor=factor):
                row = {'receipt': 12, 'trace': [frame(first, 0, 0, 'init'), frame(stage, 1, 1, LABELS[1]),
                                                frame(reset, 0, 1, 'hidden'), frame(publish, 5, factor, LABELS[factor])]}
                replay(native, row, factor, 3, old=True)
                wrong = deepcopy(row)
                wrong['trace'][-1]['state']['worker']['bundle'] = rogue.worker.bundle
                with self.assertRaisesRegex(ValueError, 'does not replay through the original scheduler at frame 3'):
                    replay(native, wrong, factor, 3, old=True)

    def test_rejects_a_report_for_a_different_observation(self):
        report = {'schema_version': 1, 'model': MODEL, 'status': 'exhaustive', 'revisions': REVISIONS,
                  'scope': {'scenario': 'initial_source (original init)', 'observation': 'source.main',
                            'max_original_transitions': None,
                            'public_histories': [[LABELS[1], LABELS[p]] for p in (2, 3)]}}
        with self.assertRaisesRegex(ValueError, 'expected an exhaustive report'):
            check_report(report, 'old', native_fixture(), {})


@unittest.skipUnless(os.environ.get('QUINT_HOME') and os.environ.get('DML_CHECKOUT')
                     and os.environ.get('DML_QUINT') and os.environ.get('DML_FULL_PROJECTION') == '1',
                     'set DML_FULL_PROJECTION=1, DML_CHECKOUT and DML_QUINT inside nix develop')
class SourceProjectionLiveTests(unittest.TestCase):
    def test_closes_full_native_and_tagged_graphs_and_replays_both_reports(self):
        checkout = Path(os.environ['DML_CHECKOUT']).resolve()
        quint = Path(os.environ['DML_QUINT']).absolute()
        driver = [sys.executable, '-B', str(Path(__file__).with_name('argument_bindings.py'))]
        compare = [*driver, 'compare', str(checkout), str(quint), '--json']
        self_report = json.loads(subprocess.check_output([*compare, '--self'], timeout=240))
        change = json.loads(subprocess.check_output(compare, timeout=240))
        with tempfile.TemporaryDirectory(prefix='dml-source-oracle-live-') as scratch:
            for case, reports, witnesses, counts in (
                ('old', (self_report, change), 12, (1269121, 611528)),
                ('new', (change,), 3, (2367361, 1160648)),
            ):
                with self.subTest(case=case):
                    tagged = Path(scratch) / case
                    subprocess.run([*driver, 'stage', str(checkout), str(quint), case, str(tagged)],
                                   check=True, stdout=subprocess.DEVNULL, timeout=120)
                    result = check_revision(checkout, quint, case, tagged, reports)
                    native_stats, tagged_stats = result['native'], result['tagged']
                    for stats in (native_stats, tagged_stats):
                        self.assertEqual((stats['generated'], stats['distinct']), counts)
                        self.assertEqual((stats['initial'], stats['queued'], stats['depth']), (1, 0, 28))
                    self.assertEqual(native_stats['edges'], tagged_stats['edges'])
                    self.assertEqual(result['replayed_witnesses'], witnesses)


if __name__ == '__main__':
    unittest.main()

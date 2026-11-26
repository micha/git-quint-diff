"""Test the constrained action binding and replay it against exact Quint commits."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import action_identity as checker


class BindingTests(unittest.TestCase):
    def test_only_annotates_the_scheduler_call_site(self):
        prefix = checker.PREFIX
        body = ''.join(f'    {prefix}{call}\n' for call in checker.CALLS)
        source = (f'{prefix}step ==\n{body}\nq_step == {prefix}step\n\n'
                  f'OtherContext ==\n    {prefix}receiveMessages\n====\n')
        monitored = checker.monitor(source, None)
        self.assertIn(source.removesuffix('====\n'), monitored)
        self.assertEqual(monitored.count('reviewAction\' = "receiveMessages"'), 2)  # bind, then read
        self.assertIn(f'    ({prefix}receiveMessages /\\ reviewAction\' = "receiveMessages")', monitored)

    def test_same_effect_is_not_fallback_for_missing_or_ambiguous_binding(self):
        prefix = checker.PREFIX
        for lookalike in ('receiveMessage', 'receiveMessages\n    ' + prefix + 'receiveMessages'):
            with self.subTest(lookalike=lookalike):
                calls = [lookalike if call == checker.PUBLIC else call for call in checker.CALLS]
                body = ''.join(f'    {prefix}{call}\n' for call in calls)
                source = f'{prefix}step ==\n{body}\nq_step == {prefix}step\n====\n'
                with self.assertRaisesRegex(checker.Incomplete, 'one scheduler call site for receiveMessages'):
                    checker.monitor(source, None)


@unittest.skipUnless(os.environ.get('CONSENSUS_CHECKOUT') and os.environ.get('CONSENSUS_QUINT'),
                     'set CONSENSUS_CHECKOUT and CONSENSUS_QUINT (0.34.0) for live Quint/TLC')
class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(os.environ['CONSENSUS_CHECKOUT']).resolve()
        self.quint = Path(os.environ['CONSENSUS_QUINT']).absolute()

    def cli(self, *flags, repo=None, quint=None, code=0):
        proc = subprocess.run([
            sys.executable, '-B', str(Path(checker.__file__).resolve()),
            str(repo or self.repo), str(quint or self.quint), '--json', *flags,
        ], capture_output=True, timeout=240)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def outcomes(self, report):
        return [([r['omissions'] for r in h['outcomes']['old']], [r['omissions'] for r in h['outcomes']['new']])
                for h in report['histories']]

    def test_self_then_compare_and_repeat_with_broken_imports_in_working_tree(self):
        same = self.cli('--self')
        self.assertEqual(self.outcomes(same), [([0], [0])] * 2)
        self.assertTrue(all(not h['added'] and not h['removed'] for h in same['histories']))
        diff = self.cli()
        self.assertEqual(diff['revisions'], checker.REVISIONS)
        self.assertEqual(self.outcomes(diff), [([0], [0, 1, 2]), ([0], [0])])
        self.assertEqual([(h['removed'], h['added']) for h in diff['histories']], [([], [1, 2]), ([], [])])
        for report in (same, diff):
            self.assertEqual(report['status'], 'exhaustive')
            self.assertIsNone(report['scope']['max_original_transitions'])
            self.assertEqual(list(report['closure']), ['old', 'new'])
            for side, stats in report['closure'].items():
                count = sum(len(h['outcomes'][side]) for h in report['histories'])
                self.assertEqual(stats['queued'], 0)
                self.assertEqual(stats['rounds'], count + 1)
        self.assertNotEqual(diff['blobs']['old'], diff['blobs']['new'])
        for h in diff['histories']:
            for rows in h['outcomes'].values():
                for row in rows:
                    trace = row['trace']
                    self.assertEqual([f['public_label'] for f in trace if f['public_label']], h['public_history'])
                    self.assertEqual([f['call'] for f in trace][:4], ['init', 'crash', 'sendMessages', 'receiveMessages'])
                    self.assertEqual(trace[-1]['call'], 'receiveMessages')
                    self.assertEqual(len(trace) - 1, 3 if len(h['public_history']) == 1 else 7)
                    self.assertNotIn('receiveMessage', [f['call'] for f in trace])
                    state = trace[-1]['state']
                    self.assertEqual(sum([] in p['S'] for p in state[checker.PREFIX + 'procState']), row['omissions'])

        with tempfile.TemporaryDirectory() as scratch:
            clone = Path(scratch) / 'quint'
            subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(self.repo), str(clone)],
                           check=True, timeout=30)
            model_dir = clone / checker.MODEL_DIR
            model_dir.mkdir(parents=True)
            for name in checker.FILES:
                (model_dir / name).write_text('not valid Quint\n', encoding='utf-8')
            self.assertEqual(self.cli(repo=clone), diff)  # Includes exact blob ids and witness ordering.
            for name in checker.FILES:
                self.assertEqual((model_dir / name).read_text(encoding='utf-8'), 'not valid Quint\n')

    def test_bound_counts_original_steps_not_init_or_labels(self):
        empty, prefix = [self.cli('--max-transitions', str(bound)) for bound in (2, 3)]
        for report, bound in ((empty, 2), (prefix, 3)):
            self.assertEqual(report['status'], 'bounded')
            self.assertEqual(report['scope']['max_original_transitions'], bound)
        self.assertEqual(self.outcomes(empty), [([], [])] * 2)
        self.assertEqual(self.outcomes(prefix), [([0], [0, 1, 2]), ([], [])])

    def test_unavailable_backend_and_missing_snapshot_are_incomplete(self):
        with tempfile.TemporaryDirectory() as scratch:
            missing = Path(scratch) / 'missing'
            cases = (self.cli(quint=missing, code=1), self.cli(repo=missing, code=1))
        for report in cases:
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(report['histories'], [])
            self.assertEqual(report['closure'], {})
            self.assertIn('missing', report['error'])


if __name__ == '__main__':
    unittest.main()

import unittest
from probe_capabilities import CAPABILITIES, classify

class CapabilityCensusTests(unittest.TestCase):
    def test_frozen_positive_and_negative_controls(self):
        def fixture(args):
            if args == ["gh", "--version"]:
                return 0, "gh version 1.2.3"
            if args == CAPABILITIES["native_issue_artifacts"][0]:
                return 1, "unsupported"
            if args == CAPABILITIES["native_pr_worktree"][0]:
                return 0, "usage: checkout --worktree PATH"
            if args == CAPABILITIES["native_issue_worktree"][0]:
                return 0, "usage: develop without matching option"
            return 0, "help"
        observed = classify(fixture)
        self.assertEqual(observed["gh_version"], "gh version 1.2.3")
        self.assertFalse(observed["mutation_performed"])
        self.assertEqual(observed["capabilities"]["native_issue_artifacts"], "UNAVAILABLE_OR_UNKNOWN")
        self.assertEqual(observed["capabilities"]["native_pr_worktree"], "HELP_EXPOSED")
        self.assertEqual(observed["capabilities"]["native_issue_worktree"], "UNAVAILABLE_OR_UNKNOWN")
        self.assertEqual(observed["basis"], "local_help_only_not_end_to_end_qualification")

if __name__ == "__main__":
    unittest.main()

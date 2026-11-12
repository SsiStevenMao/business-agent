import unittest

from business_agent.cli import build_parser


class CliTests(unittest.TestCase):
    def test_show_reasoning_flag_is_disabled_by_default(self) -> None:
        args = build_parser().parse_args([])
        self.assertFalse(args.show_reasoning)

    def test_show_reasoning_flag_can_be_enabled(self) -> None:
        args = build_parser().parse_args(["--show-reasoning"])
        self.assertTrue(args.show_reasoning)


if __name__ == "__main__":
    unittest.main()

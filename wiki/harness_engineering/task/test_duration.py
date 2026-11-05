# тесты задачи, unittest из stdlib Python 3.12, проверено на стенде 2026-11-05; агенту их менять нельзя
import unittest

from duration import parse_duration


class ParseDurationTest(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(parse_duration("45s"), 45)

    def test_minutes(self):
        self.assertEqual(parse_duration("2m"), 120)

    def test_days(self):
        self.assertEqual(parse_duration("1d"), 86400)

    def test_combined(self):
        self.assertEqual(parse_duration("1h30m"), 5400)

    def test_spaces(self):
        self.assertEqual(parse_duration("1h 30m 15s"), 5415)

    def test_case_insensitive(self):
        self.assertEqual(parse_duration("1H"), 3600)

    def test_fraction(self):
        self.assertEqual(parse_duration("1.5h"), 5400)

    def test_fraction_floor(self):
        self.assertEqual(parse_duration("2.75s"), 2)

    def test_empty(self):
        with self.assertRaises(ValueError):
            parse_duration("")

    def test_number_without_unit(self):
        with self.assertRaises(ValueError):
            parse_duration("10")

    def test_unknown_unit(self):
        with self.assertRaises(ValueError):
            parse_duration("10x")

    def test_wrong_order(self):
        with self.assertRaises(ValueError):
            parse_duration("30m1h")

    def test_repeated_unit(self):
        with self.assertRaises(ValueError):
            parse_duration("1h1h")


if __name__ == "__main__":
    unittest.main()

import unittest
from worksapp.arabic_money import amount_in_words, number_words
from worksapp.money import D, q2, q3


class ArabicMoney(unittest.TestCase):
    def test_number_words_common_values(self):
        self.assertEqual(number_words(0), "صفر")
        self.assertEqual(number_words(21), "واحد وعشرون")
        self.assertEqual(number_words(3000), "ثلاثة آلاف")
        self.assertEqual(number_words(100000), "مائة ألف")

    def test_amount_with_dinars_and_centimes(self):
        self.assertEqual(amount_in_words("1.25"), "فقط دينار جزائري واحد وخمسة وعشرون سنتيمًا لا غير")
        self.assertEqual(amount_in_words("25000.50"), "فقط خمسة وعشرون ألف دينار جزائري وخمسون سنتيمًا لا غير")
        self.assertIn("تسعة ملايين", amount_in_words("9333403.84"))
        self.assertIn("أربعة وثمانون سنتيمًا", amount_in_words("9333403.84"))

    def test_none_and_negative_amount(self):
        self.assertEqual(amount_in_words(None), "")
        self.assertTrue(amount_in_words("-5.10").startswith("سالب فقط"))

    def test_decimal_parser_rejects_non_finite_and_out_of_range(self):
        for bad in ("NaN", "Infinity", "-Infinity", "1e100", "1e-100"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                D(bad)
        self.assertEqual(q2(D("١٢٣٫٤٥")), D("123.45"))
        self.assertEqual(q3(D("2.5")), D("2.500"))


if __name__ == "__main__":
    unittest.main()

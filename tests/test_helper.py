import unittest

from src.helper import strip_trailing_affect


class TrailingAffectTests(unittest.TestCase):
    def test_removes_complete_final_affect_line(self):
        response = '(write-file "ulc.py" "print(lambda x: x)")\n⋄⟨Cn:.8 C:.7⟩'
        self.assertEqual(
            strip_trailing_affect(response),
            '(write-file "ulc.py" "print(lambda x: x)")\n',
        )

    def test_preserves_diamond_inside_command_string(self):
        response = '(write-file "note.txt" "diamond ⋄ stays")'
        self.assertEqual(strip_trailing_affect(response), response)

    def test_preserves_incomplete_affect_line(self):
        response = '(do-work)\n⋄⟨Cn:.8'
        self.assertEqual(strip_trailing_affect(response), response)

    def test_preserves_nonfinal_affect_like_line(self):
        response = '⋄⟨Cn:.8⟩\n(do-work)'
        self.assertEqual(strip_trailing_affect(response), response)


if __name__ == "__main__":
    unittest.main()

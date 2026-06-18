import os
import unittest

from special_days import config


class LoadDotenvTest(unittest.TestCase):
    def setUp(self):
        self.key = "SPECIAL_DAYS_TEST_KEY"
        os.environ.pop(self.key, None)
        self.addCleanup(lambda: os.environ.pop(self.key, None))

    def _write(self, tmp_path, text):
        path = os.path.join(tmp_path, ".env")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_loads_plain_key(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, f'{self.key}="abc123"\n')
            config.load_dotenv(path)
        self.assertEqual(os.environ[self.key], "abc123")

    def test_tolerates_export_prefix(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, f"export {self.key}=abc123\n")
            config.load_dotenv(path)
        self.assertEqual(os.environ[self.key], "abc123")

    def test_missing_file_is_noop(self):
        config.load_dotenv("/no/such/.env")  # must not raise


if __name__ == "__main__":
    unittest.main()

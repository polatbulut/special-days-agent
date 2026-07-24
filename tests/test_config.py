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

    def test_strips_inline_comment(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, f"{self.key}=value123   # a comment\n")
            config.load_dotenv(path)
        self.assertEqual(os.environ[self.key], "value123")

    def test_comment_only_value_is_empty(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, f"{self.key}=    # http://localhost:8000/v1\n")
            config.load_dotenv(path)
        self.assertEqual(os.environ.get(self.key), "")

    def test_hash_inside_quoted_value_kept(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, f'{self.key}="a#b"\n')
            config.load_dotenv(path)
        self.assertEqual(os.environ[self.key], "a#b")

    def test_missing_file_is_noop(self):
        config.load_dotenv("/no/such/.env")  # must not raise


class FootballKeyTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(config.FOOTBALL_API_KEY_ENV)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop(config.FOOTBALL_API_KEY_ENV, None)
        else:
            os.environ[config.FOOTBALL_API_KEY_ENV] = self._saved

    def test_returns_stripped_key_when_set(self):
        os.environ[config.FOOTBALL_API_KEY_ENV] = "  abc123  "
        self.assertEqual(config.get_football_api_key(), "abc123")

    def test_returns_none_when_unset(self):
        os.environ.pop(config.FOOTBALL_API_KEY_ENV, None)
        self.assertIsNone(config.get_football_api_key())


class ObsSecretKeyTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(config.OBS_SECRET_KEY_ENV)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop(config.OBS_SECRET_KEY_ENV, None)
        else:
            os.environ[config.OBS_SECRET_KEY_ENV] = self._saved

    def test_returns_stripped_secret_when_set(self):
        os.environ[config.OBS_SECRET_KEY_ENV] = "  secret123\n"
        self.assertEqual(config.get_obs_secret_key(), "secret123")

    def test_returns_none_when_unset(self):
        os.environ.pop(config.OBS_SECRET_KEY_ENV, None)
        self.assertIsNone(config.get_obs_secret_key())


class ObsEndpointStyleTest(unittest.TestCase):
    def setUp(self):
        self._saved_path_style = os.environ.get(config.OBS_PATH_STYLE_ENV)
        self._saved_is_cname = os.environ.get(config.OBS_IS_CNAME_ENV)
        self._saved_verify_ssl = os.environ.get(config.OBS_VERIFY_SSL_ENV)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved_path_style is None:
            os.environ.pop(config.OBS_PATH_STYLE_ENV, None)
        else:
            os.environ[config.OBS_PATH_STYLE_ENV] = self._saved_path_style
        if self._saved_is_cname is None:
            os.environ.pop(config.OBS_IS_CNAME_ENV, None)
        else:
            os.environ[config.OBS_IS_CNAME_ENV] = self._saved_is_cname
        if self._saved_verify_ssl is None:
            os.environ.pop(config.OBS_VERIFY_SSL_ENV, None)
        else:
            os.environ[config.OBS_VERIFY_SSL_ENV] = self._saved_verify_ssl

    def test_path_style_can_be_true_false_or_auto(self):
        os.environ.pop(config.OBS_PATH_STYLE_ENV, None)
        self.assertIsNone(config.get_obs_path_style())
        os.environ[config.OBS_PATH_STYLE_ENV] = "1"
        self.assertTrue(config.get_obs_path_style())
        os.environ[config.OBS_PATH_STYLE_ENV] = "false"
        self.assertFalse(config.get_obs_path_style())
        os.environ[config.OBS_PATH_STYLE_ENV] = "oops"
        self.assertIsNone(config.get_obs_path_style())

    def test_is_cname_is_truthy_only(self):
        os.environ.pop(config.OBS_IS_CNAME_ENV, None)
        self.assertFalse(config.get_obs_is_cname())
        os.environ[config.OBS_IS_CNAME_ENV] = "yes"
        self.assertTrue(config.get_obs_is_cname())
        os.environ[config.OBS_IS_CNAME_ENV] = "0"
        self.assertFalse(config.get_obs_is_cname())

    def test_verify_ssl_can_be_true_false_or_auto(self):
        os.environ.pop(config.OBS_VERIFY_SSL_ENV, None)
        self.assertIsNone(config.get_obs_verify_ssl())
        os.environ[config.OBS_VERIFY_SSL_ENV] = "1"
        self.assertTrue(config.get_obs_verify_ssl())
        os.environ[config.OBS_VERIFY_SSL_ENV] = "false"
        self.assertFalse(config.get_obs_verify_ssl())
        os.environ[config.OBS_VERIFY_SSL_ENV] = "maybe"
        self.assertIsNone(config.get_obs_verify_ssl())


class AzureTimeoutTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(config.AZURE_OPENAI_TIMEOUT_SECONDS_ENV)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop(config.AZURE_OPENAI_TIMEOUT_SECONDS_ENV, None)
        else:
            os.environ[config.AZURE_OPENAI_TIMEOUT_SECONDS_ENV] = self._saved

    def test_returns_float_when_set(self):
        os.environ[config.AZURE_OPENAI_TIMEOUT_SECONDS_ENV] = "180"
        self.assertEqual(config.get_azure_timeout_seconds(), 180.0)

    def test_returns_none_when_unset_or_invalid(self):
        os.environ.pop(config.AZURE_OPENAI_TIMEOUT_SECONDS_ENV, None)
        self.assertIsNone(config.get_azure_timeout_seconds())
        os.environ[config.AZURE_OPENAI_TIMEOUT_SECONDS_ENV] = "oops"
        self.assertIsNone(config.get_azure_timeout_seconds())
        os.environ[config.AZURE_OPENAI_TIMEOUT_SECONDS_ENV] = "0"
        self.assertIsNone(config.get_azure_timeout_seconds())


class EventseyeEnabledTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(config.EVENTSEYE_ENABLED_ENV)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop(config.EVENTSEYE_ENABLED_ENV, None)
        else:
            os.environ[config.EVENTSEYE_ENABLED_ENV] = self._saved

    def test_off_by_default(self):
        os.environ.pop(config.EVENTSEYE_ENABLED_ENV, None)
        self.assertFalse(config.eventseye_enabled())

    def test_truthy_values_enable(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            os.environ[config.EVENTSEYE_ENABLED_ENV] = value
            self.assertTrue(config.eventseye_enabled(), value)

    def test_other_values_stay_off(self):
        for value in ("0", "false", "no", ""):
            os.environ[config.EVENTSEYE_ENABLED_ENV] = value
            self.assertFalse(config.eventseye_enabled(), value)


if __name__ == "__main__":
    unittest.main()

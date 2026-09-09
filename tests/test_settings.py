import unittest
from travel_bot.settings import Settings

class SettingsTests(unittest.TestCase):
    def test_real_never_silently_falls_back(self):
        with self.assertRaisesRegex(ValueError, 'GOOGLE_PLACES_API_KEY'):
            Settings.load({'TELEGRAM_BOT_TOKEN': 'SECRET'})
        with self.assertRaisesRegex(ValueError, 'BOT_MODE'):
            Settings.load({'TELEGRAM_BOT_TOKEN': 'SECRET', 'BOT_MODE': 'typo'})
        real = {'TELEGRAM_BOT_TOKEN': 'SECRET', 'GOOGLE_PLACES_API_KEY': 'SECRET2',
                'PRIVACY_POLICY_URL': 'https://example.org/privacy', 'TERMS_URL': 'https://example.org/terms'}
        settings = Settings.load(real)
        self.assertNotIn('SECRET', repr(settings))
        self.assertEqual(settings.mode, 'real')
    def test_demo_explicit_and_no_google_key_needed(self):
        settings = Settings.load({'TELEGRAM_BOT_TOKEN': 'FAKE', 'BOT_MODE': 'demo'})
        self.assertEqual(settings.mode, 'demo')
    def test_public_policies_required_for_real(self):
        with self.assertRaisesRegex(ValueError, 'PRIVACY_POLICY_URL'):
            Settings.load({'TELEGRAM_BOT_TOKEN': 'FAKE', 'GOOGLE_PLACES_API_KEY': 'FAKE'})

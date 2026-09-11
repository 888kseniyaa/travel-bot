import unittest
from travel_bot.dialog import Dialog, InputError

class DialogTests(unittest.TestCase):
    def setUp(self):
        self.d = Dialog()
        self.key = (10, 1)
        self.d.start(self.key)

    def click(self, action, key=None):
        key = key or self.key
        return self.d.click(key, self.d.token(key, action))

    def places(self):
        self.d.text(self.key, 'Санкт-Петербург')
        self.click('category:museum')
        self.click('category:park')
        self.click('show')

    def test_toggle_and_empty_confirmation(self):
        self.places()
        with self.assertRaises(InputError): self.click('confirm')
        self.click('toggle:hermitage')
        self.assertEqual(self.d.store.get(self.key).selected, {'hermitage': 120})
        self.click('toggle:hermitage')
        self.assertEqual(self.d.store.get(self.key).selected, {})

    def test_duration_validation_and_total(self):
        self.places()
        self.click('toggle:hermitage')
        self.click('toggle:summer_garden')
        self.click('duration:hermitage')
        for value in ['0', '-1', '1.5', 'abc', '', '9' * 5000]:
            with self.assertRaises(InputError): self.d.text(self.key, value)
            self.assertEqual(self.d.store.get(self.key).selected['hermitage'], 120)
        self.d.text(self.key, ' 75 ')
        text, _ = self.d.view(self.key)
        self.assertIn('135 мин', text)
        self.click('confirm')
        self.click('back_to_places')
        self.assertEqual(self.d.store.get(self.key).selected['hermitage'], 75)

    def test_isolation_and_old_buttons(self):
        self.places()
        old = self.d.token(self.key, 'toggle:hermitage')
        self.d.start((10, 2))
        self.d.start((11, 1))
        for key in [(10, 2), (11, 1)]:
            with self.assertRaises(InputError): self.d.click(key, old)
            self.assertEqual(self.d.store.get(key).selected, {})
        self.d.click(self.key, old)
        with self.assertRaises(InputError): self.d.click(self.key, old)
        self.assertEqual(len(self.d.store.get(self.key).selected), 1)
        self.d.start(self.key)
        with self.assertRaises(InputError): self.d.click(self.key, old)
        self.assertEqual(self.d.store.get(self.key).selected, {})

    def test_geography_and_filter(self):
        with self.assertRaises(InputError): self.d.text(self.key, 'Москва')
        self.assertEqual(self.d.store.get(self.key).stage, 'geo')
        self.d.text(self.key, '  петроградский район ')
        self.click('category:architecture')
        self.click('show')
        text, _ = self.d.view(self.key)
        self.assertIn('Петропавловская', text)
        self.assertNotIn('Эрмитаж', text)
        with self.assertRaises(InputError): self.click('toggle:hermitage')

    def test_no_interests_and_no_results(self):
        self.d.text(self.key, 'Адмиралтейский')
        with self.assertRaises(InputError): self.click('show')
        self.click('category:park')
        self.click('show')
        self.assertIn('не найдено', self.d.view(self.key)[0])
        self.click('interests')
        self.click('category:architecture')
        self.click('show')
        self.assertIn('Исаакиевский', self.d.view(self.key)[0])

    def test_full_catalog_fits_telegram_limits(self):
        self.d.text(self.key, 'спб')
        for category in ('museum', 'park', 'architecture'):
            self.click('category:' + category)
        self.click('show')
        for place in self.d.store.get(self.key).places:
            self.click('toggle:' + place.id)
        text, rows = self.d.view(self.key)
        self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 4096)
        self.assertEqual(len(self.d.store.get(self.key).selected), 8)
        for row in rows:
            for label, data in row:
                self.assertLessEqual(len(data.encode('utf-8')), 64)

    def test_malformed_and_wrong_stage(self):
        for data in ['', 'junk', 'a:b:c:d:e']:
            with self.assertRaises(InputError): self.d.click(self.key, data)
        with self.assertRaises(InputError): self.click('toggle:hermitage')
        self.assertEqual(self.d.store.get(self.key).stage, 'geo')

if __name__ == '__main__': unittest.main()

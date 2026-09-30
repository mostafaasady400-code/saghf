"""
تست جامع سرویس تبدیل نوشتار به گفتار طبیعی فارسی (Neural TTS) و اندپوینت /properties/api/tts-audio
"""

import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from services.tts_service import clean_text_for_speech, synthesize_speech, DEFAULT_VOICE

class TestPersianNeuralTTSService(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        self.app_context.pop()

    def test_01_clean_text_for_speech(self):
        """تست پاکسازی علائم نگارشی، تگ‌های مارک‌داون و اموجی‌ها برای خوانش طبیعی"""
        raw_text = "💎 **آپارتمان ۱۸۰ متری** در سعادت‌آباد! [مشاهده آگهی](https://divar.ir/v/123) ⚡ قیمت: ۲۵ میلیارد"
        cleaned = clean_text_for_speech(raw_text)
        
        self.assertNotIn("💎", cleaned)
        self.assertNotIn("⚡", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("https://", cleaned)
        self.assertIn("آپارتمان ۱۸۰ متری", cleaned)
        self.assertIn("سعادت‌آباد", cleaned)

    @patch('services.tts_service._synthesize_edge_tts')
    def test_02_synthesize_speech_mocked(self, mock_edge):
        """تست تولید بایت‌های صوتی با کش هوشمند"""
        mock_edge.return_value = b"ID3\x03\x00\x00\x00FAKE_MP3_CONTENT_BYTES_FOR_TESTING_PURPOSES" * 10
        
        audio = synthesize_speech("سلام، مشاور سقف هستم.", voice=DEFAULT_VOICE)
        self.assertTrue(len(audio) > 100)
        self.assertTrue(audio.startswith(b"ID3"))

    def test_03_tts_audio_api_endpoint(self):
        """تست اندپوینت /properties/api/tts-audio جهت استریم فایل صوتی"""
        with patch('services.tts_service.synthesize_speech') as mock_synth:
            mock_synth.return_value = b"ID3_MOCK_STREAM_BYTES_TEST"
            
            # تست درخواست GET
            res_get = self.client.get('/properties/api/tts-audio?text=سلام')
            self.assertEqual(res_get.status_code, 200)
            self.assertEqual(res_get.content_type, 'audio/mpeg')
            self.assertEqual(res_get.data, b"ID3_MOCK_STREAM_BYTES_TEST")
            
            # تست درخواست POST
            res_post = self.client.post('/properties/api/tts-audio', json={'text': 'درخواست تست'})
            self.assertEqual(res_post.status_code, 200)
            self.assertEqual(res_post.content_type, 'audio/mpeg')
            
            # تست ورودی خالی
            res_empty = self.client.get('/properties/api/tts-audio?text=')
            self.assertEqual(res_empty.status_code, 400)

if __name__ == '__main__':
    unittest.main()

import unittest
from datetime import datetime, timedelta
from app import create_app
from database.db import db
from database.models import Property, Owner, Client
from services.messenger_service import OmniMessengerService

class TestLifecycleAndMessenger(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_property_lifecycle_properties(self):
        # Create test owner & property
        owner = Owner.query.first()
        if not owner:
            owner = Owner(full_name='مالک تستی', phone_number='09121112233')
            db.session.add(owner)
            db.session.commit()

        # 1. Fresh property (0 days old)
        p1 = Property(
            title='آپارتمان نوساز ولنجک',
            deal_type='sale',
            district='ولنجک',
            area=120,
            rooms=2,
            total_price=15000000000,
            status='available',
            owner_id=owner.id,
            created_at=datetime.utcnow()
        )
        db.session.add(p1)
        db.session.commit()

        self.assertEqual(p1.age_in_days, 0)
        self.assertFalse(p1.is_expired)

        # 2. Expired property (8 days old)
        p2 = Property(
            title='آپارتمان ۸ روزه فرمانیه',
            deal_type='sale',
            district='فرمانیه',
            area=140,
            rooms=3,
            total_price=20000000000,
            status='verified',
            owner_id=owner.id,
            created_at=datetime.utcnow() - timedelta(days=8)
        )
        db.session.add(p2)
        db.session.commit()

        self.assertGreaterEqual(p2.age_in_days, 8)
        self.assertTrue(p2.is_expired)

        # 3. Test Reactivation
        p2.reactivate()
        db.session.commit()
        self.assertEqual(p2.status, 'available')
        self.assertEqual(p2.age_in_days, 0)
        self.assertFalse(p2.is_expired)

        # 4. Test Archiving
        p2.archive(reason='sold')
        db.session.commit()
        self.assertEqual(p2.status, 'archived')
        self.assertEqual(p2.inquiry_status, 'confirmed_sold')

        # Clean up
        db.session.delete(p1)
        db.session.delete(p2)
        db.session.commit()

    def test_messenger_service_links_and_message(self):
        owner = Owner(full_name='آقای حسینی', phone_number='09123456789')
        db.session.add(owner)
        db.session.flush()

        prop = Property(
            title='پنت‌هاوس نیاوران',
            deal_type='sale',
            district='نیاوران',
            area=250,
            rooms=4,
            total_price=45000000000,
            status='available',
            owner_id=owner.id
        )
        db.session.add(prop)
        db.session.commit()

        # Test message generation
        msg = OmniMessengerService.generate_inquiry_message(prop)
        self.assertIn('نیاوران', msg)
        self.assertIn('پنت‌هاوس نیاوران', msg)
        self.assertIn('ارسال عدد ۱: ملک کماکان «موجود» است', msg)
        self.assertIn('ارسال عدد ۲: ملک «واگذار / فروخته» شده است', msg)

        # Test deep-links generation for all 5 platforms
        pkg = OmniMessengerService.generate_inquiry_package(prop.id)
        self.assertTrue(pkg['has_direct_phone'])
        self.assertIn('whatsapp', pkg['links'])
        self.assertIn('telegram', pkg['links'])
        self.assertIn('bale', pkg['links'])
        self.assertIn('eitaa', pkg['links'])
        self.assertIn('rubika', pkg['links'])

        self.assertIn('wa.me/989123456789', pkg['links']['whatsapp']['url'])
        self.assertIn('t.me/+989123456789', pkg['links']['telegram']['url'])
        self.assertIn('ble.ir/+989123456789', pkg['links']['bale']['url'])
        self.assertIn('eitaa.com/+989123456789', pkg['links']['eitaa']['url'])
        self.assertIn('rubika.ir/+989123456789', pkg['links']['rubika']['url'])

        # Test response handler
        res1 = OmniMessengerService.handle_owner_response(prop.id, '1', platform='whatsapp')
        self.assertTrue(res1['success'])
        self.assertEqual(res1['status'], 'available')

        res2 = OmniMessengerService.handle_owner_response(prop.id, '2', platform='telegram')
        self.assertTrue(res2['success'])
        self.assertEqual(res2['status'], 'archived')

        # Clean up
        db.session.delete(prop)
        db.session.delete(owner)
        db.session.commit()

    def test_routes_endpoints(self):
        # 1. Test properties list
        resp = self.client.get('/properties/')
        self.assertEqual(resp.status_code, 200)

        # 2. Test followup page
        resp = self.client.get('/properties/followup')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('یادآوری پیگیری مجدد'.encode('utf-8'), resp.data)

        # 3. Test messenger package API
        prop = Property.query.first()
        if prop:
            resp = self.client.get(f'/api/messenger/package/{prop.id}')
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data['success'])
            self.assertIn('links', data['package'])

if __name__ == '__main__':
    unittest.main()

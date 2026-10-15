import sys
import os

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from datetime import datetime, timedelta
import random
from app import create_app
from database.db import db
from database.models import Agent, Owner, Property, Client, Interaction, Visit, MatchRecord
from services.matching_service import MatchingEngine
from services.scoring_service import PropertyScorer

app = create_app()

with app.app_context():
    print("🌱 در حال آماده‌سازی و ساخت جداول دیتابیس SQLite...")
    db.create_all()

    # Check if data already exists
    if Agent.query.count() > 0:
        print("داده‌ها قبلاً ثبت شده‌اند.")
        exit(0)

    print("👤 ثبت مشاوران و کارشناسان املاک...")
    agents = [
        Agent(name='مهندس آریا شایگان', phone='09121112233', role='کارشناس فروش مناطق ۱ و ۲', avatar_color='#00f2fe'),
        Agent(name='خانم مهندس سارا صبوری', phone='09122223344', role='کارشناس رهن و اجاره لوکس', avatar_color='#10b981'),
        Agent(name='مهندس پویا رادمنش', phone='09123334455', role='مدیر قراردادها و نشست', avatar_color='#8b5cf6')
    ]
    db.session.add_all(agents)
    db.session.commit()

    print("🏠 ثبت مالکین و فایل‌های ملکی نمونه (شامل دیوار و شیپور)...")
    owners = [
        Owner(full_name='دکتر کامران رحیمی', phone_number='09124445566', urgency='high', flexibility='تخفیف دارد', notes='فروشنده واقعی به علت مهاجرت'),
        Owner(full_name='حاج اصغر کریمی', phone_number='09125556677', urgency='medium', flexibility='مقطوع', notes='سند تک برگ شخصی، بدون ریشه'),
        Owner(full_name='مهندس بهزاد نادری', phone_number='09126667788', urgency='high', flexibility='منعطف و تهاتر جزئی', notes='کلید نزد املاک است')
    ]
    db.session.add_all(owners)
    db.session.commit()

    # Sample Properties
    properties = [
        Property(
            source='divar',
            source_id='divar_wZ991001',
            source_url='https://divar.ir/v/wZ991001',
            title='آپارتمان ۱۴۵ متری ۳ خوابه کلیدنخورده سعادت آباد',
            deal_type='sale',
            property_type='apartment',
            city='تهران',
            district='سعادت آباد',
            address='تهران، سعادت آباد، بلوار ۲۴ متری، فرعی اعیان‌نشین',
            total_price=24650000000,
            meter_price=170000000,
            area=145,
            rooms=3,
            floor=4,
            total_floors=6,
            units_per_floor=2,
            build_year=1402,
            has_elevator=True,
            has_parking=True,
            has_warehouse=True,
            has_balcony=True,
            description='سازه برند و مهندسی‌ساز در بهترین فرعی سعادت آباد. سالن یکدست بدون پرتی و نورگیر مستقیم جنوب. ۲ پارکینگ سندی باکس، لابی مجلل مبله، سرایدار مقیم.',
            images=[
                'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=900&q=80',
                'https://images.unsplash.com/photo-1600566753376-12c8ab7fb75b?w=900&q=80'
            ],
            status='verified',
            owner_id=owners[0].id,
            assigned_agent_id=agents[0].id
        ),
        Property(
            source='sheypoor',
            source_id='sheypoor_sh44001',
            source_url='https://www.sheypoor.com/sh44001',
            title='رهن و اجاره آپارتمان ۱۱۰ متری دو خواب نیاوران',
            deal_type='rent',
            property_type='apartment',
            city='تهران',
            district='نیاوران',
            address='تهران، نیاوران، یاسر، کوچه مروارید',
            deposit=1200000000,
            monthly_rent=35000000,
            area=110,
            rooms=2,
            floor=3,
            build_year=1400,
            has_elevator=True,
            has_parking=True,
            has_warehouse=True,
            has_balcony=True,
            description='فایل اختصاصی نیاوران. غرق در نور، دسترسی آسان به مژده و باهنر، بازسازی شده مدرن با آشپزخانه فول فرنیش بوش، تراس دلباز رو به حیاط مشجر.',
            images=[
                'https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?w=900&q=80',
                'https://images.unsplash.com/photo-1600573472550-8090b5e0745e?w=900&q=80'
            ],
            status='verified',
            owner_id=owners[1].id,
            assigned_agent_id=agents[1].id
        ),
        Property(
            source='divar',
            source_id='divar_wZ991002',
            source_url='https://divar.ir/v/wZ991002',
            title='فروش آپارتمان ۱۸۰ متری ۳ خواب تک‌واحدی شهرک غرب',
            deal_type='sale',
            property_type='apartment',
            city='تهران',
            district='شهرک غرب',
            address='تهران، شهرک غرب، فاز ۱، خیابان ایران زمین',
            total_price=34200000000,
            meter_price=190000000,
            area=180,
            rooms=3,
            floor=2,
            build_year=1401,
            has_elevator=True,
            has_parking=True,
            has_warehouse=True,
            has_balcony=True,
            description='تک‌واحدی کم‌نظیر در ایران‌زمین شهرک غرب. متریال وارداتی برند، مسترروم کینگ با کلوزت اختصاصی، ارتفاع سقف ۳.۴۰ متر، ۲ پارکینگ سندی.',
            images=[
                'https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=900&q=80'
            ],
            status='verified',
            owner_id=owners[2].id,
            assigned_agent_id=agents[0].id
        ),
        Property(
            source='sheypoor',
            source_id='sheypoor_sh44002',
            source_url='https://www.sheypoor.com/sh44002',
            title='فروش آپارتمان ۹۰ متری دو خواب فول تهرانپارس غربی',
            deal_type='sale',
            property_type='apartment',
            city='تهران',
            district='تهرانپارس',
            address='تهران، تهرانپارس غربی، بین فلکه دوم و سوم',
            total_price=9900000000,
            meter_price=110000000,
            area=90,
            rooms=2,
            floor=3,
            build_year=1398,
            has_elevator=True,
            has_parking=True,
            has_warehouse=True,
            has_balcony=False,
            description='لوکیشن اعیان‌نشین تهرانپارس غربی. خوش نقشه بدون پرتی، سند تک برگ آماده انتقال، مناسب سرمایه‌گذاری و سکونت.',
            images=[
                'https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=900&q=80'
            ],
            status='raw_crawled',
            assigned_agent_id=agents[2].id
        ),
        Property(
            source='divar',
            source_id='divar_wZ991003',
            source_url='https://divar.ir/v/wZ991003',
            title='رهن کامل ۱۶۰ متری ۳ خوابه پاسداران گلستان',
            deal_type='rent',
            property_type='apartment',
            city='تهران',
            district='پاسداران',
            address='تهران، پاسداران، گلستان‌ها',
            deposit=2800000000,
            monthly_rent=0,
            area=160,
            rooms=3,
            floor=5,
            build_year=1399,
            has_elevator=True,
            has_parking=True,
            has_warehouse=True,
            has_balcony=True,
            description='رهن کامل بدون تبدیل در فرعی دنج گلستان پاسداران. نقشه تفکیکی، سالن رو به آفتاب، نگهبانی و لابی من ۲۴ ساعته.',
            images=[
                'https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=900&q=80'
            ],
            status='verified',
            assigned_agent_id=agents[1].id
        )
    ]

    for p in properties:
        p.score = PropertyScorer.calculate_score(p)
        p.features = ['سند رسمی', 'نورگیر عالی', 'لابی مجلل', 'متریال درجه یک']
        db.session.add(p)
    db.session.commit()

    print("👥 ثبت خریداران و متقاضیان ملکی...")
    clients = [
        Client(
            full_name='مهندس بابک افشار',
            phone_number='09127778899',
            preferred_deal_type='sale',
            min_budget=20000000000,
            max_budget=26000000000,
            min_area=130,
            max_area=160,
            min_rooms=3,
            must_have_parking=True,
            must_have_elevator=True,
            must_have_warehouse=True,
            urgency='urgent',
            lead_status='visiting',
            notes='خریدار نقد، دنبال واحد ۳ خوابه شیک در سعادت آباد یا شهرک غرب',
            assigned_agent_id=agents[0].id
        ),
        Client(
            full_name='خانم دکتر ترانه کیانی',
            phone_number='09128889900',
            preferred_deal_type='rent',
            max_deposit=1500000000,
            max_rent=40000000,
            min_area=100,
            max_area=130,
            min_rooms=2,
            must_have_parking=True,
            must_have_elevator=True,
            urgency='normal',
            lead_status='contacted',
            notes='برای مطب/سکونت در محدوده نیاوران یا پاسداران، متعهد به پرداخت منظم',
            assigned_agent_id=agents[1].id
        ),
        Client(
            full_name='دکتر فرهاد مجد',
            phone_number='09129990011',
            preferred_deal_type='sale',
            min_budget=30000000000,
            max_budget=36000000000,
            min_area=170,
            max_area=220,
            min_rooms=3,
            must_have_parking=True,
            must_have_elevator=True,
            urgency='immediate',
            lead_status='negotiating',
            notes='سرمایه‌گذار آماده واریز وجه، علاقه خاص به تک‌واحدی در شهرک غرب',
            assigned_agent_id=agents[0].id
        ),
        Client(
            full_name='مهندس نیما شمس',
            phone_number='09351112233',
            preferred_deal_type='sale',
            min_budget=8500000000,
            max_budget=10500000000,
            min_area=80,
            max_area=100,
            min_rooms=2,
            must_have_parking=True,
            urgency='normal',
            lead_status='new',
            notes='دنبال واحد ۲ خوابه در تهرانپارس با پارکینگ سندی',
            assigned_agent_id=agents[2].id
        )
    ]
    clients[0].preferred_districts = ['سعادت آباد', 'شهرک غرب']
    clients[1].preferred_districts = ['نیاوران', 'فرمانیه', 'پاسداران']
    clients[2].preferred_districts = ['شهرک غرب', 'سعادت آباد']
    clients[3].preferred_districts = ['تهرانپارس']

    db.session.add_all(clients)
    db.session.commit()

    print("📞 ثبت لاگ تماس‌ها و پیگیری‌های اولیه...")
    interactions = [
        Interaction(
            type='call',
            target_type='client',
            target_id=clients[0].id,
            client_id=clients[0].id,
            property_id=properties[0].id,
            agent_id=agents[0].id,
            summary='تماس تلفنی با مشتری برقرار شد. فایل ۱۴۵ متری سعادت آباد برایشان معرفی گردید و بسیار استقبال کردند.',
            outcome='requested_visit',
            next_followup_date=datetime.now() + timedelta(days=1)
        ),
        Interaction(
            type='meeting',
            target_type='client',
            target_id=clients[2].id,
            client_id=clients[2].id,
            property_id=properties[2].id,
            agent_id=agents[0].id,
            summary='جلسه کارشناسی تک‌واحدی شهرک غرب برگزار شد. قیمت اعلامی مالک ۳۴.۲ میلیارد تومان بررسی گردید و خریدار برای نشست اعلام آمادگی کرد.',
            outcome='interested',
            next_followup_date=datetime.now() + timedelta(days=2)
        )
    ]
    db.session.add_all(interactions)

    print("📅 ثبت برنامه‌ریزی بازدید...")
    visits = [
        Visit(
            property_id=properties[0].id,
            client_id=clients[0].id,
            agent_id=agents[0].id,
            scheduled_time=datetime.now() + timedelta(hours=3),
            status='scheduled',
            readiness_to_buy=4
        ),
        Visit(
            property_id=properties[1].id,
            client_id=clients[1].id,
            agent_id=agents[1].id,
            scheduled_time=datetime.now() - timedelta(days=1),
            status='completed',
            feedback='مشتری نورگیر و لابی را بسیار پسندید، درخواست کمی تخفیف در ودیعه داشت.',
            readiness_to_buy=4
        )
    ]
    db.session.add_all(visits)
    db.session.commit()

    print("⚡ اجرای موتور تطبیق هوشمند اولیه...")
    MatchingEngine.refresh_matches_for_all(threshold=60)

    print("✅ دیتابیس با موفقیت راه‌اندازی و با داده‌های اولیه هوشمند بارگذاری شد.")

import time
from datetime import datetime, date, timedelta
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from database.db import db
from database.models import Property, Client, Interaction, Visit, Agent, MatchRecord

class AnalyticsService:
    """
    سرویس تحلیل آمار، گزارش عملکرد مشاوران و شاخص‌های کلیدی (KPIs) برای داشبورد نئون دارک سقف
    مجهز به کش حافظه‌ای با فرکانس به‌روزرسانی هوشمند و کوئری‌های تجمیعی دسته‌جمعی (Batch Aggregation)
    """
    _kpis_cache = {'data': None, 'time': 0}
    _agents_cache = {'data': None, 'time': 0}
    _activities_cache = {'data': None, 'time': 0}

    @classmethod
    def invalidate_cache(cls):
        """ابطال سریع کش هنگام ثبت فایل جدید، تغییر وضعیت مشتری یا تطبیق جدید"""
        cls._kpis_cache['time'] = 0
        cls._agents_cache['time'] = 0
        cls._activities_cache['time'] = 0

    @classmethod
    def get_dashboard_kpis(cls):
        now_ts = time.time()
        if now_ts - cls._kpis_cache['time'] < 15 and cls._kpis_cache['data'] is not None:
            return cls._kpis_cache['data']

        today_start = datetime.combine(date.today(), datetime.min.time())
        cutoff_7days = datetime.utcnow() - timedelta(days=7)

        total_properties = Property.query.count()
        crawled_today = Property.query.filter(Property.created_at >= today_start, Property.source.in_(['divar', 'sheypoor'])).count()
        
        # 7-day lifecycle breakdown
        active_properties_count = Property.query.filter(
            Property.created_at >= cutoff_7days,
            Property.status.notin_(['archived', 'sold', 'needs_followup'])
        ).count()
        expired_properties_count = Property.query.filter(
            (Property.created_at < cutoff_7days) | (Property.status == 'needs_followup'),
            Property.status.notin_(['archived', 'sold'])
        ).count()
        verified_properties = active_properties_count
        
        total_clients = Client.query.count()
        active_leads = Client.query.filter(Client.lead_status.notin_(['contract_won', 'lost'])).count()
        
        today_visits = Visit.query.filter(Visit.scheduled_time >= today_start, Visit.status == 'scheduled').count()
        
        # Pipeline stages count via single grouped query
        stage_counts = dict(
            db.session.query(Client.lead_status, func.count(Client.id))
            .group_by(Client.lead_status).all()
        )
        deals_won = stage_counts.get('contract_won', 0)
        pipeline_stages = {
            'new': stage_counts.get('new', 0),
            'contacted': stage_counts.get('contacted', 0),
            'visiting': stage_counts.get('visiting', 0),
            'negotiating': stage_counts.get('negotiating', 0),
            'contract_won': deals_won
        }

        # Conversion rate
        conv_rate = round((deals_won / total_clients * 100), 1) if total_clients > 0 else 0

        # District distribution (Top 6)
        district_counts = db.session.query(
            Property.district, func.count(Property.id)
        ).group_by(Property.district).order_by(func.count(Property.id).desc()).limit(6).all()

        district_labels = [d[0] for d in district_counts]
        district_values = [d[1] for d in district_counts]

        # High match opportunities (matches >= 80%)
        high_matches_count = MatchRecord.query.filter(MatchRecord.match_score >= 80).count()

        kpi_data = {
            'total_properties': total_properties,
            'active_properties_count': active_properties_count,
            'expired_properties_count': expired_properties_count,
            'crawled_today': crawled_today,
            'verified_properties': verified_properties,
            'total_clients': total_clients,
            'active_leads': active_leads,
            'today_visits': today_visits,
            'deals_won': deals_won,
            'conversion_rate': conv_rate,
            'high_matches_count': high_matches_count,
            'district_labels': district_labels,
            'district_values': district_values,
            'pipeline_stages': pipeline_stages
        }
        cls._kpis_cache['time'] = now_ts
        cls._kpis_cache['data'] = kpi_data
        return kpi_data

    @classmethod
    def get_agent_performance(cls):
        now_ts = time.time()
        if now_ts - cls._agents_cache['time'] < 15 and cls._agents_cache['data'] is not None:
            return cls._agents_cache['data']

        agents = Agent.query.filter_by(is_active=True).all()
        if not agents:
            return []

        # Batch queries to completely eliminate N+1 latency
        deal_counts = dict(
            db.session.query(Client.assigned_agent_id, func.count(Client.id))
            .filter(Client.lead_status == 'contract_won')
            .group_by(Client.assigned_agent_id).all()
        )
        visit_counts = dict(
            db.session.query(Visit.agent_id, func.count(Visit.id))
            .filter(Visit.status == 'completed')
            .group_by(Visit.agent_id).all()
        )
        call_counts = dict(
            db.session.query(Interaction.agent_id, func.count(Interaction.id))
            .group_by(Interaction.agent_id).all()
        )
        prop_counts = dict(
            db.session.query(Property.assigned_agent_id, func.count(Property.id))
            .group_by(Property.assigned_agent_id).all()
        )

        performance = []
        for agent in agents:
            performance.append({
                'id': agent.id,
                'name': agent.name,
                'role': agent.role,
                'avatar_color': agent.avatar_color,
                'closed_deals': deal_counts.get(agent.id, 0),
                'visits_done': visit_counts.get(agent.id, 0),
                'calls_made': call_counts.get(agent.id, 0),
                'assigned_files': prop_counts.get(agent.id, 0)
            })

        cls._agents_cache['time'] = now_ts
        cls._agents_cache['data'] = performance
        return performance

    @classmethod
    def get_recent_activities(cls, limit=8):
        now_ts = time.time()
        if now_ts - cls._activities_cache['time'] < 10 and cls._activities_cache['data'] is not None:
            return cls._activities_cache['data'][:limit]

        activities = []

        # Recent interactions with eager-loaded agents
        recent_interactions = Interaction.query.options(joinedload(Interaction.agent)).order_by(Interaction.created_at.desc()).limit(limit).all()
        for it in recent_interactions:
            activities.append({
                'type': 'interaction',
                'title': f"پیگیری: {(it.summary or '')[:45]}...",
                'badge': 'تماس' if it.type == 'call' else 'مذاکره',
                'badge_color': 'cyan',
                'agent': it.agent.name if it.agent else 'مشاور',
                'time': it.created_at.strftime('%H:%M') if it.created_at else ''
            })

        # Recent visits with eager-loaded property and client
        recent_visits = Visit.query.options(joinedload(Visit.property), joinedload(Visit.client), joinedload(Visit.agent)).order_by(Visit.scheduled_time.desc()).limit(4).all()
        for v in recent_visits:
            activities.append({
                'type': 'visit',
                'title': f"بازدید هماهنگ‌شده: {v.property.title if v.property else 'ملک'} برای {v.client.full_name if v.client else 'مشتری'}",
                'badge': 'بازدید',
                'badge_color': 'emerald',
                'agent': v.agent.name if v.agent else 'کارشناس',
                'time': v.scheduled_time.strftime('%Y-%m-%d %H:%M') if v.scheduled_time else ''
            })

        activities.sort(key=lambda x: x['time'], reverse=True)
        result = activities[:limit]
        cls._activities_cache['time'] = now_ts
        cls._activities_cache['data'] = result
        return result

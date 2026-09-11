from datetime import datetime, date
from sqlalchemy import func
from database.db import db
from database.models import Property, Client, Interaction, Visit, Agent, MatchRecord

class AnalyticsService:
    """
    سرویس تحلیل آمار، گزارش عملکرد مشاوران و شاخص‌های کلیدی (KPIs) برای داشبورد نئون دارک سقف
    """
    @staticmethod
    def get_dashboard_kpis():
        today_start = datetime.combine(date.today(), datetime.min.time())

        total_properties = Property.query.count()
        crawled_today = Property.query.filter(Property.created_at >= today_start, Property.source.in_(['divar', 'sheypoor'])).count()
        verified_properties = Property.query.filter(Property.status.in_(['verified', 'available'])).count()
        
        total_clients = Client.query.count()
        active_leads = Client.query.filter(Client.lead_status.notin_(['contract_won', 'lost'])).count()
        
        today_visits = Visit.query.filter(Visit.scheduled_time >= today_start, Visit.status == 'scheduled').count()
        deals_won = Client.query.filter_by(lead_status='contract_won').count()

        # Conversion rate
        conv_rate = round((deals_won / total_clients * 100), 1) if total_clients > 0 else 0

        # District distribution (Top 5)
        district_counts = db.session.query(
            Property.district, func.count(Property.id)
        ).group_by(Property.district).order_by(func.count(Property.id).desc()).limit(6).all()

        district_labels = [d[0] for d in district_counts]
        district_values = [d[1] for d in district_counts]

        # Pipeline stages count
        pipeline_stages = {
            'new': Client.query.filter_by(lead_status='new').count(),
            'contacted': Client.query.filter_by(lead_status='contacted').count(),
            'visiting': Client.query.filter_by(lead_status='visiting').count(),
            'negotiating': Client.query.filter_by(lead_status='negotiating').count(),
            'contract_won': deals_won
        }

        # High match opportunities (matches >= 80%)
        high_matches_count = MatchRecord.query.filter(MatchRecord.match_score >= 80).count()

        return {
            'total_properties': total_properties,
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

    @staticmethod
    def get_agent_performance():
        agents = Agent.query.filter_by(is_active=True).all()
        performance = []
        for agent in agents:
            closed_deals = Client.query.filter_by(assigned_agent_id=agent.id, lead_status='contract_won').count()
            visits_done = Visit.query.filter_by(agent_id=agent.id, status='completed').count()
            calls_made = Interaction.query.filter_by(agent_id=agent.id).count()
            assigned_files = Property.query.filter_by(assigned_agent_id=agent.id).count()

            performance.append({
                'id': agent.id,
                'name': agent.name,
                'role': agent.role,
                'avatar_color': agent.avatar_color,
                'closed_deals': closed_deals,
                'visits_done': visits_done,
                'calls_made': calls_made,
                'assigned_files': assigned_files
            })
        return performance

    @staticmethod
    def get_recent_activities(limit=8):
        activities = []

        # Recent interactions
        recent_interactions = Interaction.query.order_by(Interaction.created_at.desc()).limit(limit).all()
        for it in recent_interactions:
            activities.append({
                'type': 'interaction',
                'title': f"پیگیری: {it.summary[:45]}...",
                'badge': 'تماس' if it.type == 'call' else 'مذاکره',
                'badge_color': 'cyan',
                'agent': it.agent.name if it.agent else 'مشاور',
                'time': it.created_at.strftime('%H:%M') if it.created_at else ''
            })

        # Recent visits
        recent_visits = Visit.query.order_by(Visit.scheduled_time.desc()).limit(4).all()
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
        return activities[:limit]

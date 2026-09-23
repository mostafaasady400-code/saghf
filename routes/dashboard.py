from flask import Blueprint, render_template, jsonify
from services.analytics_service import AnalyticsService
from database.models import Property, MatchRecord, Client

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
def index():
    kpis = AnalyticsService.get_dashboard_kpis()
    agents = AnalyticsService.get_agent_performance()
    activities = AnalyticsService.get_recent_activities(limit=6)
    
    # Latest crawled properties
    recent_properties = Property.query.order_by(Property.created_at.desc()).limit(6).all()
    
    # Top matching opportunities
    top_matches = MatchRecord.query.order_by(MatchRecord.match_score.desc()).limit(5).all()

    # Department Counts
    sale_count = Property.query.filter(Property.deal_type == 'sale', Property.status.notin_(['archived', 'sold'])).count()
    rent_count = Property.query.filter(Property.deal_type == 'rent', Property.status.notin_(['archived', 'sold'])).count()

    return render_template(
        'dashboard.html',
        kpis=kpis,
        agents=agents,
        activities=activities,
        recent_properties=recent_properties,
        top_matches=top_matches,
        sale_count=sale_count,
        rent_count=rent_count
    )

@dashboard_bp.route('/api/dashboard/stats')
def get_stats():
    return jsonify({
        'kpis': AnalyticsService.get_dashboard_kpis(),
        'agents': AnalyticsService.get_agent_performance(),
        'activities': AnalyticsService.get_recent_activities(limit=8)
    })

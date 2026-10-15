"""Run existing web app with explicit independent owner pre-guard installed."""
import argparse
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    os.environ["SAGHF_LEGACY_DIVAR_MONITOR"] = "0"
    from crawler.strict_owner_guard import install_strict_owner_guard
    install_strict_owner_guard()
    from app import app
    from verification.team_review_routes import install_team_review
    install_team_review(app)
    from crawler.strict_owner_guard import VERSION
    from crawler.owner_filter import OwnerFilter
    @app.get("/__strict_owner_guard_health")
    def strict_guard_health():
        return {"guard_version": VERSION, "enabled": getattr(OwnerFilter.evaluate, "_strict_owner_version", None) == VERSION}
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

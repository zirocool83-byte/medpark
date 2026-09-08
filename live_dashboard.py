import dashboard_actual_fix as active

app = active.app

# Fresh route on the current runtime. Uses the exact same authenticated dashboard
# renderer as the root endpoint, but a new URL guarantees the browser cannot reuse
# an already-loaded document from before the Procfile fix.
if "live_dashboard" not in app.view_functions:
    app.add_url_rule(
        "/live-dashboard",
        endpoint="live_dashboard",
        view_func=active.dashboard_actual,
        methods=["GET"],
    )

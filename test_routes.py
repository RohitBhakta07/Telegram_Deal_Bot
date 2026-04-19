"""Quick test: verify all routes register and templates render without errors."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dashboard.app import create_app

app = create_app()

print("=== REGISTERED ROUTES ===")
rules = sorted(app.url_map.iter_rules(), key=lambda r: r.rule)
for r in rules:
    if r.endpoint == 'static':
        continue
    methods = r.methods - {"HEAD", "OPTIONS"}
    print(f"  {methods}  {r.rule}  ->  {r.endpoint}")

print(f"\nTotal: {len(rules)} routes registered")

# Test that key pages don't crash (template rendering)
print("\n=== TEMPLATE RENDER TEST ===")
with app.test_client() as client:
    tests = [
        ("GET", "/login", 200),
        ("GET", "/", 302),          # redirect to login (not logged in)
        ("GET", "/channels", 302),
        ("GET", "/admins", 302),
        ("GET", "/overview", 302),
        ("GET", "/live_console", 302),
        ("GET", "/settings", 302),
        ("GET", "/channel/test-slug/login", 404),  # slug doesn't exist in DB
        ("GET", "/nonexistent", 404),
    ]
    
    all_passed = True
    for method, path, expected in tests:
        resp = client.get(path) if method == "GET" else client.post(path)
        status = "PASS" if resp.status_code == expected else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"  [{status}] {method} {path} -> {resp.status_code} (expected {expected})")
    
    # Test with login session
    print("\n=== LOGGED-IN TEMPLATE RENDER ===")
    with client.session_transaction() as sess:
        sess['super_admin_logged_in'] = True
    
    logged_in_tests = [
        ("/", 200, "Dashboard"),
        ("/channels", 200, "Channels"),
        ("/admins", 200, "Admins"),
        ("/overview", 200, "Overview"),
        ("/live_console", 200, "Console"),
        ("/settings", 200, "Settings"),
    ]
    
    for path, expected, name in logged_in_tests:
        resp = client.get(path)
        status = "PASS" if resp.status_code == expected else "FAIL"
        if status == "FAIL":
            all_passed = False
            # Print first 500 chars of response for debugging
            print(f"  [{status}] {name}: {path} -> {resp.status_code} (expected {expected})")
            print(f"         Response: {resp.data[:500]}")
        else:
            print(f"  [{status}] {name}: {path} -> {resp.status_code}")

    print(f"\n{'ALL TESTS PASSED!' if all_passed else 'SOME TESTS FAILED!'}")

from flask import Flask, request, jsonify
from flask_cors import CORS
from scrapper.scraper_core import (
    create_driver,
    wait_for_manual_login,
    build_search_url,
    try_apply_location_facet,
    scrape_results,
    next_page,
    filter_by_location,
    fetch_contact,
    save_outputs,
)
import time
import os

app = Flask(__name__)

CORS(app, resources={
    r"/*": {
        "origins": [
            "https://linked-in-frontend-five.vercel.app",
            "http://linked-in-frontend-five.vercel.app"
        ]
    }
})

@app.get("/")
def health():
    return {"status": "ok", "message": "LinkedIn Scraper API running"}

@app.post("/run-scraper")
def run_scraper():
    print("\n[ BACKEND ACTIVE ] Request received...")

    data = request.get_json(force=True) or {}
    print("[DEBUG] Payload:", data)

    query = data.get("query", "")
    location = data.get("location", "")
    pages = int(data.get("pages", 5))
    output = data.get("output", "results")
    fetch = bool(data.get("fetch_contact", False))
    headless = bool(data.get("headless", False))
    excel = bool(data.get("excel", False))

    print(
        f"[DEBUG] query={query!r}, location={location!r}, pages={pages}, "
        f"output={output!r}, fetch_contact={fetch}, headless={headless}, excel={excel}"
    )

    driver = create_driver(headless=headless)
    print("[DEBUG] Chrome driver created.")

    try:
        print("[DEBUG] Waiting for LinkedIn login...")
        ok = wait_for_manual_login(driver, timeout_s=300)
        if not ok:
            print("[ERROR] Login timeout")
            return jsonify({"ok": False, "error": "Login timeout"}), 400

        print("[DEBUG] Login detected. Searching...")
        driver.get(build_search_url(query))
        time.sleep(2)

        if location:
            print(f"[DEBUG] Applying location facet: {location}")
            try_apply_location_facet(driver, location)

        collected = []
        seen = set()

        for p in range(1, pages + 1):
            print(f"[DEBUG] Scraping page {p}...")
            rows = scrape_results(driver)
            print(f"[DEBUG] {len(rows)} rows found.")

            for r in rows:
                key = (r.get("profile_url") or r.get("name", "")).strip()
                if key and key not in seen:
                    seen.add(key)
                    r.setdefault("email", "")
                    r.setdefault("phone", "")
                    r.setdefault("website", "")
                    r.setdefault("other", "")
                    collected.append(r)

            if not next_page(driver):
                break

        print(f"[DEBUG] Total collected: {len(collected)}")
        filtered = filter_by_location(collected, location)
        print(f"[DEBUG] After filter: {len(filtered)}")

        if fetch:
            print("[DEBUG] Fetching contact info...")
            for idx, r in enumerate(filtered, 1):
                url = r.get("profile_url", "")
                print(f"[DEBUG] Visiting {idx}/{len(filtered)}: {url}")
                contact = fetch_contact(driver, url)
                r.update(contact)
                time.sleep(1)

        print("[DEBUG] Saving output files...")
        files = save_outputs(filtered, output, excel=excel)

        return jsonify({
            "ok": True,
            "total": len(collected),
            "filtered": len(filtered),
            "files": files
        })

    except Exception as e:
        print("[EXCEPTION]", e)
        return jsonify({"ok": False, "error": str(e)}), 500

    finally:
        print("[DEBUG] Closing browser...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("\n===========================================")
    print("  BACKEND ACTIVE: LinkedIn Scraper API")
    print(f"  Listening on 0.0.0.0:{port}")
    print("===========================================\n")
    app.run(host="0.0.0.0", port=port, debug=False)

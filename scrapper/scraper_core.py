# scrapper/scraper_core.py

import time
import re
import os
import pandas as pd
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


# -------------------------------------------------
# Create Chrome WebDriver
# -------------------------------------------------
def create_driver(headless: bool = False):
    options = Options()
    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    # Best-effort: hide webdriver flag
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            },
        )
    except Exception:
        pass

    return driver


# -------------------------------------------------
# Auto-detect login (NO input(), more strict)
# -------------------------------------------------
def _is_logged_in(driver) -> bool:
    """
    Heuristic: consider user logged in ONLY if:
      - We are NOT on /login or /checkpoint, AND
      - We see the top nav / profile area ("Me" menu, avatar, etc.)
    """
    try:
        url = (driver.current_url or "").lower()
    except Exception:
        url = ""

    if "login" in url or "checkpoint" in url:
        return False

    try:
        # Look for typical nav/profile elements shown only when logged in
        elems = driver.find_elements(
            By.XPATH,
            "//*[contains(@class,'global-nav__me') "
            "or contains(@aria-label,'Me') "
            "or contains(@id,'profile-nav-item') "
            "or contains(@data-test-global-nav-link,'profile')]"
        )
        if elems:
            return True
    except Exception:
        pass

    return False


def wait_for_manual_login(driver, timeout_s: int = 300, poll_interval: float = 2.0):
    """
    Hosted / auto mode:
      - Tries /feed first: if you're already logged in, it will work immediately.
      - Otherwise redirects to /login.
      - You log in manually in the opened browser window.
      - We poll until we detect the *logged-in* nav/profile bar.
      - No input(), so this can run on a hosted backend as long as
        the browser is available there.
    """
    # 1) Try going directly to feed (handles "already logged in" case)
    print("\n[LOGIN] Checking if already logged in...")
    driver.get("https://www.linkedin.com/feed/")
    time.sleep(3)

    if _is_logged_in(driver):
        print("[LOGIN] Already logged in (detected nav/profile).")
        return True

    # 2) Not logged in → go to login page and wait for manual login
    print("[LOGIN] Not logged in yet. Opening LinkedIn login page...")
    driver.get("https://www.linkedin.com/login")
    print("[LOGIN] Please log into your LinkedIn account in the opened browser window.")
    print(f"[LOGIN] Waiting (up to {timeout_s} seconds) for login to complete...")

    start = time.time()
    last_log = start

    while True:
        if _is_logged_in(driver):
            try:
                url = driver.current_url
            except Exception:
                url = "UNKNOWN"
            print(f"[LOGIN] Login detected (nav/profile visible). Current URL: {url}")
            return True

        now = time.time()
        if now - start > timeout_s:
            print("[LOGIN] Timeout waiting for login.")
            return False

        # Don't spam logs too much
        if now - last_log > 10:
            try:
                print("[LOGIN] Still waiting... current URL:", driver.current_url)
            except Exception:
                print("[LOGIN] Still waiting... (could not read URL)")
            last_log = now

        time.sleep(poll_interval)


# -------------------------------------------------
# Build search URL
# -------------------------------------------------
def build_search_url(query: str):
    if not query:
        return "https://www.linkedin.com/search/results/people/"
    encoded = quote_plus(query)
    return f"https://www.linkedin.com/search/results/people/?keywords={encoded}"


# -------------------------------------------------
# Try apply location facet (best-effort, fragile)
# -------------------------------------------------
def try_apply_location_facet(driver, desired_location: str) -> bool:
    if not desired_location:
        return False

    dl = desired_location.strip().lower()
    print(f"[FILTER] Trying to apply location facet for: {desired_location!r}")

    try:
        time.sleep(1.2)
        # Try click "All filters" if present
        try:
            btn = driver.find_element(
                By.XPATH,
                "//button[contains(., 'All filters') or contains(., 'Filters')]",
            )
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(1.0)
        except Exception:
            pass

        # Try click anything whose text contains the location
        elements = driver.find_elements(
            By.XPATH,
            f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{dl}')]",
        )
        for el in elements:
            try:
                text = (el.text or "").strip().lower()
                if dl in text:
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(1.2)
                    print(f"[FILTER] Applied location facet using element: {text[:80]!r}")
                    return True
            except Exception:
                continue

    except Exception:
        pass

    print("[FILTER] Could not apply location facet via UI (will rely on strong post-filter).")
    return False


# -------------------------------------------------
# Scrape list page results
# -------------------------------------------------
def scrape_results(driver):
    """
    Scrape visible search results on the current page.
    Returns list of dicts: {name, headline, location, profile_url}
    """
    time.sleep(2.0)

    # Scroll to load more
    for i in range(4):
        try:
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight/4);")
        except Exception:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.8)

    results = []
    container_selectors = [
        "li.reusable-search__result-container",
        '[data-test-search-result-item]',
        "div.search-results-container li",
        "div.search-result__info",
        "div.search-result__wrapper",
    ]

    containers = []
    for sel in container_selectors:
        try:
            found = driver.find_elements(By.CSS_SELECTOR, sel)
            if found:
                containers = found
                break
        except Exception:
            continue

    if not containers:
        print("[SCRAPE] No containers found on this page.")
        return results

    for card in containers:
        try:
            # NAME
            name = ""
            try:
                name = card.find_element(By.CSS_SELECTOR, "span[aria-hidden='true']").text.strip()
            except Exception:
                try:
                    name = card.find_element(By.CSS_SELECTOR, "a.app-aware-link").text.strip()
                except Exception:
                    name = ""
            if not name:
                continue

            # HEADLINE
            headline = ""
            for hs in [
                ".entity-result__primary-subtitle",
                "p.entity-result__primary-subtitle",
                "div.t-14.t-normal",
                "div.entity-result__summary",
                "span.entity-result__subtitle",
            ]:
                try:
                    text = card.find_element(By.CSS_SELECTOR, hs).text.strip()
                    if text:
                        headline = text
                        break
                except Exception:
                    continue

            # LOCATION
            location = ""
            for ls in [
                ".entity-result__secondary-subtitle",
                "p.entity-result__secondary-subtitle",
                "div.t-12.t-black--light",
                "span.entity-result__location",
            ]:
                try:
                    t = card.find_element(By.CSS_SELECTOR, ls).text.strip()
                    if t:
                        location = t
                        break
                except Exception:
                    continue

            # PROFILE URL
            profile_url = ""
            try:
                link = card.find_element(By.CSS_SELECTOR, "a.app-aware-link")
                profile_url = link.get_attribute("href") or ""
            except Exception:
                profile_url = ""

            results.append(
                {
                    "name": name,
                    "headline": headline,
                    "location": location,
                    "profile_url": profile_url,
                }
            )
        except Exception:
            continue

    print(f"[SCRAPE] Extracted {len(results)} results from page.")
    return results


# -------------------------------------------------
# Next page navigation
# -------------------------------------------------
def next_page(driver) -> bool:
    time.sleep(1.2)
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.0)
    except Exception:
        pass

    next_xpaths = [
        "//button[contains(@aria-label,'Next') and not(contains(@disabled,'true'))]",
        "//button[contains(text(),'Next') and not(contains(@disabled,'true'))]",
        "//a[contains(@aria-label,'Next') and not(contains(@disabled,'true'))]",
        "//a[contains(text(),'Next') and not(contains(@disabled,'true'))]",
    ]

    for xp in next_xpaths:
        try:
            btn = driver.find_element(By.XPATH, xp)
            if btn and btn.is_displayed() and btn.is_enabled():
                try:
                    driver.execute_script("arguments[0].click();", btn)
                except Exception:
                    btn.click()
                time.sleep(2.2)
                print("[PAGE] Moved to next page via:", xp)
                return True
        except Exception:
            continue

    print("[PAGE] Next page not found - stopping.")
    return False


# -------------------------------------------------
# Strong location filter (post-processing)
# -------------------------------------------------
def filter_by_location(results, location):
    if not location:
        return results

    dl = location.lower()
    filtered = [
        r
        for r in results
        if dl in (r.get("location") or "").lower()
        or dl in (r.get("headline") or "").lower()
    ]

    print(
        f"[FILTER] Strong location filter '{location}': "
        f"{len(filtered)}/{len(results)} rows kept."
    )
    return filtered


# -------------------------------------------------
# Fetch contact info from individual profile
# -------------------------------------------------
def fetch_contact(driver, url):
    contact = {"email": "", "phone": "", "website": "", "other": ""}

    if not url:
        return contact

    try:
        driver.get(url)
        time.sleep(2.0)

        open_xpaths = [
            "//a[contains(@data-control-name,'contact_see_more')]",
            "//button[contains(., 'Contact info')]",
            "//a[contains(@href, 'overlay/contactInfo')]",
            "//a[contains(., 'Contact info')]",
        ]

        for xp in open_xpaths:
            try:
                el = driver.find_element(By.XPATH, xp)
                driver.execute_script("arguments[0].click();", el)
                time.sleep(1.2)
                break
            except Exception:
                continue

        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            body_text = ""

        emails = list(
            set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", body_text))
        )
        phones = list(set(re.findall(r"\+?\d[\d\s\-\(\)]{6,}\d", body_text)))
        urls = [
            u
            for u in re.findall(r"https?://\S+", body_text)
            if "linkedin.com" not in u
        ]

        contact["email"] = "; ".join(emails)
        contact["phone"] = "; ".join(phones)
        contact["website"] = "; ".join(urls)
        contact["other"] = body_text[:500]

        print(f"[CONTACT] {url} -> emails={len(emails)}, phones={len(phones)}, urls={len(urls)}")
    except Exception:
        print(f"[CONTACT] Failed to fetch contact info for {url}")

    return contact

def save_outputs(rows, basename, excel=False):
    if not rows:
        print("[SAVE] No rows to save.")
        return {"tsv": None, "xlsx": None}

    df = pd.DataFrame(rows)

    cols = ["name", "headline", "location", "profile_url", "email", "phone", "website", "other"]
    for c in cols:
        if c not in df.columns:
            df[c] = ""

    df = df[cols]

    # Ensure basename has no extension
    base = basename
    if base.lower().endswith((".tsv", ".csv", ".xlsx")):
        base = ".".join(base.split(".")[:-1])

    tsv_path = f"{base}.tsv"
    df.to_csv(tsv_path, sep="\t", index=False, encoding="utf-8")
    print(f"[SAVE] TSV saved -> {os.path.abspath(tsv_path)}")

    xlsx_path = None
    if excel:
        xlsx_path = f"{base}.xlsx"
        df.to_excel(xlsx_path, index=False)
        print(f"[SAVE] Excel saved -> {os.path.abspath(xlsx_path)}")

    return {
        "tsv": os.path.abspath(tsv_path),
        "xlsx": os.path.abspath(xlsx_path) if xlsx_path else None,
    }

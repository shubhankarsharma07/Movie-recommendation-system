"""
CineMatch frontend — interaction smoke test (mock mode).
Checks keyboard navigation, context override, ratings (incl. the 400 range
error), dismiss + undo, deep links, Back button, player logging, behaviour
events, filters, search, retrain, sign-out and expired sessions.

    cd frontend && python3 -m http.server 8765      # in one terminal
    python3 tests/smoke_test.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
from screenshots import new_context, attach_logging, login_demo, logs, BASE

results = []
def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))

def db(page):
    return page.evaluate("JSON.parse(localStorage.getItem('cinematch_mock_db_v2'))")

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = new_context(browser)
    page = ctx.new_page(); attach_logging(page, "func")
    login_demo(page)

    # --- context chip override (FR-2.3)
    chip = page.locator(".ctx-chip")
    check("chip shows detected weather", "Rainy" in chip.inner_text(), chip.inner_text())
    chip.click(); page.wait_for_selector(".pop")
    page.locator(".pop .chip", has_text="Sunny").click()
    page.wait_for_timeout(1500)
    check("chip shows override", "Sunny" in chip.inner_text() and chip.get_attribute("data-overridden") == "true", chip.inner_text())
    title = page.locator('[data-row-id="weather"] .row__title').inner_text()
    check("weather row rebuilt for override", "sunny" in title.lower(), title)
    page.locator(".pop [data-act=reset]").click(); page.wait_for_timeout(600)
    check("override reset", "Rainy" in chip.inner_text())
    page.mouse.click(10, 500); page.wait_for_timeout(300)
    check("popover closes on outside click", page.locator(".pop").count() == 0)

    # --- keyboard navigation in a row
    first = page.locator('[data-row-id="for_you"] .card__hit').first
    first.focus()
    page.keyboard.press("ArrowRight")
    focused_label = page.evaluate("document.activeElement.getAttribute('aria-label')")
    second_label = page.locator('[data-row-id="for_you"] .card__hit').nth(1).get_attribute("aria-label")
    check("arrow key moves focus to next card", focused_label == second_label, focused_label)
    page.keyboard.press("Enter")
    page.wait_for_selector(".modal .modal__title")
    check("enter opens details + hash", "#/movie/" in page.url, page.url)
    page.wait_for_timeout(600)
    page.keyboard.press("Escape"); page.wait_for_timeout(700)
    check("escape closes modal, back to home", page.locator(".modal").count() == 0 and page.url.endswith("#/"), page.url)

    # --- rating via keyboard in modal
    page.locator('[data-row-id="trending"] .card__hit').first.click()
    page.wait_for_selector(".modal .rating")
    mid = int(page.url.split("/movie/")[1])
    page.locator(".modal .rating").focus()
    for _ in range(3): page.keyboard.press("ArrowRight")
    page.wait_for_timeout(1200)
    r = db(page)["ratings"]["u-demo"].get(str(mid))
    check("keyboard rating saved (1.5)", r and r["rating"] == 1.5, json.dumps(r))
    # back button closes the modal
    page.go_back(); page.wait_for_timeout(700)
    check("browser Back closes modal", page.locator(".modal").count() == 0, page.url)

    # --- invalid rating -> 400 message (FR-1.2)
    msg = page.evaluate("import('./js/api.js').then(m => m.api.post('/api/ratings', {movie_id: 1, rating: 3.3})).then(() => 'no error', e => e.status + ' ' + e.detail)")
    check("invalid rating rejected with range message", msg.startswith("400 Rating must be between 0.5 and 5.0"), msg)

    # --- dismiss + undo (FR-4.5)
    page.evaluate("window.scrollTo(0, 0)"); page.wait_for_timeout(400)
    card = page.locator('[data-row-id="for_you"] .card').nth(1)
    card.scroll_into_view_if_needed(); page.wait_for_timeout(400)
    dmid = card.get_attribute("data-mid")
    before = page.locator(f'#main .card[data-mid="{dmid}"]').count()
    card.locator(".card__hit").hover(); page.wait_for_selector(".preview.is-open", timeout=4000)
    page.locator(".preview [data-act=dismiss]").click()
    page.wait_for_timeout(900)
    after = page.locator(f'#main .card[data-mid="{dmid}"]').count()
    check("dismiss removes every card of that film", before > 0 and after == 0, f"{before}->{after}")
    check("dismiss stored", int(dmid) in db(page)["dismissals"]["u-demo"])
    page.locator(".toast__action", has_text="Undo").click(); page.wait_for_timeout(800)
    check("undo restores cards", page.locator(f'#main .card[data-mid="{dmid}"]').count() == before)
    page.mouse.move(5, 5)

    # --- deep link
    page2 = ctx.new_page(); attach_logging(page2, "deeplink")
    page2.goto(BASE + "?mock=1#/movie/79132")
    page2.wait_for_selector(".modal .modal__title")
    check("deep link opens modal", "Inception" in page2.locator(".modal__title").inner_text())
    page2.wait_for_selector(".hero")
    page2.locator(".modal__close").click(); page2.wait_for_timeout(700)
    check("deep link close goes home", page2.url.endswith("#/") and page2.locator(".modal").count() == 0, page2.url)

    # --- trailer fallback + player logging (Inception has trailer_key; YouTube is blocked here)
    page2.goto(BASE + "?mock=1#/movie/79132"); page2.wait_for_selector(".modal [data-act=play]")
    page2.locator(".modal [data-act=play]").click()
    page2.wait_for_selector(".player [data-scrub]", timeout=15000)
    check("YouTube failure falls back to simulated player", page2.locator(".player [data-scrub]").count() == 1)
    page2.wait_for_timeout(1200)
    page2.keyboard.press("k"); page2.wait_for_timeout(300)
    page2.keyboard.press("ArrowRight"); page2.wait_for_timeout(300)
    page2.keyboard.press("k"); page2.wait_for_timeout(300)
    page2.keyboard.press("Escape"); page2.wait_for_timeout(1000)
    sess = [s for s in db(page2)["sessions"] if s["movie_id"] == 79132]
    last = sess[-1] if sess else {}
    check("playback session logged with pause/seek/stop", last.get("pause_count", 0) >= 1 and last.get("seek_forward_count", 0) >= 1 and last.get("drop_off_sec") is not None, json.dumps({k: last.get(k) for k in ("pause_count", "seek_forward_count", "drop_off_sec", "duration_sec", "completed")}))
    page2.close()

    # --- results: remove chip
    page.click(".nav__links [data-action=mixer]"); page.wait_for_selector(".drawer.is-open")
    page.locator(".drawer .chip", has_text="Family night").click()
    page.locator(".drawer .chip", has_text="Comedy").click()
    page.locator(".drawer [data-act=apply]").click()
    page.wait_for_selector(".results .card")
    n_chips = page.locator("[data-chips] .chip").count()
    url_before = page.url
    page.locator("[data-chips] .chip__x").last.click(); page.wait_for_timeout(1200)
    check("removing a chip re-queries", page.locator("[data-chips] .chip").count() == n_chips - 1 and page.url != url_before, f"{n_chips}")

    # --- search
    page.click(".search__btn"); page.keyboard.type("knives", delay=40); page.wait_for_timeout(1400)
    check("search results", "#/search?q=knives" in page.url and page.locator(".grid .card").count() >= 1, page.url)

    # --- browse filter
    page.goto(BASE + "?mock=1#/movies"); page.wait_for_selector(".grid .card")
    page.select_option("select[name=genre]", "Comedy"); page.wait_for_timeout(1200)
    n = page.locator(".grid .card").count()
    total = page.locator("[data-total]").inner_text()
    check("browse genre filter", "genre=Comedy" in page.url and 0 < n < 54 and str(n) in total, f"{n} {total}")

    # --- events were logged
    page.wait_for_timeout(4500)
    types = {e.get("type") for e in db(page)["events"]}
    for t in ["impression", "select", "details_open", "filter_apply", "search", "trailer_open" if False else "details_open"]:
        check(f"event logged: {t}", t in types)
    sel = [e for e in db(page)["events"] if e.get("type") == "select"]
    check("select has browse-to-select ms", sel and all(isinstance(e.get("value"), (int, float)) for e in sel), json.dumps(sel[:2]))

    # --- trailer_open event
    page.goto(BASE + "?mock=1#/movie/109487"); page.wait_for_selector(".modal [data-act=trailer]")
    page.locator(".modal [data-act=trailer]").click(); page.wait_for_timeout(800)
    page.keyboard.press("Escape"); page.wait_for_timeout(4600)
    check("event logged: trailer_open", any(e.get("type") == "trailer_open" for e in db(page)["events"]))

    # --- admin retrain
    page.goto(BASE + "?mock=1#/admin"); page.wait_for_selector(".kpi__value")
    page.locator("[data-act=retrain]").click(); page.wait_for_timeout(2500)
    check("retrain running", page.locator("[data-retrain] [data-status]").inner_text() == "Running")
    page.wait_for_timeout(8000)
    check("retrain finished", page.locator("[data-retrain] [data-status]").inner_text() == "Finished")

    # --- logout
    page.goto(BASE + "?mock=1#/"); page.wait_for_selector(".hero")
    page.locator(".usermenu .avatar").click(); page.locator("[data-action=logout]").click(); page.wait_for_timeout(800)
    check("logout -> login page", "#/login" in page.url and page.locator("#nav").is_hidden())

    # --- expired token -> login
    page.evaluate("localStorage.setItem('cinematch_token', 'mock-nobody'); localStorage.setItem('cinematch_user', JSON.stringify({display_name:'X'}))")
    page.goto(BASE + "?mock=1#/profile"); page.wait_for_timeout(2000)
    check("401 sends you to sign in", "#/login" in page.url, page.url)

    # --- register validation + onboarding redirect
    page.goto(BASE + "?mock=1#/register"); page.wait_for_selector("#auth-name")
    page.fill("#auth-name", "T"); page.fill("#auth-email", "bad"); page.fill("#auth-password", "123")
    page.click("button[type=submit]")
    check("register validation message", "valid email" in page.locator(".form-error").inner_text())

    browser.close()

print("----")
print(sum(1 for r in results if r[1]), "/", len(results), "passed")
for l in logs: print(l)
sys.exit(0 if all(r[1] for r in results) else 1)

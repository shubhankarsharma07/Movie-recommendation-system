"""
CineMatch frontend — screenshot tour (mock mode, no backend needed).

    cd frontend
    python3 -m http.server 8765            # in one terminal
    pip install playwright && playwright install chromium   # once
    python3 tests/screenshots.py           # all scenes  -> screenshots/
    python3 tests/screenshots.py home mixer   # just some scenes

Env vars:
    BASE          site URL (default http://127.0.0.1:8765/)
    OUT           output folder (default ../screenshots next to this file)
    LOCAL_ASSETS  optional folder with fonts.css + font files + chart.umd.js, for
                  machines without internet (Google Fonts / cdnjs are then served
                  locally). Without it, everything loads from the real CDNs.
"""
import os, sys, glob, time
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("OUT", os.path.join(HERE, "..", "screenshots"))
BASE = os.environ.get("BASE", "http://127.0.0.1:8765/")
ASSETS = os.environ.get("LOCAL_ASSETS")
FONT_FILES, FONT_CSS, CHART_JS = {}, None, None
if ASSETS:
    for f in glob.glob(os.path.join(ASSETS, "**/*.woff2"), recursive=True):
        FONT_FILES[os.path.basename(f)] = f
    FONT_CSS = open(os.path.join(ASSETS, "fonts.css")).read()
    CHART_JS = open(glob.glob(os.path.join(ASSETS, "**/chart.umd.js"), recursive=True)[0]).read()

logs = []

def route_all(context):
    """Serve fonts / Chart.js locally when LOCAL_ASSETS is set; otherwise let everything through."""
    if not ASSETS:
        return
    def handler(route):
        url = route.request.url
        if "fonts.googleapis.com" in url:
            return route.fulfill(status=200, content_type="text/css", body=FONT_CSS)
        if "fonts.gstatic.com/local/" in url:
            name = url.rsplit("/", 1)[-1]
            if name in FONT_FILES:
                return route.fulfill(status=200, content_type="font/woff2", body=open(FONT_FILES[name], "rb").read(),
                                     headers={"Access-Control-Allow-Origin": "*"})
            return route.abort()
        if "cdnjs.cloudflare.com" in url and "Chart.js" in url:
            return route.fulfill(status=200, content_type="application/javascript", body=CHART_JS)
        if url.startswith(BASE):
            return route.continue_()
        return route.abort()  # offline: YouTube / TMDB fall back to generated art + simulated player
    context.route("**/*", handler)

def attach_logging(page, name):
    page.on("console", lambda m: logs.append((name, m.type, m.text)) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: logs.append((name, "pageerror", str(e))))

def new_context(browser, **kw):
    opts = dict(viewport={"width": 1440, "height": 900}, device_scale_factor=1, locale="en-IN", timezone_id="Asia/Kolkata",
                geolocation={"latitude": 27.4924, "longitude": 77.6737}, permissions=["geolocation"])
    opts.update(kw)
    ctx = browser.new_context(**opts)
    route_all(ctx)
    return ctx

def shot(page, name, full=False):
    path = os.path.join(OUT, name)
    page.screenshot(path=path, full_page=full)
    print("saved", name)

def settle(page, ms=900):
    page.wait_for_timeout(ms)

def login_demo(page):
    page.goto(BASE + "?mock=1#/login")
    page.evaluate("localStorage.clear(); sessionStorage.setItem('cinematch_mock','1')")
    page.goto(BASE + "?mock=1#/login")
    page.wait_for_selector("#auth-email")
    page.fill("#auth-email", "demo@cinematch.app")
    page.fill("#auth-password", "demo1234")
    page.click("button[type=submit]")
    page.wait_for_selector(".hero", timeout=15000)
    page.wait_for_selector(".row .card")
    page.evaluate("document.fonts.ready")
    settle(page, 1500)

SCENES = {}
def scene(fn):
    SCENES[fn.__name__] = fn
    return fn

@scene
def login(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "login")
    page.goto(BASE + "?mock=1#/login")
    page.evaluate("localStorage.clear()")
    page.goto(BASE + "?mock=1#/login")
    page.wait_for_selector("#auth-email"); page.evaluate("document.fonts.ready"); settle(page, 2200)
    shot(page, "01-login.png")
    ctx.close()

@scene
def onboarding(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "onboarding")
    page.goto(BASE + "?mock=1#/register")
    page.evaluate("localStorage.clear()")
    page.goto(BASE + "?mock=1#/register")
    page.wait_for_selector("#auth-name")
    page.fill("#auth-name", "Meera"); page.fill("#auth-email", f"meera{int(time.time())}@example.com"); page.fill("#auth-password", "secret12")
    page.click("button[type=submit]")
    page.wait_for_selector(".onb-tile .rating")
    settle(page, 800)
    tiles = page.locator(".onb-tile .rating__stars")
    for i, frac in [(0, 0.95), (1, 0.75), (3, 0.62)]:
        box = tiles.nth(i).bounding_box()
        page.mouse.click(box["x"] + box["width"] * frac, box["y"] + box["height"] / 2)
        settle(page, 450)
    page.mouse.move(700, 600)
    page.locator(".onb-tile").nth(5).hover()
    settle(page, 1800)
    shot(page, "02-onboarding.png")
    ctx.close()

@scene
def home(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "home")
    login_demo(page)
    page.mouse.move(5, 450)
    settle(page, 2500)
    shot(page, "03-home.png")
    # hover a card in the second row
    card = page.locator(".row").nth(1).locator(".card__hit").nth(2)
    card.scroll_into_view_if_needed(); settle(page, 300)
    card.hover(); settle(page, 2600)
    shot(page, "04-home-hover.png")
    page.mouse.move(5, 300); settle(page, 300)
    page.evaluate("window.scrollTo(0, 0)")
    shot(page, "03b-home-full.png", full=True)
    ctx.close()

@scene
def mixer(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "mixer")
    login_demo(page)
    page.click(".nav__links [data-action=mixer]")
    page.wait_for_selector(".drawer.is-open"); settle(page, 700)
    d = page.locator(".drawer")
    d.locator(".chip", has_text="Date night").click()
    d.locator('[aria-label="Starting feeling"] .chip', has_text="Sad").click()
    d.locator('[aria-label="Ending feeling"] .chip', has_text="Happy").click()
    d.locator(".chip", has_text="2½ hr").click()
    settle(page, 900)
    page.locator(".drawer__body").evaluate("el => el.scrollTo(0, 360)")
    settle(page, 900)
    shot(page, "05-mixer.png")
    page.locator(".drawer__body").evaluate("el => el.scrollTo(0, 1200)")
    d.locator(".ac input").first.fill("inter")
    settle(page, 900)
    shot(page, "05b-mixer-like.png")
    page.keyboard.press("Enter"); settle(page, 300)
    d.locator("[data-act=apply]").click()
    page.wait_for_selector(".results .card"); page.mouse.move(700, 150); settle(page, 2200)
    shot(page, "06-results.png")
    # details modal
    page.locator(".results .card__hit").first.click()
    page.wait_for_selector(".modal .modal__title"); settle(page, 2200)
    shot(page, "07-details.png")
    page.locator(".modal-scrim").evaluate("el => el.scrollTo(0, 99999)"); settle(page, 800)
    shot(page, "07b-details-more.png")
    page.locator(".modal-scrim").evaluate("el => el.scrollTo(0, 0)"); settle(page, 300)
    page.locator(".modal [data-act=play]").click()
    page.wait_for_selector(".player.is-open"); settle(page, 1200)
    page.mouse.move(700, 500); settle(page, 1800)
    shot(page, "08-player.png")
    page.keyboard.press("Escape"); settle(page, 500)
    ctx.close()

@scene
def series(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "series")
    login_demo(page)
    page.goto(BASE + "?mock=1#/movie/10101352")
    page.wait_for_selector(".modal [data-act=play]"); settle(page, 1200)
    page.locator(".modal [data-act=play]").click()
    page.wait_for_selector(".player.is-open"); settle(page, 800)
    page.locator("[data-scrub]").evaluate("el => { el.value = el.max - 30; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
    settle(page, 2500)
    page.mouse.move(600, 400)
    shot(page, "08b-player-next-episode.png")
    ctx.close()

@scene
def party(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "party")
    login_demo(page)
    page.goto(BASE + "?mock=1#/party"); page.wait_for_selector("[data-add] input"); settle(page, 800)
    for e in ["aman@example.com", "riya@example.com"]:
        page.fill("[data-add] input", e); page.click("[data-add] button")
    settle(page, 600)
    shot(page, "09a-party-lobby.png")
    page.click("[data-act=create]")
    page.wait_for_selector(".party-room__body .card"); settle(page, 2200)
    shot(page, "09-party.png")
    ctx.close()

@scene
def profile(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "profile")
    login_demo(page)
    page.goto(BASE + "?mock=1#/profile"); page.wait_for_selector(".bar"); settle(page, 2000)
    shot(page, "10-profile.png")
    shot(page, "10b-profile-full.png", full=True)
    ctx.close()

@scene
def admin(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "admin")
    login_demo(page)
    page.goto(BASE + "?mock=1#/admin"); page.wait_for_selector(".kpi__value"); settle(page, 2500)
    shot(page, "11-admin.png")
    shot(page, "11b-admin-full.png", full=True)
    ctx.close()

@scene
def browse(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "browse")
    login_demo(page)
    page.goto(BASE + "?mock=1#/movies"); page.wait_for_selector(".grid .card"); settle(page, 1500)
    shot(page, "14-browse.png")
    page.click(".search__btn"); page.keyboard.type("the", delay=60)
    page.wait_for_selector(".grid .card"); settle(page, 1500)
    shot(page, "15-search.png")
    ctx.close()

@scene
def mobile(browser):
    ctx = new_context(browser, viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    page = ctx.new_page(); attach_logging(page, "mobile")
    login_demo(page)
    settle(page, 1500)
    shot(page, "12-mobile-home.png")
    page.evaluate("window.scrollTo(0, 700)"); settle(page, 800)
    shot(page, "12b-mobile-rows.png")
    page.locator(".row .card__hit").nth(3).tap()
    page.wait_for_selector(".modal .modal__title"); settle(page, 1800)
    shot(page, "12c-mobile-details.png")
    page.keyboard.press("Escape"); settle(page, 600)
    page.locator(".tabbar [data-action=mixer]").tap(); settle(page, 1200)
    shot(page, "12d-mobile-mixer.png")
    ctx.close()

@scene
def context(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "context")
    login_demo(page)
    page.mouse.move(5, 450)
    page.click(".ctx-chip"); page.wait_for_selector(".pop .chip"); settle(page, 900)
    shot(page, "16-context-override.png")
    ctx.close()

@scene
def waking(browser):
    ctx = new_context(browser); page = ctx.new_page(); attach_logging(page, "waking")
    login_demo(page)
    page.goto(BASE + "?mock=1&cold=1#/profile")
    page.reload()
    page.wait_for_selector(".wake.is-open", timeout=8000); settle(page, 1200)
    shot(page, "13-waking-server.png")
    page.wait_for_selector(".wake", state="hidden", timeout=20000)
    ctx.close()

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    wanted = sys.argv[1:] or list(SCENES)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in wanted:
            try:
                SCENES[name](browser)
            except Exception as e:
                print("SCENE FAILED", name, repr(e)[:400])
        browser.close()
    print("---- console ----")
    for l in logs:
        print(l)
    print("total", len(logs))

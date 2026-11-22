"""Shared IEEE SSO login for tableau_export.py and vtools_export.py.

With IEEE_EMAIL and IEEE_PASSWORD in the environment (e.g. exported from a
git-ignored .envrc), the SSO form is filled in automatically; otherwise (or
if MFA/captcha shows up) the user finishes in the browser window.
"""

import os


def sso_login(page, url: str, done_host: str) -> None:
    """Open url, sign in through IEEE SSO, and return once back on done_host."""
    page.goto(url)
    email, password = os.environ.get("IEEE_EMAIL"), os.environ.get("IEEE_PASSWORD")
    if not (email and password):
        print("Complete the IEEE SSO login in the browser window, then press Enter here...")
        input()
        return
    page.wait_for_selector("#username", timeout=60_000)
    page.fill("#username", email)
    page.fill("#password", password)
    page.click("#modalWindowRegisterSignInBtn")
    try:
        # Generous timeout so a manual MFA step, if any, can still be finished.
        page.wait_for_url(lambda u: done_host in u and "services10.ieee.org" not in u, timeout=180_000)
        page.wait_for_load_state("networkidle")
    except Exception:
        print("Automatic login did not finish (wrong credentials or extra step?). "
              "Finish it in the browser window, then press Enter here...")
        input()

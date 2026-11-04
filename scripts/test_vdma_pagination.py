from playwright.sync_api import sync_playwright

URL = "https://www.vdma.eu/de/mitglieder-landtechnik"

with sync_playwright() as p:

    browser = p.chromium.launch(headless=False)

    page = browser.new_page()

    page.goto(URL, wait_until="domcontentloaded")

    page.locator(
        ".association-member"
    ).first.wait_for(timeout=30000)

    for attempt in range(1, 4):

        current = page.locator(
            ".vdma-pagination-page.active"
        ).get_attribute("data-page")

        first_company = page.locator(
            ".association-member__title"
        ).first.inner_text()

        print(
            f"Before click {attempt}:",
            current,
            first_company
        )

        page.locator(
            ".vdma-pagination-right"
        ).click()

        # Give the page a chance to finish its update.
        page.wait_for_timeout(3000)

        new_page = page.locator(
            ".vdma-pagination-page.active"
        ).get_attribute("data-page")

        new_company = page.locator(
            ".association-member__title"
        ).first.inner_text()

        print(
            f"After click {attempt}:",
            new_page,
            new_company
        )

    browser.close()
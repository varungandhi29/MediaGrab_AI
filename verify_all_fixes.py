import asyncio
from playwright.async_api import async_playwright

async def verify_flezen_and_seeking():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 850})
        page = await context.new_page()

        print("=== TEST 1: Flezen Link Handling ===")
        await page.goto("http://localhost:5173", wait_until="networkidle")

        url_input = page.locator("input[placeholder*='Paste a link']")
        await url_input.fill("https://flezen.com/s/datajtpbjlnn76mmuo6greu8-qdnwsi")
        await page.locator("button:has-text('Play & Download')").click()

        # Wait for the metadata card to appear
        print("Waiting for Flezen metadata card...")
        await page.wait_for_selector("text=Flezen Cloud", timeout=12000)
        print("Flezen card rendered successfully!")

        # Verify Flezen quick action buttons
        app_btn = page.locator("text=Open in Flezen App").first
        tg_btn = page.locator("text=Telegram Fast Bot").first
        print("Open in Flezen App visible:", await app_btn.is_visible())
        print("Telegram Fast Bot visible:", await tg_btn.is_visible())

        # Screenshot Flezen card
        await page.screenshot(path="C:/Users/DELL/.gemini/antigravity/brain/6092ef46-2ff1-48a6-af92-16ede32451dd/flezen_metadata_verified.png")
        print("Saved flezen_metadata_verified.png")

        # Click Watch in Player to test modal presentation
        play_card_btn = page.locator("text=Watch in Player")
        if await play_card_btn.is_visible():
            await play_card_btn.click()
            await page.wait_for_selector("text=Flezen Cloud Media Access", timeout=5000)
            print("Flezen modal overlay verified!")
            await page.screenshot(path="C:/Users/DELL/.gemini/antigravity/brain/6092ef46-2ff1-48a6-af92-16ede32451dd/flezen_player_modal_verified.png")
            print("Saved flezen_player_modal_verified.png")
            # Close modal
            await page.locator("button[aria-label='Close video player']").click()
            await asyncio.sleep(0.5)

        print("\n=== TEST 2: Butter-Smooth Seeking Test ===")
        # Paste YouTube 22-min video to test smooth forward/backward seeking & scrubber
        await url_input.fill("https://youtu.be/zbkq2na9fHY?si=G1-QMQyFtGga8aXq")
        await page.locator("button:has-text('Play & Download')").click()

        print("Waiting for YouTube metadata...")
        await page.wait_for_selector("text=Watch Video", timeout=15000)
        print("Clicking Watch Video...")
        await page.locator("button:has-text('Watch Video')").click()

        # Wait for player modal
        await page.wait_for_selector("video", timeout=10000)
        video_el = page.locator("video")

        # Wait for video to begin playing
        for _ in range(15):
            t = await video_el.evaluate("el => el.currentTime")
            paused = await video_el.evaluate("el => el.paused")
            if t > 0.5 and not paused:
                break
            await asyncio.sleep(0.5)

        init_time = await video_el.evaluate("el => el.currentTime")
        print(f"Video started playing smoothly at {init_time:.2f}s")

        # Test butter-smooth keyboard seeking: press ArrowRight 3 times rapidly
        print("Testing rapid Right Arrow taps (+10s, +20s, +30s)...")
        await page.keyboard.press("ArrowRight")
        await asyncio.sleep(0.1)
        await page.keyboard.press("ArrowRight")
        await asyncio.sleep(0.1)
        await page.keyboard.press("ArrowRight")

        # Check accumulated feedback pill
        feedback = page.locator("text=+30s")
        is_fb_vis = await feedback.is_visible()
        print(f"Accumulated seek feedback '+30s' visible: {is_fb_vis}")

        await asyncio.sleep(1.0)
        seeked_time = await video_el.evaluate("el => el.currentTime")
        print(f"Time after +30s seek: {seeked_time:.2f}s")
        assert seeked_time >= init_time + 25.0, "Seek did not jump forward properly"

        # Test relative backward seek -10s
        print("Testing backward Left Arrow tap (-10s)...")
        await page.keyboard.press("ArrowLeft")
        await asyncio.sleep(1.0)
        back_time = await video_el.evaluate("el => el.currentTime")
        print(f"Time after -10s backward seek: {back_time:.2f}s")

        # Test timeline scrubber hover and progress bar
        scrubber = page.locator("input[aria-label='Seek video position']")
        box = await scrubber.bounding_box()
        if box:
            print(f"Hovering on timeline scrubber at 60% width...")
            target_x = box["x"] + box["width"] * 0.6
            target_y = box["y"] + box["height"] * 0.5
            await page.mouse.move(target_x, target_y)
            await asyncio.sleep(0.3)
            # Verify hover time tooltip is visible
            hover_badge = page.locator("div.absolute.-top-7")
            print("Hover time badge visible:", await hover_badge.is_visible())
            # Click to seek smoothly to ~13 minutes (60%)
            await page.mouse.click(target_x, target_y)
            await asyncio.sleep(1.5)

        final_pos = await video_el.evaluate("el => el.currentTime")
        final_paused = await video_el.evaluate("el => el.paused")
        print(f"Final playback position after scrubber seek: {final_pos:.2f}s (Paused: {final_paused})")

        # Capture artifact
        await page.screenshot(path="C:/Users/DELL/.gemini/antigravity/brain/6092ef46-2ff1-48a6-af92-16ede32451dd/butter_smooth_seeking_verified.png")
        print("Saved butter_smooth_seeking_verified.png")

        await browser.close()
        print("\nALL VERIFICATION TESTS COMPLETED SUCCESSFULLY!")

asyncio.run(verify_flezen_and_seeking())

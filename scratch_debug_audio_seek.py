import asyncio
from playwright.async_api import async_playwright

async def debug_audio_seek():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Listen to all console messages and page errors
        page.on("console", lambda m: print(f"CONSOLE [{m.type}]:", m.text))
        page.on("pageerror", lambda e: print("PAGEERROR:", e))

        await page.goto("http://localhost:5173", wait_until="networkidle")

        url_input = page.locator("input[placeholder*='Paste a link']")
        await url_input.fill("https://youtu.be/zbkq2na9fHY?si=G1-QMQyFtGga8aXq")
        await page.locator("button:has-text('Play & Download')").click()

        print("Waiting for Watch Video button...")
        await page.wait_for_selector("text=Watch Video", timeout=15000)
        await page.locator("button:has-text('Watch Video')").click()

        # Wait for video element
        await page.wait_for_selector("video", timeout=10000)
        await asyncio.sleep(2.0)

        # Inspect video and audio elements before seek
        status_before = await page.evaluate("""() => {
            const v = document.querySelector('video');
            const a = document.querySelector('audio');
            return {
                video: {
                    src: v ? v.src : null,
                    currentTime: v ? v.currentTime : null,
                    paused: v ? v.paused : null,
                    muted: v ? v.muted : null,
                    volume: v ? v.volume : null,
                    readyState: v ? v.readyState : null,
                },
                audio: a ? {
                    src: a.src,
                    currentTime: a.currentTime,
                    paused: a.paused,
                    muted: a.muted,
                    volume: a.volume,
                    readyState: a.readyState,
                    error: a.error ? a.error.message : null,
                    buffered: a.buffered.length > 0 ? [a.buffered.start(0), a.buffered.end(0)] : []
                } : null
            };
        }""")
        print("STATUS BEFORE SEEK:")
        import pprint
        pprint.pprint(status_before)

        # Attach event listeners to audio and video to log everything
        await page.evaluate("""() => {
            const v = document.querySelector('video');
            const a = document.querySelector('audio');
            if (a) {
                ['play', 'playing', 'pause', 'seeking', 'seeked', 'waiting', 'stalled', 'error', 'ended', 'timeupdate'].forEach(evt => {
                    a.addEventListener(evt, () => {
                        if (evt !== 'timeupdate') {
                            console.log(`[AUDIO_EVENT] ${evt} - currentTime=${a.currentTime}, paused=${a.paused}, readyState=${a.readyState}`);
                        }
                    });
                });
            }
            if (v) {
                ['seeking', 'seeked', 'pause', 'play', 'waiting', 'playing'].forEach(evt => {
                    v.addEventListener(evt, () => {
                        console.log(`[VIDEO_EVENT] ${evt} - currentTime=${v.currentTime}, paused=${v.paused}`);
                    });
                });
            }
        }""")

        # Now trigger forward seek (+10s)
        print("\n--- PRESSING ArrowRight (+10s) ---")
        await page.keyboard.press("ArrowRight")
        await asyncio.sleep(1.5)

        status_after_1 = await page.evaluate("""() => {
            const v = document.querySelector('video');
            const a = document.querySelector('audio');
            return {
                video: {
                    currentTime: v ? v.currentTime : null,
                    paused: v ? v.paused : null,
                },
                audio: a ? {
                    currentTime: a.currentTime,
                    paused: a.paused,
                    readyState: a.readyState,
                    error: a.error ? a.error.message : null,
                    buffered: a.buffered.length > 0 ? [a.buffered.start(0), a.buffered.end(0)] : []
                } : null
            };
        }""")
        print("\nSTATUS AFTER +10s SEEK:")
        pprint.pprint(status_after_1)

        # Wait another 2 seconds and check if audio is playing or paused
        await asyncio.sleep(2.0)
        status_after_wait = await page.evaluate("""() => {
            const v = document.querySelector('video');
            const a = document.querySelector('audio');
            return {
                video: {
                    currentTime: v ? v.currentTime : null,
                    paused: v ? v.paused : null,
                },
                audio: a ? {
                    currentTime: a.currentTime,
                    paused: a.paused,
                    readyState: a.readyState,
                    error: a.error ? a.error.message : null,
                } : null
            };
        }""")
        print("\nSTATUS AFTER WAITING 2 SECONDS:")
        pprint.pprint(status_after_wait)

        # Now trigger backward seek (-10s)
        print("\n--- PRESSING ArrowLeft (-10s) ---")
        await page.keyboard.press("ArrowLeft")
        await asyncio.sleep(2.0)

        status_after_back = await page.evaluate("""() => {
            const v = document.querySelector('video');
            const a = document.querySelector('audio');
            return {
                video: {
                    currentTime: v ? v.currentTime : null,
                    paused: v ? v.paused : null,
                },
                audio: a ? {
                    currentTime: a.currentTime,
                    paused: a.paused,
                    readyState: a.readyState,
                    error: a.error ? a.error.message : null,
                } : null
            };
        }""")
        print("\nSTATUS AFTER -10s SEEK:")
        pprint.pprint(status_after_back)

        await browser.close()

asyncio.run(debug_audio_seek())

# Deal Hunter Bot — Implementation Changes

Last updated: 1 September 2026

This document records the implemented fixes and the current production flow. It is intended to be kept in Git with the source code. Generated screenshots, media frames, local databases, sessions, logs, and secrets are excluded through `.gitignore`.

## 1. Current posting result

Every deal post now uses a strict professional two-photo album:

1. Product frame — actual high-resolution product image and cleaned product title.
2. Price-proof frame — a live Flipkart price snapshot plus verified price, MRP, discount, rating, product thumbnail, timestamp, and price warning.

Both files are RGB JPEG images with identical `1080 × 1350` dimensions. Telegram receives them in one `sendMediaGroup` request. The caption is attached only to the first photo.

The production posting path does not silently downgrade to one photo. If both valid frames are unavailable, or Telegram does not return exactly two media messages, the deal is not marked as sent.

Telegram controls the final layout in each client. Sending exactly two equal-sized images in one media group is the supported way to produce the symmetric side-by-side album grid.

## 2. End-to-end flow

```text
Scheduled / flash / instant product selection
        ↓
Product-page deep verification
        ↓
Current product title, image, price, MRP, discount and rating
        ↓
Live price-block screenshot at 2× device scale
        ↓
ExtraPe affiliate-link request
        ↓
Fallback affiliate parameters if ExtraPe does not return a usable URL
        ↓
Caption with the visible direct affiliate URL
        ↓
Build two matching 1080×1350 frames
        ↓
Telegram sendMediaGroup with exactly two local attachments
        ↓
Verify Telegram response contains exactly two messages
        ↓
Save sent-deal record only after successful delivery
        ↓
Clean temporary screenshot and frame files after all channels finish
```

For multiple configured channels, the frames are built once, cached on the in-memory deal object, reused for every channel, and removed only after all channel attempts finish.

## 3. Professional media frames

Implemented in `telegram/media_frames.py`.

### Product frame

- Canvas: `1080 × 1350`, portrait.
- Uses the full-quality Flipkart CDN rendition instead of the old small thumbnail.
- Product is contained inside a rounded white product card without stretching.
- Displays a cleaned two-line product title.
- Uses matching Deal Hunter branding, spacing, borders, colors, and typography.

### Price-proof frame

- Canvas: `1080 × 1350`, matching the product frame.
- Top card contains the real Flipkart product-price block as a receipt-style snapshot.
- Bottom card contains product thumbnail, verified price, MRP, discount, title, rating, verification time, and a live-price warning.
- The screenshot is contained without cropping price/title edges or distorting its aspect ratio.
- Wide proof strips use a compact intentional layout instead of leaving an oversized blank panel.

Frame generation requires Pillow. `Pillow>=10.0` is included in `requirements.txt`.

## 4. Price screenshot and data-integrity fixes

Implemented mainly in `scraper/price_screenshot.py` and `scraper/flipkart.py`.

- Screenshots use `device_scale_factor=2` for sharper Telegram rendering.
- Semantic price detection runs before legacy CSS selector fallbacks.
- Elements appearing after the `Similar Products` heading are excluded.
- Product-page controls such as `Hot Deal`, discount, current price, minimum order quantity, and buy/apply-offer context help identify the primary price block.
- Legacy selectors are accepted only when they occur before `Similar Products`.
- The final price-centered fallback can use the expected product price rather than selecting any rupee value.
- Product JSON-LD is located recursively and unrelated Review/Offer JSON objects are ignored.
- Product title, image, price, and aggregate rating use the Product schema when available.
- MRP and discount are extracted from the same visible block as the current product price.
- The previous page-wide maximum-price logic was removed because it could take MRP or discount from a similar product.
- Scheduled keyword deals are enriched with product-page title, price, MRP, discount, image, and rating before scoring and queueing.
- Repeated marketplace title phrases are collapsed for cleaner frames and captions.

Example of the fixed contamination case:

```text
Target product: 86% / MRP ₹999 / price ₹135
Similar product: 88% / MRP ₹2,999 / price ₹359
```

Only the target product values are now used in the proof and verified card.

## 5. Telegram album guarantees

Implemented in `telegram/bot.py` and `telegram/deal_media.py`.

- Both professional frames are uploaded as local files in one `sendMediaGroup` call.
- Attachment names are `product_frame` and `price_frame`.
- A successful album response must contain exactly two Telegram result messages.
- A partial result or rejected media group returns failure.
- The strict path does not fall back to two separate messages, one photo, or text-only delivery.
- Failed delivery is not written to the sent-deals table, allowing a later scrape to retry it.
- The legacy dashboard screenshot toggle has been converted to `ALWAYS ON` because the required production format is always two photos.

## 6. Affiliate-link and caption changes

Implemented in `main.py`, `dashboard/app.py`, `telegram/post_format.py`, and `userbot/extrape_agent.py`.

- ExtraPe is called through a thread-safe synchronous wrapper around its asynchronous Telegram client.
- Replies are checked for usable URLs in both message text and inline buttons.
- Timeout, missing authorization, missing configuration, and connection failures use the configured affiliate-parameter fallback.
- Fallback query parameters are built with URL parsing and encoding; the invalid old `&&affid` form is not emitted.
- The caption shows the actual affiliate URL directly.
- The old `OPEN DEAL ON FLIPKART` anchor text is removed.
- Existing Telegram posts are not retroactively edited; the new caption applies after bot restart.

## 7. Rating fixes

- Product `aggregateRating.ratingValue` and `ratingCount` are preferred.
- Rating histograms and individual review ratings are not mistaken for the product rating.
- Compact counts such as K/M/B are normalized.
- The professional frame uses a font-safe `x / 5` label to avoid missing star-glyph squares.

## 8. Smart keyword selection

Implemented in `analyzer/keyword_selector.py` and integrated into the main round flow.

Keyword selection now considers:

- configured category priority;
- historical attempts and deals found;
- Bayesian-smoothed expected yield;
- exploration bonus for under-tested keywords;
- time since the keyword was last selected;
- category diversity within the same round;
- small random jitter so equal keywords do not remain in a permanent order.

Keyword attempt/yield state is persisted and recovered, so future rounds learn from previous results.

## 9. Queue, priority, flash and instant-post behavior

- A bounded `PriorityQueue` prevents unlimited memory growth.
- Lower numeric priority is consumed first; flash/high-priority deals can move ahead of normal deals.
- Timestamp ordering keeps equal-priority items stable.
- The consumer processes affiliate conversion and Telegram posting sequentially to prevent uncontrolled channel bursts.
- `QUEUE_DELAY_POST` controls the delay between completed deal attempts.
- Flash detection uses adaptive polling, cooldown persistence, incremental checks, and limited parallel workers.
- Dashboard Instant Post follows the same affiliate, professional-frame, strict-album, success-recording, and cleanup path as scheduled posts.

## 10. Dashboard and login changes

- Dashboard sessions use `FLASK_SECRET_KEY`; a temporary key warning remains when it is not configured.
- The settings page clearly shows that the professional two-photo album is always enabled.
- `reset_dashboard_login.py` safely changes both the dashboard login ID and password without manual SQLite commands or Python REPL indentation.

Reset command:

```powershell
cd C:\Users\hp\OneDrive\Desktop\Telegram_BOt_2\deal-hunter-bot
python reset_dashboard_login.py
```

Restart the dashboard after a login reset so old sessions are cleared.

## 11. Browser and CDN reliability

- Playwright contexts support 2× device scaling and optional HTTPS-error handling.
- When Playwright's bundled Chromium is absent, installed Google Chrome or Microsoft Edge is used as a safe fallback.
- Flipkart image download supports both current CDN hostname variants, including `rukminim...flixcart.com` and `rukmini...flixcart.com`.
- The HTTPS-tolerant image fallback is restricted to Flipkart CDN hosts; arbitrary hosts are not allowed through it.
- Image payloads are size-limited and decoded as images before use.

## 12. Main files changed

| File | Responsibility |
|---|---|
| `telegram/media_frames.py` | Builds and cleans the matching product and price frames. |
| `telegram/deal_media.py` | Enforces mandatory two-frame preparation and reuses frames across channels. |
| `telegram/bot.py` | Sends/validates the exact two-photo Telegram media group. |
| `telegram/post_format.py` | Builds captions with the visible direct affiliate URL. |
| `scraper/price_screenshot.py` | Captures the correct live product-price area at high resolution. |
| `scraper/flipkart.py` | Product schema, rating, price/MRP/discount verification and title cleanup. |
| `scraper/browser_pool.py` | Per-thread browser contexts and installed-browser fallback. |
| `analyzer/keyword_selector.py` | Adaptive, diverse keyword selection and learning. |
| `userbot/extrape_agent.py` | Thread-safe ExtraPe Telegram interaction and URL extraction. |
| `main.py` | Queue, priority, flash, affiliate and strict posting orchestration. |
| `dashboard/app.py` | Instant Post and settings integration. |
| `dashboard/templates/settings.html` | Always-on professional album status. |
| `database/db_manager.py` | Settings, login, state and keyword-stat persistence. |
| `reset_dashboard_login.py` | Safe local dashboard credential reset. |
| `requirements.txt` | Includes frame-generation and runtime dependencies. |

## 13. Tests and verification

Added or extended tests cover:

- matching `1080 × 1350` media frames;
- direct affiliate URL and removal of old anchor text;
- exact two-file Telegram media group;
- rejection of partial one-message album results;
- Product JSON-LD selection;
- aggregate rating extraction;
- repeated-title cleanup;
- MRP/discount isolation from similar products;
- smart keyword scoring, diversity, and history;
- parser, fake-drop, database, selector, and ExtraPe behavior.

The latest media/caption and product-data test groups passed, and the changed Python source completed compilation checks. A real Telegram dummy post was intentionally not sent to the production channel.

Run locally:

```powershell
cd C:\Users\hp\OneDrive\Desktop\Telegram_BOt_2\deal-hunter-bot
python -m pip install -r requirements.txt
python -m pytest -q
```

## 14. Start and restart

```powershell
cd C:\Users\hp\OneDrive\Desktop\Telegram_BOt_2\deal-hunter-bot
python -m pip install -r requirements.txt
python main.py
```

Stop a running copy with `Ctrl+C` before restarting. Code and caption changes affect only newly generated posts.

## 15. Troubleshooting

### Only one photo appears

Restart the bot and check logs for `Professional 2-photo album sent`. The current strict path does not mark a one-photo result successful. If frame generation fails, verify Pillow is installed and the product image/Flipkart page is reachable.

### Wrong product price appears in proof

The current detector excludes `Similar Products` and binds MRP/discount to the current price. If Flipkart changes its page structure, preserve this rule when updating selectors: a generic first-price or page-wide maximum must not be used.

### ExtraPe does not return a short URL

Verify API ID/hash, Telegram userbot authorization, and the ExtraPe session. The system will use the configured affiliate-parameter URL fallback rather than hiding the failure behind a non-affiliate link.

### Browser executable missing

Install Chrome/Edge or run:

```powershell
python -m playwright install chromium
```

### Dashboard login fails

Run `python reset_dashboard_login.py`, restart `main.py`, and log in with the newly entered ID and password.

## 16. Git hygiene and sensitive files

The following must remain uncommitted:

- `.env` and environment-specific variants;
- `database/bot_data.db`;
- Telegram/ExtraPe session files;
- logs;
- virtual environments;
- screenshots and generated media frames;
- test/browser reports and caches;
- generated `output/` previews or PDFs;
- temporary QA files.

`.env.example`, source files, tests, and this document remain trackable.

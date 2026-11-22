# Hawk logo with a sale tag

Approved 2026-11-22. A small change.

## Why

The app was renamed from Irtokarkki to Tarjoushaukka ("sale hawk") and now follows the owner's whole shopping list, not just pick-and-mix. The old logo, three pick-and-mix candies, no longer says what the app is. A hawk holding a sale tag says "hunts down sales".

## Goals

- Replace the candy logo in the header (next to the "Tarjoushaukka" wordmark) and the browser-tab icon with the hawk.
- Recognisable at header size (32 px) and in the browser tab (16 px), in light and dark mode.

## Non-goals

- No change to the colours, the wordmark, or anything else on the page.
- No separate image files or app icons (none exist today).

## The logo (chosen in the browser mockups)

The hawk head in profile facing right (option A of three: head, soaring hawk, hawk eye), with a plain raspberry price tag clenched in its beak (option 1 of two: plain tag, tag with %).

- Head: plum (`--ink`), light in dark mode so it stays visible.
- Beak: hooked, lemon `#FFD84A`, drawn over the top of the tag so the tag looks held.
- Eye: white with a plum ring and pupil. Brow: raspberry `#D91A5B`.
- Tag: raspberry, with a hole in the paper colour, hanging down to the right at about 30°.
- The hawk is drawn at 88% so the tag fits inside the 32×32 box.

The SVG paths are the ones in the approved mockup (`.superpowers/brainstorm/.../hawk-tag.html`, option `plain`).

## Approaches

1. **Inline SVG in the page (chosen).** Same as the current logo: no extra request, and the head can follow the page's dark mode through `--ink`.
2. A separate SVG or PNG file: an extra request, and a file can't follow the page's colour scheme. Rejected.

## Motion (Claude's proposal, approved)

- On page load the hawk drops in, and the tag swings in just after (like the candies' staggered drop today).
- While a check runs (`.logo.busy`), the tag sways gently back and forth around its top point instead of the candies bobbing.
- With reduced motion turned on, nothing moves (the existing `prefers-reduced-motion` rule).

## Browser-tab icon

The same drawing as a data-URI SVG in fixed light-mode colours, since a favicon can't follow the page's dark mode.

## Left to the builder

Exact animation timing and swing angle, as long as it stays subtle.

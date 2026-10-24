# Progressive Cards and Studio Identity

Status: completed per owner request.

- Adapt the real reference from ha_app: cards close to scroll, smooth entrance,
  and rubber-band response, preserving native video controls and Back gesture.
- Materialize block contents progressively, preserving position, drafts,
  focus, and state across navigation. Opening, scrolling, and navigating back do not trigger generation.
- Dedicated teal/turquoise palette: background #0b191e, surface #132b33,
  accent #75ddd0, text #edf8f8, secondary #a5bbc0, error #ffb7b0.
- Preserve current fonts, hierarchy, and components. Card entrance is the signature
  motion; avoid displacing media or controls and respect reduced-motion.
- Test long lists, state updates, navigation, requests, and reduced motion.
  Validate in browser using mocks; production remains on stable version.

## Evidence

- 305 frontend tests passed, including 200-card list, 80-version
  history, fallback without IntersectionObserver, draft preservation, focus,
  cross-script navigation, and motion guards.
- Fixed premature scroll restoration in ViewTransition: position is
  restored after destination paint, without waiting for animation end.
- Mocked desktop browser 1280×900, DPR 1, touch 0: 50 lightweight shells, 2 initial
  complete cards, no history mounted in advance; 5 complete cards
  after jumping to bottom. Settings/Back preserved identical DOM and scroll 18657px.
  Normal and reduced motion passed, without JS errors or mutation requests.
- Captures inspected in `.dumps/tests/lazy-ui/`; does not constitute proof of fluidity on
  physical device. No real calls to Grok/GPU for this validation.
- Calculated contrast: secondary text/card 6.54:1; primary button 8.99:1.
- Following PC reset, stable server bf7305a restarted by agent on port 8888;
  no request was automatically resent.

"""Host/LLM client error classifier — GEP signal attribution guard (#571).

Behaviour-equivalent port of ``evolver/src/gep/hostErrorClassifier.js``.

An unrecoverable host/LLM 4xx error (malformed request / auth / quota) must
NOT be attributed to a Gene: it does not feed the consecutive-failure streak
or ``ban_gene`` / ``failure_loop_detected``. ``signals.py`` surfaces the
actionable ``host_llm_client_error`` signal instead.
"""

from __future__ import annotations

import re

# Stateless (non-global) on purpose. The Node contract asserts
# ``HOST_PROVIDER_ERR_RE.global === false``: a global regex would leak
# ``lastIndex`` between calls and disagree on repeated matches. Python's
# ``re`` has no global flag, so ``re.search`` is stateless by construction.
#
# The patterns carry enough context (``HTTP``/``status code``/``Forbidden``)
# to avoid colliding with bare numbers such as "refactor touched 400 lines".
HOST_PROVIDER_ERR_RE = re.compile(
    r"invalid_api_key"
    r"|insufficient[_\s]quota"
    r"|rate[_\s]limit(?:ed)?"
    r"|max_?tokens"
    r"|http\s+\d{3}"
    r"|status\s+code:?\s*\d{3}"
    r"|\b(?:40[0-3]|429)\s+(?:forbidden|unauthorized|too\s+many\s+requests)",
    re.IGNORECASE,
)


def is_host_client_error(text: object) -> bool:
    """Return True if *text* looks like an unrecoverable host/LLM 4xx error.

    Accepts ``None``/non-str/empty gracefully (returns ``False``), matching
    the Node ``isHostClientError`` contract.
    """
    if not isinstance(text, str) or not text:
        return False
    return HOST_PROVIDER_ERR_RE.search(text) is not None

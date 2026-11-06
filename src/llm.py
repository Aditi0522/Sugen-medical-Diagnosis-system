import json, os, re, threading, time

_lock = threading.Lock()
_clients = {}
_dead = set()        # providers switched off for this run (no credits, bad key, unknown model)
_NO_TEMP = set()     # "provider:model" pairs that rejected the temperature argument

USAGE = {"in": 0, "out": 0, "calls": 0, "rate_waits": 0}


def _note_usage(i, o):
    with _lock:
        USAGE["in"] += i or 0
        USAGE["out"] += o or 0
        USAGE["calls"] += 1

# Error texts that mean "retrying this provider is pointless": stop using it, fall back.
# NOTE: "billing" is deliberately absent: rate-limit messages link to a billing page.
_STOP = ("insufficient_quota", "no credits", "credit balance", "exceeded your current quota",
         "invalid x-api-key", "invalid_api_key", "invalid api key", "incorrect api key",
         "authentication", "permission", "not_found_error", "model_not_found",
         "does not exist or you do not have access")


def _extract_json(s):
    s = re.sub(r"<think>.*?</think>", "", s or "", flags=re.S)   # reasoning models (Qwen etc.)
    m = re.search(r"\{.*\}", s, re.S)
    return json.loads(m.group(0)) if m else None


def _client(name):
    with _lock:
        if name not in _clients:
            if name == "openai":
                from openai import OpenAI
                _clients[name] = OpenAI(timeout=60, max_retries=0)
            else:
                import anthropic
                _clients[name] = anthropic.Anthropic(timeout=60, max_retries=0)
        return _clients[name]


def _openai_text(system, user, max_tokens):
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    key = f"openai:{model}"
    kw = dict(model=model, max_tokens=max_tokens, response_format={"type": "json_object"},
              messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    if os.getenv("OPENAI_REASONING_EFFORT"):            # only for reasoning models, e.g. on Groq
        kw["reasoning_effort"] = os.getenv("OPENAI_REASONING_EFFORT")
    if key not in _NO_TEMP:
        kw["temperature"] = 0
    for _ in range(3):
        try:
            r = _client("openai").chat.completions.create(**kw)
            u = getattr(r, "usage", None)
            if u:
                _note_usage(u.prompt_tokens, u.completion_tokens)
            return r.choices[0].message.content
        except Exception as e:
            s = str(e).lower()
            if "temperature" in kw and "temperature" in s:      # newer models refuse it
                _NO_TEMP.add(key); kw.pop("temperature"); continue
            if "max_tokens" in kw and "max_completion_tokens" in s:
                kw["max_completion_tokens"] = kw.pop("max_tokens"); continue
            raise
    raise RuntimeError("openai: parameters kept being rejected")


def _anthropic_text(system, user, max_tokens):
    model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    key = f"anthropic:{model}"
    kw = dict(model=model, max_tokens=max_tokens, system=system,
              messages=[{"role": "user", "content": user}])
    if key not in _NO_TEMP:
        kw["temperature"] = 0
    for _ in range(2):
        try:
            r = _client("anthropic").messages.create(**kw)
            u = getattr(r, "usage", None)
            if u:
                _note_usage(u.input_tokens, u.output_tokens)
            return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        except Exception as e:
            if "temperature" in kw and "temperature" in str(e).lower():
                _NO_TEMP.add(key); kw.pop("temperature"); continue
            raise
    raise RuntimeError("anthropic: parameters kept being rejected")


_CALLS = {"openai": _openai_text, "anthropic": _anthropic_text}


def _live():
    """Providers that have a key and have not been switched off, preferred one first."""
    names = ["openai", "anthropic"]
    if os.getenv("LLM_PROVIDER", "").lower() == "anthropic":
        names.reverse()
    keys = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    return [n for n in names if os.getenv(keys[n]) and n not in _dead]


def have_key():
    return bool(_live())


def _is_rate_limit(s):
    return "rate limit" in s or "rate_limit" in s or "429" in s or "too many requests" in s


def _retry_wait(s):
    """Seconds suggested by 'try again in 1m2.5s' / '7.5s' / '300ms'; else 10. Capped at 30."""
    m = re.search(r"try again in (?:(\d+)m)?(?:([\d.]+)(ms|s))?", s)
    if m and (m.group(1) or m.group(2)):
        secs = int(m.group(1) or 0) * 60
        if m.group(2):
            secs += float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
        return min(max(secs + 1, 2), 30)
    return 10


def llm_json(system, user, max_tokens=400, retries=6, rate_budget_s=240):
    """Returns a dict or None. Never raises.
    Rate limits wait (up to rate_budget_s in total) without using up a retry; other errors use retries."""
    mt = max_tokens
    t_start = time.time()
    attempt = 0
    while attempt < retries:
        live = _live()
        if not live:
            return None
        p = live[0]
        try:
            out = _extract_json(_CALLS[p](system, user, mt))
            if out is not None:
                return out
            raise ValueError("no JSON in reply")
        except Exception as e:
            s = str(e).lower()
            if _is_rate_limit(s):
                if "per day" in s or "tpd" in s or "rpd" in s:      # daily quota gone
                    _dead.add(p)
                    print(f"[llm] {p} daily quota exhausted for this run", flush=True)
                    continue
                if time.time() - t_start > rate_budget_s:
                    print(f"[llm] {p} rate limit: gave up after {rate_budget_s}s", flush=True)
                    return None
                with _lock:
                    USAGE["rate_waits"] += 1
                time.sleep(_retry_wait(s))                         # per-minute limit: wait, retry
                continue
            if any(k in s for k in _STOP):
                _dead.add(p)
                print(f"[llm] {p} switched off for this run: {type(e).__name__}: {str(e)[:120]}", flush=True)
                continue
            attempt += 1
            if "no json" in s:                                     # reply was cut off: allow a longer one
                mt = min(mt * 2, 4096)
            print(f"[llm] {p} attempt {attempt} failed: {type(e).__name__}: {str(e)[:150]}", flush=True)
            time.sleep(min(2 ** attempt, 20))
    return None

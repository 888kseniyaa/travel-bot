from dataclasses import dataclass, field
from .google_places import safe_url

@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    google_key: str = field(repr=False)
    mode: str = 'real'
    privacy_url: str = ''
    terms_url: str = ''

    @classmethod
    def load(cls, env):
        token = env.get('TELEGRAM_BOT_TOKEN', '').strip()
        mode = env.get('BOT_MODE', 'real').strip().lower()
        key = env.get('GOOGLE_PLACES_API_KEY', '').strip()
        privacy = safe_url(env.get('PRIVACY_POLICY_URL', '').strip())
        terms = safe_url(env.get('TERMS_URL', '').strip())
        if mode not in ('real', 'demo'): raise ValueError('BOT_MODE должен быть real или demo.')
        if not token: raise ValueError('Задайте TELEGRAM_BOT_TOKEN. См. README.md.')
        if mode == 'real':
            if not key: raise ValueError('В real-режиме требуется GOOGLE_PLACES_API_KEY. Demo включается только через BOT_MODE=demo.')
            if not privacy or not terms:
                raise ValueError('Для real-режима задайте публичные HTTPS-ссылки PRIVACY_POLICY_URL и TERMS_URL. См. README.md.')
        return cls(token, key, mode, privacy, terms)

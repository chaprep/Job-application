"""Explicit local configuration, loaded once at startup."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database: Path = ROOT / 'data/jab.sqlite3'
    base_url: str = 'https://openrouter.ai/api/v1'
    model: str = ''
    api_key: str = field(default='', repr=False)
    zyte_api_key: str = field(default='', repr=False)
    response_format: str = 'prompt_json'
    max_output_tokens: int = 8192
    ai_timeout: float = 120
    origins: tuple[str, ...] = ('http://localhost:5173', 'http://127.0.0.1:5173')
    resume_model: str = ''
    job_model: str = ''
    review_model: str = ''
    revision_model: str = ''
    tailor_model: str = ''
    cover_letter_model: str = ''
    cover_letter_research_enabled: bool = True
    research_max_searches: int = 5
    research_max_pages: int = 8
    research_timeout: float = 300
    zyte_search_domain: str = 'google.com'

    @property
    def ai_ready(self):
        return bool(self.model.strip() and self.api_key.strip() and self.base_url)

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Provider base URL must be HTTPS without credentials, query or fragment')
        if self.response_format not in ('prompt_json', 'json_schema'):
            raise ValueError('JAB_AI_RESPONSE_FORMAT must be prompt_json or json_schema')
        if not 1 <= self.max_output_tokens <= 65536 or not 1 <= self.ai_timeout <= 600:
            raise ValueError('Invalid AI request limits')
        if (not 1 <= self.research_max_searches <= 20 or not 1 <= self.research_max_pages <= 30
                or not 1 <= self.research_timeout <= 600):
            raise ValueError('Invalid company research limits')
        if not self.zyte_search_domain or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in self.zyte_search_domain):
            raise ValueError('Zyte search domain must be a hostname')

    @classmethod
    def load(cls):
        load_dotenv(ROOT / '.env', override=False)
        path = Path(os.getenv('JAB_DATABASE', 'data/jab.sqlite3'))
        research_enabled = os.getenv('JAB_COVER_LETTER_RESEARCH_ENABLED', 'true').strip().lower()
        if research_enabled not in ('true', 'false', '1', '0'):
            raise ValueError('JAB_COVER_LETTER_RESEARCH_ENABLED must be true or false')
        return cls(database=path if path.is_absolute() else ROOT / path,
                   base_url=os.getenv('JAB_AI_BASE_URL', 'https://openrouter.ai/api/v1').rstrip('/'),
                   model=os.getenv('JAB_AI_MODEL', ''), api_key=os.getenv('JAB_AI_API_KEY', ''),
                   zyte_api_key=os.getenv('JAB_ZYTE_API_KEY', '').strip(),
                   resume_model=os.getenv('JAB_AI_RESUME_MODEL', '').strip(),
                   job_model=os.getenv('JAB_AI_JOB_MODEL', '').strip(),
                   review_model=os.getenv('JAB_AI_REVIEW_MODEL', '').strip(),
                   revision_model=os.getenv('JAB_AI_REVISION_MODEL', '').strip(),
                   tailor_model=os.getenv('JAB_AI_TAILOR_MODEL', '').strip(),
                   cover_letter_model=os.getenv('JAB_AI_COVER_LETTER_MODEL', '').strip(),
                   cover_letter_research_enabled=research_enabled in ('true', '1'),
                   research_max_searches=int(os.getenv('JAB_RESEARCH_MAX_SEARCHES', '5')),
                   research_max_pages=int(os.getenv('JAB_RESEARCH_MAX_PAGES', '8')),
                   research_timeout=float(os.getenv('JAB_RESEARCH_TIMEOUT', '300')),
                   zyte_search_domain=os.getenv('JAB_ZYTE_SEARCH_DOMAIN', 'google.com').strip().lower(),
                   response_format=os.getenv('JAB_AI_RESPONSE_FORMAT', 'prompt_json'),
                   max_output_tokens=int(os.getenv('JAB_AI_MAX_OUTPUT_TOKENS', '8192')),
                   ai_timeout=float(os.getenv('JAB_AI_TIMEOUT', '120')),
                   origins=tuple(x.strip() for x in os.getenv('JAB_ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',') if x.strip()))

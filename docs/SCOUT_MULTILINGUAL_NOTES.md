# Multilingual Scout notes

This slice keeps multilingual discovery cost-aware and fail-open:

- Russian/Cyrillic intents persist `preferred_languages=("ru", "en")`.
- Command wrappers such as `Найди видео про ...` are removed before source search.
- An optional translation provider adds one concise English query variant.
- If translation is unavailable, Scout continues with the normalized original query.
- X receives one grouped `RU OR EN` Recent Search query, not two paid search requests.
- The final X result cap remains 10 candidates.
- Search translation credentials are scoped to the Scout worker and remain separate from media visual-moderation credentials.

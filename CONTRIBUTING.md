# Как вносить изменения

1. Окружение: `make setup && source .venv/bin/activate`, затем `make image` и `make data`.
2. Перед коммитом: `make lint test`. CI выполняет то же и ещё полный прогон на данных.
3. Если изменились код, CWL или пороги, пересоберите доказательства и картинки:

   ```bash
   make run && cp results/run/HG002.report.* docs/results/reference/
   ```

   ```bash
   make figures
   ```

   `make figures` пересобирает `evidence.json` и рисунки в `docs/assets`. На рисунке стоит число тестов, поэтому порядок такой: evidence без запуска тестов, рисунки, evidence с тестами. `scripts/lint_claims.py` не пропустит README, где число разошлось с `evidence.json`, `build_evidence.py --verify-source` — устаревший `evidence.json`, а `tests/test_figures.py` — устаревший рисунок.
   Для RNA-seq то же самое: `make rnaseq`, затем скопировать `results/rnaseq/rnaseq.*` в `docs/results/rnaseq/` и `make figures`.
4. Новое утверждение в README или docs — сначала строка в [CLAIMS_REGISTRY](CLAIMS_REGISTRY.md) с командой воспроизведения и границей, затем текст с пометкой `<!--ev:ключ-->число<!--/ev-->`.
5. Новая ошибка, которую пришлось расследовать, — запись в [DEBUGGING](docs/DEBUGGING.md) по схеме «симптом → причина → исправление → проверка» и, если можно, тест, который не даст ей вернуться.
6. Архитектурное решение — ADR в [docs/adr/](docs/adr/): решение, контекст, последствия, проверка.

Коммиты: одно логическое изменение на коммит, сообщение в повелительном наклонении по-английски (`Stage inputs by basename to keep headers reproducible`).

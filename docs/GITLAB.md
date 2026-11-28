# GitLab: зеркало и CI

Основной репозиторий — публичный GitHub. GitLab-копия нужна для полного CI на данных и для публикации отчёта в Pages. Оба способа синхронизации бесплатные.

## Зеркало

**Вариант 1. GitHub Action** ([`.github/workflows/mirror-to-gitlab.yml`](../.github/workflows/mirror-to-gitlab.yml)). Каждый push в `main` и каждый тег `v*` отправляются в GitLab.

1. В GitLab создать проект и Project Access Token: роль Developer или выше, scope `write_repository`.
2. В GitHub → Settings → Secrets and variables → Actions добавить секреты `GITLAB_URL` (`https://gitlab.com/<группа>/hg002-mini-wgs.git`) и `GITLAB_TOKEN`, а также переменную `GITLAB_MIRROR_ENABLED=true`.

**Вариант 2. Локально** ([`scripts/setup_gitlab_mirror.sh`](../scripts/setup_gitlab_mirror.sh)). Добавляет GitLab вторым push-адресом к `origin`, и обычный `git push` обновляет оба репозитория.

```bash
scripts/setup_gitlab_mirror.sh git@gitlab.com:<группа>/hg002-mini-wgs.git
```

Pull-зеркалирование из GitHub в самом GitLab доступно только на платных тарифах, поэтому оно не используется.

## Конвейер CI

| Стадия | Задание | Что делает | Сколько идёт |
|---|---|---|---|
| lint | `lint:cwl`, `lint:python`, `lint:shell`, `lint:dockerfile`, `lint:claims` | `cwltool --validate`, ruff, shellcheck, hadolint, сверка чисел в текстах с `evidence.json` | ~1 мин |
| test | `test:unit` | pytest с покрытием (cobertura в MR) и JUnit; падает, если есть пропущенные тесты | ~1 мин |
| build | `build:tools-image` | сборка образа с `RUN_TESTS=1`, push в Container Registry проекта (`:<sha>`, `:latest` на main) | ~4 мин |
| build | `build:rnaseq-image` | образ RNA-seq: архив Subread через `scripts/fetch_source.sh`, featureCounts из исходников с тестами, STAR | ~1 мин |
| pipeline | `pipeline:hg002` | данные (кеш по хешу `dataset.env`), прогон, порог качества (JUnit), второй прогон на 2 потоках и побайтное сравнение, загрузка в SQLite | ~4 мин |
| pipeline | `pipeline:callers` | Strelka2 и DeepVariant на BAM основного прогона, метрика патента рядом с GA4GH | ~10 мин |
| pipeline | `pipeline:rnaseq` | данные RNA-seq (кеш по хешу `rnaseq.env`), прогон, порог качества (JUnit), прогон на 2 потоках и сравнение | ~5 мин |
| publish | `pages` | HTML-отчёт в GitLab Pages (только `main`) | ~10 с |

Что видно в merge request: вкладка Tests (юнит-тесты и проверки порогов качества WGS и RNA-seq как тест-кейсы), покрытие, ссылки «HG002 report» и «RNA-seq report» на артефакты (`expose_as`).

## Требования к раннеру

Стадиям `build` и `pipeline` нужен Docker executor в привилегированном режиме (`docker:dind`). Важная деталь для dind: Docker-демон видит только каталог сборки (`/builds/…`), а не файловую систему контейнера задания. Поэтому `scripts/run_pipeline.sh` держит временные каталоги cwltool рядом с результатами (`CWL_WORKDIR`), а не в `/tmp`. Иначе монтирование входов в контейнеры шагов найдёт пустые каталоги.

Если в организации shell-раннер на узле с Docker или Apptainer, то `services` и `DOCKER_*` переменные не нужны, а задание `pipeline:hg002` можно заменить на `sbatch --wait slurm/run_cwltool_apptainer.sbatch`.

## Как проверялось

GitLab-раннер в этой работе не запускался. Команды каждого задания выполнены локально в том же порядке: валидация CWL и линтеры, pytest, чистая сборка образа с тестами, прогон, порог качества, сравнение 4/2 потоков, загрузка в базу. Образы заданий закреплены по digest, как и базовый образ Dockerfile.

# Происхождение

Откуда взяты внешние данные и программы, как закреплены их версии и чем проверена целостность. Остальной код написан в этом репозитории и распространяется по лицензии MIT ([LICENSE](LICENSE)).

## Данные

| Что | Источник | Закрепление и проверка | Лицензия / условия |
|---|---|---|---|
| Риды HG002, NovaSeq 6000, PCR-free, 2×151, ~35x | Google DeepVariant case study: `HG002.novaseq.pcr-free.35x.dedup.grch38_no_alt.chr20.bam` | sha256 FASTQ в `data/MANIFEST.sha256`; извлечение детерминировано (`samtools collate` хеширует имена) | публичные данные GIAB / PGP |
| Референс GRCh38 no-alt analysis set | `GCA_000001405.15_GRCh38_no_alt_analysis_set.fa.gz` (тот же bucket), чтение участка по `.fai/.gzi` | побайтная сверка участка с UCSC hg38 (REST API) при каждой подготовке; M5 = MD5 последовательности | публичный |
| Эталон GIAB HG002 v5.0q (small variants) | NIST, `ftp-trace.ncbi.nlm.nih.gov/.../HG002_NA24385_son/v5.0q/` | каждый REF-аллель после сдвига координат сверен с референсом (`bcftools norm --check-ref e`) | NIST, public domain |
| Эталон GIAB HG002 v4.2.1 | NIST, `.../NISTv4.2.1/GRCh38/` | то же | NIST, public domain |
| Стратификации GIAB v3.6 (8 файлов) | NIST, `.../genome-stratifications/v3.6/GRCh38@all/` | MD5 каждого файла против списка релиза `GRCh38-genome-stratifications-md5s.txt` | NIST, public domain |

| RNA-seq: UHR и HBR с ERCC Mix 1 и Mix 2, по три реплики | `genomedata.org/rnaseq-tutorial/HBR_UHR_ERCC_ds_5pc.tar` (Griffith et al., 2015) | sha256 архива; R1 и R2 сверены попарно по именам ридов | учебные данные, открытые |
| Концентрации ERCC в Mix 1 и Mix 2 | Thermo Fisher, `cms_095046.txt` | sha256; 92 транскрипта, 4 подгруппы по 23, отношения сходятся с концентрациями | открытый документ производителя |
| Последовательности и аннотация ERCC92 | Thermo Fisher, `ERCC92.zip` | sha256; набор идентификаторов совпадает с таблицей концентраций | то же |
| chr22 GRCh38 | тот же `GCA_000001405.15_GRCh38_no_alt_analysis_set.fa.gz`, чтение по индексу | длина и M5 сверены со словарём `Homo_sapiens_assembly38.dict` (Broad Institute) | публичный |
| Аннотация GENCODE 50 | EBI, `gencode.v50.annotation.gtf.gz` | MD5 из `MD5SUMS` релиза | открытая |

Сами данные в репозиторий не входят: `make data` собирает их заново (~40 МБ, ~45 с), `make rnaseq-data` — данные RNA-seq (~500 МБ вместе с загруженными архивами, около трёх минут, больше всего времени уходит на GENCODE), а `MANIFEST.sha256` в каждом каталоге фиксирует результат.

## Программы

| Что | Версия | Как попадает в образ | Проверка |
|---|---|---|---|
| Базовый образ | `debian:trixie-slim@sha256:8aa5a7bf…` | `FROM` по digest | digest |
| Пакеты Debian | snapshot `20261123T000000Z` (дата сборки базового образа) | `snapshot.debian.org` | подписи apt |
| htslib, samtools, bcftools | 1.25 | сборка из релизных тарболов | `ADD --checksum=sha256`, `make test` всех трёх при сборке |
| bwa-mem2 | 2.3 (бинарник сообщает 2.2.1, см. [D-03](docs/DEBUGGING.md#d-03)) | релизный архив x86-64 | `ADD --checksum=sha256` |
| fastp | 1.4.0 | статический бинарник opengene.org | `ADD --checksum=sha256` |
| hap.py | 0.3.15 | `quay.io/biocontainers/hap.py@sha256:d63b963a…` | digest |
| Strelka2 | 2.9.10 | `quay.io/biocontainers/strelka@sha256:0fb1a07c…` | digest |
| DeepVariant | 1.10.0 | `google/deepvariant@sha256:962e5a83…` | digest |
| STAR | 2.7.11b | официальный статический бинарник из релиза GitHub | `ADD --checksum=sha256` |
| Subread (featureCounts) | 2.1.1 | сборка из архива с SourceForge, скачанного `scripts/fetch_source.sh` | sha256 до сборки и внутри неё, тесты featureCounts при сборке |
| fastp для проверки D-23 | 1.4.0, коммит `ee125a52` | сборка из исходников по хешу коммита тега, как есть и с патчем; в пайплайне не используется | хеш коммита git |
| Dockerfile frontend | 1.7 | `# syntax=docker/dockerfile:1.7@sha256:a57df69d…` | digest |

Контрольные суммы тарболов записаны при первом скачивании с GitHub Releases по TLS (trust on first use); у проектов samtools и bwa-mem2 нет опубликованных подписей релизов.

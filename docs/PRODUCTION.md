# Производственный стек популяционного WGS и как его воспроизводит Etalon

В открытых публикациях описан стек, на котором в России обработаны геномы крупной популяционной когорты: прибор NovaSeq 6000, выравнивание DRAGEN, вызов вариантов Strelka2, контроль качества FastQC, samtools и mosdepth, а точность оценивается по эталонному образцу методикой из патента RU 2846268. Источники перечислены в конце страницы.

Etalon воспроизводит из этого стека всё, что доступно открыто, на открытом эталоне GIAB HG002 (NIST). Его задача — проверить выбор инструментов на независимых данных и дополнить методику оценки точности. Заменять методику он не предлагает.

## Шаг за шагом

| Шаг | В публикациях | В Etalon | Чем проверено |
|---|---|---|---|
| Секвенирование | NovaSeq 6000, 2×150, библиотека Illumina DNA Prep (с ПЦР) | данные того же прибора: HG002, NovaSeq 6000, 2×151, без ПЦР | оптические и ПЦР-дубликаты считаются раздельно ([отчёт](results/reference/HG002.report.md)) |
| Демультиплексирование | bcl2fastq 2.20 | вход — готовые FASTQ | — |
| Контроль ридов | FastQC 0.11.9 | fastp 1.4.0 с отчётом | [D-05](DEBUGGING.md#d-05): флаг, замедлявший шаг в 19 раз |
| Выравнивание | DRAGEN (программно-аппаратный комплекс) | bwa-mem2 2.3 | пять сборок под разные процессоры дают одинаковый BAM ([REPRODUCIBILITY](REPRODUCIBILITY.md)) |
| Контроль выравнивания | samtools 1.13, mosdepth 0.3.1 | samtools 1.25, собранный из исходников с тестами | [C-08](../CLAIMS_REGISTRY.md) |
| **Вызов вариантов** | **Strelka2, вызовы PASS** | **Strelka2 2.9.10** на том же BAM, что bcftools 1.25 и DeepVariant 1.10 | hap.py, страты GIAB, парный тест ([C-16](../CLAIMS_REGISTRY.md), [C-17](../CLAIMS_REGISTRY.md)) |
| **Оценка точности** | **доля совпавших генотипов (F), порог 99,9 %** | F по формуле патента рядом с recall, precision и F1 по GA4GH | [METRICS](METRICS.md), [C-19](../CLAIMS_REGISTRY.md) |
| Хранение выравниваний | формат не описан | BAM и CRAM 3.1: CRAM занимает <!--ev:cram_v31_share-->29<!--/ev--> % объёма BAM, вызовы из него те же | [ниже](#хранение-выравниваний-cram-вместо-bam), [C-30](../CLAIMS_REGISTRY.md) |
| Окружение | Python 3.9 | Python 3.10–3.13 в CI; Python 2.7 только внутри образов hap.py и Strelka2 | CI |

## Что показало сравнение вызывателей

Один BAM (HG002, ~35x, 2 Мб chr20), PASS-вызовы, эталон GIAB v5.0q. Полные таблицы — в [results/callers/compare.md](results/callers/compare.md).

| | bcftools | Strelka2 | DeepVariant |
|---|---|---|---|
| SNV F1 [95 % ДИ] | <!--ev:bcftools_snp_v5_f1-->0.9868<!--/ev--> [<!--ev:bcftools_snp_v5_f1_ci-->0.983–0.990<!--/ev-->] | <!--ev:strelka2_snp_v5_f1-->0.9955<!--/ev--> [<!--ev:strelka2_snp_v5_f1_ci-->0.993–0.997<!--/ev-->] | <!--ev:dv_snp_v5_f1-->0.9957<!--/ev--> [<!--ev:dv_snp_v5_f1_ci-->0.994–0.997<!--/ev-->] |
| Инделы F1 [95 % ДИ] | <!--ev:bcftools_indel_v5_f1-->0.9081<!--/ev--> [<!--ev:bcftools_indel_v5_f1_ci-->0.890–0.923<!--/ev-->] | <!--ev:strelka2_indel_v5_f1-->0.9383<!--/ev--> [<!--ev:strelka2_indel_v5_f1_ci-->0.923–0.951<!--/ev-->] | <!--ev:dv_indel_v5_f1-->0.9430<!--/ev--> [<!--ev:dv_indel_v5_f1_ci-->0.928–0.954<!--/ev-->] |
| Ложные вызовы SNV / инделов | <!--ev:bcftools_snp_v5_fp-->42<!--/ev--> / <!--ev:bcftools_indel_v5_fp-->50<!--/ev--> | <!--ev:strelka2_snp_v5_fp-->10<!--/ev--> / <!--ev:strelka2_indel_v5_fp-->16<!--/ev--> | <!--ev:dv_snp_v5_fp-->14<!--/ev--> / <!--ev:dv_indel_v5_fp-->32<!--/ev--> |
| Пропуски SNV / инделов | <!--ev:bcftools_snp_v5_fn-->28<!--/ev--> / <!--ev:bcftools_indel_v5_fn-->60<!--/ev--> | <!--ev:strelka2_snp_v5_fn-->14<!--/ev--> / <!--ev:strelka2_indel_v5_fn-->55<!--/ev--> | <!--ev:dv_snp_v5_fn-->9<!--/ev--> / <!--ev:dv_indel_v5_fn-->37<!--/ev--> |
| SNV F1 в тандемных повторах | <!--ev:bcftools_snp_v5_tr_f1-->0.800<!--/ev--> | <!--ev:strelka2_snp_v5_tr_f1-->0.967<!--/ev--> | <!--ev:dv_snp_v5_tr_f1-->0.916<!--/ev--> |
| CPU на вызов, с | <!--ev:bcftools_call_cpu_s-->10<!--/ev--> | <!--ev:strelka2_call_cpu_s-->20<!--/ev--> | <!--ev:dv_call_cpu_s-->169<!--/ev--> |
| Пик памяти, МБ | <!--ev:bcftools_call_peak_mb-->60<!--/ev--> | <!--ev:strelka2_call_peak_mb-->102<!--/ev--> | <!--ev:dv_call_peak_mb-->5459<!--/ev--> |

1. Strelka2 точнее bcftools, и выигрыш в основном в точности (precision): ложных вызовов у него заметно меньше (строка «Ложные вызовы» в таблице). По пропускам разница меньше: парный тест по истинным SNV — <!--ev:mcnemar_snp_v5_strelka2_bcftools_only_base-->21<!--/ev--> вариант нашёл только Strelka2 и <!--ev:mcnemar_snp_v5_strelka2_bcftools_only_other-->7<!--/ev--> только bcftools (p = <!--ev:mcnemar_snp_v5_strelka2_bcftools_p-->0.013<!--/ev-->); по инделам <!--ev:mcnemar_indel_v5_strelka2_bcftools_only_base-->25<!--/ev--> против <!--ev:mcnemar_indel_v5_strelka2_bcftools_only_other-->20<!--/ev--> (p = <!--ev:mcnemar_indel_v5_strelka2_bcftools_p-->0.551<!--/ev-->). Почти вся разница — в сложных участках: там SNV F1 <!--ev:bcftools_snp_v5_difficult_f1-->0.906<!--/ev--> у bcftools против <!--ev:strelka2_snp_v5_difficult_f1-->0.977<!--/ev--> у Strelka2. Выбор Strelka2 для производства на этих данных подтверждается.
2. DeepVariant и Strelka2 на этом участке по F1 не различаются: интервалы перекрываются и по SNV, и по инделам. DeepVariant находит больше истинных инделов (<!--ev:mcnemar_indel_v5_strelka2_dv_only_other-->27<!--/ev--> против <!--ev:mcnemar_indel_v5_strelka2_dv_only_base-->9<!--/ev-->, p = <!--ev:mcnemar_indel_v5_strelka2_dv_p-->0.004<!--/ev-->), но и ложных инделов у него больше: <!--ev:dv_indel_v5_fp-->32<!--/ev--> против <!--ev:strelka2_indel_v5_fp-->16<!--/ev-->. CPU на вызов у него в <!--ev:dv_vs_strelka2_cpu_x-->8.6<!--/ev--> раза больше, пик памяти — <!--ev:dv_call_peak_mb-->5459<!--/ev--> МБ против <!--ev:strelka2_call_peak_mb-->102<!--/ev--> МБ. Для когорты в сотни тысяч геномов замена вызывателя — решение о вычислительном бюджете, и принимать его стоит по полному геному, а не по 2 Мб.
3. Все три вызывателя воспроизводимы: VCF и gVCF Strelka2 и DeepVariant побайтно совпадают при 4 и 2 потоках ([C-18](../CLAIMS_REGISTRY.md)). Чтобы так было у Strelka2, из заголовка убраны дата, время запуска, командная строка и путь к референсу (`cwl/tools/vcf-clean-header.cwl`, [D-15](DEBUGGING.md#d-15)).

## Хранение выравниваний: CRAM вместо BAM

На когорте в десятки тысяч геномов основной объём хранения — выравнивания. CRAM хранит риды относительно референса и без потерь сжимает их сильнее BAM. `scripts/check_cram.sh` (`make cram`) переписывает BAM эталонного прогона в три варианта CRAM и проверяет, что ничего не потеряно ([results/cram/cram.md](results/cram/cram.md)).

| Формат | Размер, МБ | Доля от BAM | Запись, с | Чтение, с |
|---|---|---|---|---|
| BAM | <!--ev:cram_bam_mb-->27.2<!--/ev--> | 100 % | – | <!--ev:cram_bam_read_s-->0.30<!--/ev--> |
| CRAM 3.0 (по умолчанию в samtools 1.13) | <!--ev:cram_v30_mb-->9.3<!--/ev--> | <!--ev:cram_v30_share-->34<!--/ev--> % | <!--ev:cram_v30_write_s-->1.4<!--/ev--> | <!--ev:cram_v30_read_s-->0.56<!--/ev--> |
| CRAM 3.1 (по умолчанию с samtools 1.22) | <!--ev:cram_v31_mb-->7.9<!--/ev--> | <!--ev:cram_v31_share-->29<!--/ev--> % | <!--ev:cram_v31_write_s-->1.5<!--/ev--> | <!--ev:cram_v31_read_s-->0.48<!--/ev--> |
| CRAM 3.1, профиль archive | <!--ev:cram_v31a_mb-->7.2<!--/ev--> | <!--ev:cram_v31a_share-->26<!--/ev--> % | <!--ev:cram_v31a_write_s-->14.7<!--/ev--> | <!--ev:cram_v31a_read_s-->1.81<!--/ev--> |

Время — на одном потоке; чтение — полное декодирование в SAM.

1. Без потерь. Записи CRAM совпадают с записями BAM (<!--ev:cram_records_identical-->да<!--/ev-->), а вызовы bcftools из CRAM — побайтно с вызовами из BAM (<!--ev:cram_calls_identical-->да<!--/ev-->). Побайтно не совпадает только SAM-текст (<!--ev:cram_sam_bytes_identical-->нет<!--/ev-->): CRAM не хранит теги MD и NM, а восстанавливает их при чтении и ставит в конец записи. По спецификации SAM порядок дополнительных полей не значим.
2. CRAM 3.1 меньше CRAM 3.0 на <!--ev:cram_v31_vs_v30-->15<!--/ev--> %. samtools 1.13 из производственного стека по умолчанию пишет CRAM 3.0. Версию 3.1 можно задать явно (`--output-fmt-option version=3.1`) или обновить samtools.
3. Цена — время чтения. CRAM 3.1 читается в <!--ev:cram_v31_read_x-->1.6<!--/ev--> раза дольше BAM. Профиль archive экономит ещё 3 процентных пункта, но пишется в <!--ev:cram_v31a_write_x-->10<!--/ev--> раз дольше: он для архива, а не для рабочих копий.
4. Порядок величины для когорты. При линейном пересчёте участка на геном 30x BAM занимает около <!--ev:cram_bam_genome_gb-->34<!--/ev--> ГБ, CRAM 3.1 — около <!--ev:cram_v31_genome_gb-->10<!--/ev--> ГБ. На <!--ev:cram_cohort-->100 000<!--/ev--> геномов разница порядка <!--ev:cram_saving_v31_pb-->2.4<!--/ev--> ПБ. Это грубая оценка: на полном геноме соотношение может отличаться на несколько процентов.
5. Референс — часть архива. CRAM без референса не прочитать. Хранить нужно тот самый FASTA, с которым писался CRAM (MD5 последовательностей записан в заголовке). При переходе на другой референс старые CRAM нужно перепаковать или хранить оба референса.

## Что не воспроизводится открытыми средствами

- **DRAGEN.** Программа проприетарная и привязана к оборудованию. Открытая реализация его выравнивателя — DRAGMAP; сравнение DRAGMAP с bwa-mem2 на тех же стратах стоит в [ROADMAP](ROADMAP.md).
- **Российский эталонный образец.** Данные российского донора в открытый репозиторий не загружаются: генетические данные граждан РФ нельзя передавать за рубеж, а GitHub — зарубежная площадка. Методика переносится на такой эталон без правки кода: эталонный VCF, доверенные участки, референс и пороги задаются в job-файле ([METHODOLOGY](METHODOLOGY.md#перенос-на-другой-эталон-или-референс)).
- **Глубина и библиотека.** Здесь ~35x и PCR-free. Производственные данные — с ПЦР и глубже 30x; разница в доле дубликатов и ошибках в гомополимерах на этих данных не измерена.

## Запуск

```bash
make run       # основной пайплайн: BAM и вызовы bcftools -> results/run
```

```bash
make callers   # Strelka2 и DeepVariant на том же BAM, сравнение -> results/callers/compare.md
```

```bash
make metric    # формула патента рядом с GA4GH -> results/metrics/patent_metric.md
```

```bash
make cram      # BAM против CRAM 3.0, 3.1 и 3.1 archive -> docs/results/cram
```

## Источники

- Патент RU 2846268 C1. Способ оценки точности результатов высокопроизводительного секвенирования и биоинформатической обработки генома человека. Заявка от 15.11.2024, патент выдан 03.09.2025.
- Юдин В. С. и др. // Экстремальная биомедицина. 2026. Т. 28, № 1. С. 19–27 — описание обработки данных когорты: NovaSeq 6000, bcl2fastq, DRAGEN, Strelka2, FastQC, samtools, mosdepth.
- Kim S. et al. Strelka2: fast and accurate calling of germline and somatic variants. Nat Methods. 2018;15:591–594.
- Poplin R. et al. A universal SNP and small-indel variant caller using deep neural networks. Nat Biotechnol. 2018;36:983–987.

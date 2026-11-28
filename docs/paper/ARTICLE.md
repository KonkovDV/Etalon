# Побайтно воспроизводимые пайплайны WGS и RNA-seq на CWL: источники недетерминизма и проверка на эталонных образцах GIAB HG002 и ERCC

*Черновик рукописи для рецензируемого журнала в формате IMRaD. Числа помечены и сверяются с данными в CI, как во всех документах репозитория; каждое воспроизводится командой из [реестра утверждений](../../CLAIMS_REGISTRY.md).*

Дмитрий Коньков · открытый проект Etalon · https://github.com/KonkovDV/Etalon

## Аннотация

**Введение.** Базы популяционных частот и приёмка протоколов секвенирования по эталонному образцу опираются на то, что один и тот же вход даёт один и тот же результат при смене числа потоков, исполнителя, образа и машины. Обычно это предполагают, а не проверяют.

**Цель.** Построить пайплайны полногеномного секвенирования (WGS) и RNA-seq, результат которых совпадает побайтно в любой из проверенных конфигураций, найти и устранить все источники недетерминизма и показать, что воспроизводимый пайплайн точен на эталонных образцах.

**Материалы и методы.** WGS: эталонный образец GIAB HG002, NovaSeq 6000, PCR-free, 2×151, участок 2 Мб хромосомы 20, глубина <!--ev:mean_depth-->34.5<!--/ev-->x. RNA-seq: эталонные РНК UHR и HBR со spike-in ERCC, по три реплики. Шаги описаны на CWL v1.2, программы работают в Docker-образах, закреплённых по digest; htslib, samtools, bcftools и featureCounts собраны из исходников с их тестами. Критерий воспроизводимости — совпадение sha256 выходных файлов.

**Результаты.** VCF совпал побайтно во всех <!--ev:repro_comparisons-->10<!--/ev--> сравнениях: другое число потоков, повторный запуск, cwltool и Toil на Slurm, образ, пересобранный с нуля, другая машина и пять сборок bwa-mem2 под разные наборы инструкций процессора. Найдены и устранены девять источников недетерминизма, в том числе два в сторонних программах: в fastp 1.4.0 гистограмму длины вставки строит один рабочий поток из N, а STAR выбирает границы бинов сортировки BAM по потоку, который первым заполнил буфер. Воспроизводимый пайплайн даёт SNV F1 <!--ev:strelka2_snp_v5_f1-->0.9955<!--/ev--> со Strelka2 на эталоне GIAB v5.0q, а RNA-seq — корреляцию измеренной кратности по ERCC с известной <!--ev:rnaseq_fc_pearson-->0.984<!--/ev-->.

**Заключение.** Побайтная воспроизводимость достижима на стандартных открытых инструментах и проверяется одной командой. Сравнение sha256 выходов на эталонном образце годится как регрессионный тест каждого обновления пайплайна.

**Ключевые слова:** полногеномное секвенирование, RNA-seq, воспроизводимость, Common Workflow Language, эталонный образец, GIAB HG002, ERCC, контроль качества.

## Abstract

**Background.** Population frequency databases and reference-sample acceptance of sequencing protocols assume that identical inputs give identical outputs regardless of thread count, workflow engine, container build and machine. This assumption is rarely tested.

**Methods.** We built WGS and RNA-seq pipelines in CWL v1.2 with digest-pinned Docker images and tools compiled from source together with their test suites, and benchmarked them on GIAB HG002 (NovaSeq 6000, PCR-free, 2×151, 2 Mb of chr20, ~35x) and on UHR/HBR RNA with ERCC spike-ins. Reproducibility was judged by sha256 of output files.

**Results.** The VCF was byte-identical in all <!--ev:repro_comparisons-->10<!--/ev--> comparisons: thread count, rerun, cwltool versus Toil on Slurm, an image rebuilt from scratch, a second machine and five SIMD builds of bwa-mem2. Nine sources of non-determinism were found and removed, including two in third-party tools: fastp 1.4.0 builds its insert-size histogram in one worker thread out of N, and STAR picks BAM sorting-bin boundaries from whichever thread fills its buffer first. The reproducible pipeline reaches SNV F1 <!--ev:strelka2_snp_v5_f1-->0.9955<!--/ev--> with Strelka2 on GIAB v5.0q; RNA-seq fold changes correlate with the known ERCC ratios at r = <!--ev:rnaseq_fc_pearson-->0.984<!--/ev-->.

**Conclusions.** Byte-level reproducibility is achievable with standard open-source tools and is checked with a single command. Comparing output checksums on a reference sample works as a regression test for every pipeline update.

## Введение

Крупные программы популяционной геномики обрабатывают десятки и сотни тысяч геномов одним пайплайном и годами его обновляют [1, 2]. Когда меняется версия программы, число потоков, узел кластера или образ, важно знать, изменился ли результат и почему. Самый строгий и самый дешёвый ответ даёт побайтное сравнение выходов: совпадение sha256 не требует обсуждать, «существенны ли» различия.

Источники недетерминизма в пайплайнах NGS известны по отдельности: размер пачки ридов в bwa-mem2 зависит от числа потоков, исполнители CWL монтируют входы в случайные каталоги, программы пишут в заголовки дату, путь и командную строку. Однако сводной проверки, после которой пайплайн WGS и RNA-seq совпадает побайтно в целом наборе конфигураций, в открытых источниках мы не нашли.

Цель работы — построить такие пайплайны, найти и устранить каждый источник недетерминизма и показать на эталонных образцах, что воспроизводимость достигнута без потери точности.

## Материалы и методы

**Данные WGS.** Эталонный образец HG002 (NIST RM 8391) [3], прибор NovaSeq 6000, библиотека PCR-free, 2×151, <!--ev:read_pairs-->259084<!--/ev--> пар ридов участка chr20:10–12 Мб (GRCh38), средняя глубина без дубликатов <!--ev:mean_depth-->34.5<!--/ev-->x. Эталоны малых вариантов GIAB v5.0q и v4.2.1, стратификации GIAB v3.6 [4]. Каждый REF-аллель эталонов сверен с референсом, участок референса — побайтно с UCSC hg38, стратификации — по MD5 релиза.

**Данные RNA-seq.** Эталонные РНК UHR и HBR со spike-in ERCC в смесях Mix 1 и Mix 2, по три реплики, HiSeq 2500, 2×100 [5–7]. ERCC — 92 транскрипта известной концентрации в четырёх подгруппах с отношениями 4 : 1, 1 : 1, 2 : 3 и 1 : 2.

**Пайплайны.** WGS: fastp 1.4.0 [8] → bwa-mem2 2.3 [9] → samtools 1.25 → bcftools 1.25 [10]; на том же BAM — Strelka2 2.9.10 [11] и DeepVariant 1.10 [12]; сверка с эталоном — hap.py по стандарту GA4GH [1]. RNA-seq: fastp → STAR 2.7.11b [13] → featureCounts (Subread 2.1.1) [14]. Шаги описаны на CWL v1.2 [15] и выполняются cwltool или Toil [16]; на кластере — под Slurm, с Docker или Apptainer [17]. Базовый образ закреплён по digest, пакеты Debian — по snapshot.debian.org. htslib, samtools и bcftools собраны из исходников с их тестами: <!--ev:htslib_tests_passed-->364<!--/ev--> из <!--ev:htslib_tests_total-->364<!--/ev-->, <!--ev:samtools_tests_passed-->1020<!--/ev--> пройдено и <!--ev:samtools_tests_failed-->0<!--/ev--> ошибок, <!--ev:bcftools_tests_passed-->2538<!--/ev--> из <!--ev:bcftools_tests_total-->2538<!--/ev-->; featureCounts — <!--ev:featurecounts_tests_passed-->52<!--/ev--> проверки без провалов.

**Критерий воспроизводимости.** Два прогона сравниваются на нескольких уровнях: sha256 файла VCF, sha256 распакованных записей VCF, sha256 выравниваний BAM без заголовка, sha256 файла BAM и итоги hap.py (`scripts/check_reproducibility.sh`). Для RNA-seq дополнительно сравниваются матрица счётов, таблица featureCounts и числа отчёта (`scripts/check_rnaseq_reproducibility.sh`). Проверка сама проверена отрицательными тестами: отсутствующий каталог или BAM дают ошибку, а не «совпадает».

**Точность.** Recall и precision — с интервалом Уилсона, F1 — с интервалом Монте-Карло по апостериорным бета-распределениям с фиксированным зерном. Два вызывателя на одном BAM сравниваются парным точным тестом Макнемара по истинным вариантам.

**Ресурсы.** Каждый шаг запускается через `bin/measure.py`, который записывает время, CPU и пик памяти всего дерева процессов шага. Так замер не зависит от исполнителя и учитывает процессы внутри контейнера, которые Slurm при запуске через Docker не видит.

## Результаты

### Источники недетерминизма и их устранение

| Источник | Как проявлялся | Что сделано |
|---|---|---|
| размер пачки ридов в bwa-mem2 зависит от числа потоков | разные выравнивания при 4 и 2 потоках | `-K 100000000`: пачка фиксирована в основаниях |
| порядок ридов на входе | другие пачки — другие выравнивания | FASTQ строится детерминированно, fastp сохраняет порядок |
| случайные каталоги исполнителя CWL | пути в `##reference` VCF и `@PG` BAM | входы раскладываются в рабочий каталог шага и передаются по имени |
| командные строки, версии и даты в заголовках | строки `##bcftools_*Command`, `@PG samtools`, `Date=` | `--no-version` у bcftools, `--no-PG` у samtools |
| имя сборки bwa-mem2 в `@PG` | BAM сборки AVX2 отличается строкой заголовка | сборка запускается с `argv[0] = bwa-mem2`, как это делает лаунчер |
| заголовок VCF Strelka2 | дата, время и путь к референсу | очистка заголовка без новых строк (`bcftools view --no-version -h`) |
| границы бинов сортировки BAM в STAR | другие байты BAM при тех же записях | BAM переписывается блоками htslib |
| гистограмма длины вставки в fastp | пик зависит от числа потоков | значение исключено из отчётов; патч для fastp |
| Монте-Карло в отчёте | интервалы F1 менялись от прогона к прогону | фиксированное зерно |

### Побайтное совпадение

VCF совпал побайтно во всех <!--ev:repro_comparisons-->10<!--/ev--> сравнениях: 4 и 2 потока, повторный запуск, cwltool и Toil с отдельной задачей Slurm на каждый шаг, образ, пересобранный с нуля, другая машина с образом, собранным за прокси с подменой TLS, и пять сборок bwa-mem2 (SSE4.1, SSE4.2, AVX, AVX2, AVX-512BW). При одинаковом числе потоков совпадает и BAM; при разном BAM отличается одной строкой заголовка с `-t N`. VCF и gVCF Strelka2 и DeepVariant совпадают при 4 и 2 потоках (Strelka2: <!--ev:strelka2_repro_vcf-->да<!--/ev-->, DeepVariant: <!--ev:dv_repro_vcf-->да<!--/ev-->). В RNA-seq при 4 и 2 потоках совпадают матрица счётов (<!--ev:rnaseq_repro_threads_4_vs_2_counts-->да<!--/ev-->) и записи BAM (<!--ev:rnaseq_repro_threads_4_vs_2_bam_records-->да<!--/ev-->), а при повторе на тех же потоках BAM совпадает побайтно (<!--ev:rnaseq_repro_same_threads_bam_bytes-->да<!--/ev-->).

### Дефекты сторонних программ

Побайтная проверка находит и то, что не видно при сравнении итоговых метрик.

- **fastp 1.4.0.** Гистограмму длины вставки строит только рабочий поток 0, а пачки ридов раздаются потокам по кругу. При 1, 2, 3 и 4 потоках в гистограмму попадает <!--ev:fastp_isize_rna_share_t1-->100<!--/ev-->, <!--ev:fastp_isize_rna_share_t2-->50<!--/ev-->, <!--ev:fastp_isize_rna_share_t3-->33<!--/ev--> и <!--ev:fastp_isize_rna_share_t4-->25<!--/ev--> % пар, и пик равен <!--ev:fastp_isize_rna_peak_t1-->145<!--/ev-->, <!--ev:fastp_isize_rna_peak_t2-->154<!--/ev-->, <!--ev:fastp_isize_rna_peak_t3-->161<!--/ev--> и <!--ev:fastp_isize_rna_peak_t4-->140<!--/ev-->. Патч из трёх строк вызывает подсчёт во всех потоках: гистограмма становится независимой от числа потоков (<!--ev:fastp_isize_patched_thread_independent-->да<!--/ev-->), риды на выходе не меняются (<!--ev:fastp_isize_reads_identical-->да<!--/ev-->).
- **fastp 1.4.0, скорость.** Флаг `--detect_adapter_for_pe` запускает отдельный однопоточный проход; без него шаг идёт <!--ev:fastp_after_s-->2.1<!--/ev--> с вместо <!--ev:fastp_before_s-->39.6<!--/ev--> с при тех же ридах и тех же итогах hap.py.
- **STAR 2.7.11b.** Границы бинов сортировки выбираются по выравниваниям потока, который первым заполнил буфер, поэтому байты BAM при повторе различаются при одинаковых записях.
- **Subread 2.1.1.** Тесты featureCounts завершаются с кодом 0 при любом исходе; сборка сама подсчитывает PASS и FAILED.
- **bwa-mem2 2.3.** Бинарник релиза сообщает версию 2.2.1; версия закрепляется тегом релиза и sha256 архива.

### Точность воспроизводимого пайплайна

| Показатель (GIAB v5.0q, PASS) | bcftools | Strelka2 | DeepVariant |
|---|---|---|---|
| SNV F1 | <!--ev:snp_v5_f1-->0.9868<!--/ev--> | <!--ev:strelka2_snp_v5_f1-->0.9955<!--/ev--> | <!--ev:dv_snp_v5_f1-->0.9957<!--/ev--> |
| Инделы F1 | <!--ev:indel_v5_f1-->0.9081<!--/ev--> | <!--ev:strelka2_indel_v5_f1-->0.9383<!--/ev--> | <!--ev:dv_indel_v5_f1-->0.9430<!--/ev--> |

Strelka2 точнее bcftools (парный тест Макнемара по истинным SNV, p = <!--ev:mcnemar_snp_v5_strelka2_bcftools_p-->0.013<!--/ev-->); DeepVariant и Strelka2 по F1 не различаются, а CPU на вызов у DeepVariant в <!--ev:dv_vs_strelka2_cpu_x-->8.6<!--/ev--> раза больше. Ошибки сосредоточены в сложных участках: вне них SNV F1 <!--ev:snp_v5_easy_f1-->0.999<!--/ev-->, в тандемных повторах — <!--ev:snp_v5_tr_f1-->0.800<!--/ev--> у bcftools.

RNA-seq: отклик на ERCC линейный, наклон <!--ev:rnaseq_slope_min-->0.94<!--/ev-->–<!--ev:rnaseq_slope_max-->0.99<!--/ev--> при теоретической 1, 95 % интервал накрывает 1 у <!--ev:rnaseq_slope_ci_cover_1-->6<!--/ev--> образцов из 6, R² ≥ <!--ev:rnaseq_r2_min-->0.966<!--/ev-->; кратность UHR/HBR коррелирует с известной на <!--ev:rnaseq_fc_pearson-->0.984<!--/ev--> при RMSE <!--ev:rnaseq_fc_rmse-->0.21<!--/ev--> log2.

### Ресурсы

Шаги WGS вместе занимают <!--ev:total_wall_s-->40<!--/ev--> с и <!--ev:total_cpu_s-->66<!--/ev--> CPU-с на 4 потоках, пик памяти самого тяжёлого шага — <!--ev:max_peak_rss_mb-->1138<!--/ev--> МБ. Линейный пересчёт по числу оснований даёт нижнюю оценку ≈ <!--ev:cpu_h_per_genome_lb-->19<!--/ev--> CPU-часов на геном 30x и ≈ <!--ev:cpu_mh_120k_lb-->2.3<!--/ev--> млн CPU-часов на когорту из <!--ev:cohort_120k-->120 000<!--/ev--> геномов. Выравнивания в CRAM 3.1 занимают <!--ev:cram_v31_share-->29<!--/ev--> % объёма BAM, а вызовы bcftools из CRAM совпадают с вызовами из BAM побайтно.

## Обсуждение

Побайтная воспроизводимость получена на стандартных открытых инструментах без изменения их алгоритмов. Почти все источники недетерминизма лежат не в вычислениях, а вокруг них: в размере пачки, в заголовках файлов, в путях исполнителя и в способе записи сжатого файла. Поэтому их можно устранить параметрами запуска и одним дополнительным шагом, а затем держать под контролем тестами: правила CWL проверяются статически на каждый коммит.

Для производственного пайплайна и базы частот отсюда следуют четыре практики:

1. Закреплять образы по digest, пакеты — по снимку репозитория, исходники — по sha256 и собирать ключевые программы с их тестами.
2. Убирать из выходов всё, что зависит от запуска: даты, пути, командные строки; фиксировать размер пачки выравнивателя.
3. Принимать каждое обновление по эталонному образцу: совпадение sha256 выходов означает, что результат не изменился, а расхождение указывает, на каком уровне — записи, выравнивания или заголовок — искать причину.
4. Мерить ресурсы внутри шага: так запросы памяти для Slurm берутся из замеров, а не из учёта планировщика, который не видит контейнеры Docker.

Сравнение sha256 оказалось и инструментом отладки чужого кода: дефект fastp проявился как различие одного числа в отчётах двух прогонов с одинаковыми ридами.

**Условия проверки и следующие шаги.** Воспроизводимость проверена на эталоне HG002 (участок 2 Мб, ~35x) и на наборе UHR/HBR с ERCC, на машинах x86-64 с AVX-512. Эталон, референс и пороги задаются в job-файле, поэтому та же проверка переносится на полный геном и национальный эталонный образец без правки кода. Следующие шаги — полный геном с разбиением вызова по окнам, побайтная проверка сжатых файлов на процессоре без AVX-512 и запуск через Apptainer на многоузловом кластере.

## Заключение

Пайплайны WGS и RNA-seq на CWL дают побайтно одинаковый результат во всех <!--ev:repro_comparisons-->10<!--/ev--> проверенных конфигурациях при точности, сопоставимой с производственными вызывателями. Каждый источник недетерминизма найден, устранён и закрыт тестом, а два дефекта сторонних программ описаны с воспроизводимой проверкой и исправлением.

## Доступность данных и кода

Код, описания CWL, Dockerfile, файлы прогонов и все числа статьи — в открытом репозитории https://github.com/KonkovDV/Etalon (лицензия MIT). Данные GIAB находятся в общественном достоянии, риды WGS взяты из публичного набора DeepVariant case study, риды RNA-seq — из открытого учебного набора [7]. Команда воспроизведения каждого числа — в [реестре утверждений](../../CLAIMS_REGISTRY.md).

## Литература

1. Krusche P., Trigg L., Boutros P. C. et al. Best practices for benchmarking germline small-variant calls in human genomes // Nat. Biotechnol. 2019. Vol. 37. P. 555–560. doi:10.1038/s41587-019-0054-x
2. Юдин В. С. и др. // Экстремальная биомедицина. 2026. Т. 28, № 1. С. 19–27.
3. Zook J. M., Catoe D., McDaniel J. et al. Extensive sequencing of seven human genomes to characterize benchmark reference materials // Sci. Data. 2016. Vol. 3. 160025. doi:10.1038/sdata.2016.25
4. Dwarshuis N., Kalra D., McDaniel J. et al. The GIAB genomic stratifications resource for human reference genomes // Nat. Commun. 2024. Vol. 15. doi:10.1038/s41467-024-53260-y
5. Jiang L., Schlesinger F., Davis C. A. et al. Synthetic spike-in standards for RNA-seq experiments // Genome Res. 2011. Vol. 21. P. 1543–1551. doi:10.1101/gr.121095.111
6. Munro S. A., Lund S. P., Pine P. S. et al. Assessing technical performance in differential gene expression experiments with external spike-in RNA control ratio mixtures // Nat. Commun. 2014. Vol. 5. 5125. doi:10.1038/ncomms6125
7. Griffith M., Walker J. R., Spies N. C. et al. Informatics for RNA sequencing: a web resource for analysis on the cloud // PLoS Comput. Biol. 2015. Vol. 11. e1004393. doi:10.1371/journal.pcbi.1004393
8. Chen S., Zhou Y., Chen Y., Gu J. fastp: an ultra-fast all-in-one FASTQ preprocessor // Bioinformatics. 2018. Vol. 34. P. i884–i890. doi:10.1093/bioinformatics/bty560
9. Vasimuddin M., Misra S., Li H., Aluru S. Efficient architecture-aware acceleration of BWA-MEM for multicore systems // IEEE IPDPS. 2019. P. 314–324. doi:10.1109/IPDPS.2019.00041
10. Danecek P., Bonfield J. K., Liddle J. et al. Twelve years of SAMtools and BCFtools // GigaScience. 2021. Vol. 10. giab008. doi:10.1093/gigascience/giab008
11. Kim S., Scheffler K., Halpern A. L. et al. Strelka2: fast and accurate calling of germline and somatic variants // Nat. Methods. 2018. Vol. 15. P. 591–594. doi:10.1038/s41592-018-0051-x
12. Poplin R., Chang P.-C., Alexander D. et al. A universal SNP and small-indel variant caller using deep neural networks // Nat. Biotechnol. 2018. Vol. 36. P. 983–987. doi:10.1038/nbt.4235
13. Dobin A., Davis C. A., Schlesinger F. et al. STAR: ultrafast universal RNA-seq aligner // Bioinformatics. 2013. Vol. 29. P. 15–21. doi:10.1093/bioinformatics/bts635
14. Liao Y., Smyth G. K., Shi W. featureCounts: an efficient general purpose program for assigning sequence reads to genomic features // Bioinformatics. 2014. Vol. 30. P. 923–930. doi:10.1093/bioinformatics/btt656
15. Crusoe M. R., Abeln S., Iosup A. et al. Methods included: standardizing computational reuse and portability with the Common Workflow Language // Commun. ACM. 2022. Vol. 65, № 6. P. 54–63. doi:10.1145/3486897
16. Vivian J., Rao A. A., Nothaft F. A. et al. Toil enables reproducible, open source, big biomedical data analyses // Nat. Biotechnol. 2017. Vol. 35. P. 314–316. doi:10.1038/nbt.3772
17. Kurtzer G. M., Sochat V., Bauer M. W. Singularity: scientific containers for mobility of compute // PLoS One. 2017. Vol. 12. e0177459. doi:10.1371/journal.pone.0177459

# Реестр утверждений

Здесь собраны числа и утверждения из README и документации. У каждого указана команда, которая его воспроизводит, и граница, за которой оно перестаёт быть верным. В текстах на утверждения ссылаются по номеру строки, например C-02.

Числа собирает `evidence.json` (`make evidence`). В CI `scripts/lint_claims.py` сверяет с ним каждое помеченное число в текстах и не пропускает формулировки из `BANNED_CLAIMS.txt`.

## Точность

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-01 | На эталоне GIAB v5.0q: SNV F1 <!--ev:snp_v5_f1-->0.9868<!--/ev--> (95 % ДИ <!--ev:snp_v5_f1_ci-->0.983–0.990<!--/ev-->), инделы F1 <!--ev:indel_v5_f1-->0.9081<!--/ev--> (<!--ev:indel_v5_f1_ci-->0.890–0.923<!--/ev-->) | `make data && make run`, затем `results/run/HG002.report.html` | один образец, 2 Мб chr20, ~35x, PASS-варианты |
| C-02 | На v4.2.1 те же вызовы дают SNV F1 <!--ev:snp_v421_f1-->0.9977<!--/ev-->, инделы <!--ev:indel_v421_f1-->0.9804<!--/ev-->: выше, потому что v4.2.1 не включает многие сложные участки | тот же прогон, второй эталон | разница — свойство эталонов, а не вызывателя |
| C-03 | Ошибки сосредоточены в сложных участках: вне них SNV F1 <!--ev:snp_v5_easy_f1-->0.999<!--/ev--> и инделы <!--ev:indel_v5_easy_f1-->0.996<!--/ev-->, в тандемных повторах — <!--ev:snp_v5_tr_f1-->0.800<!--/ev--> и <!--ev:indel_v5_tr_f1-->0.826<!--/ev--> (v5.0q) | отчёт, раздел «Точность против эталонов GIAB» | в стратах десятки–сотни вариантов, интервалы широкие |
| C-04 | Профиль `-X illumina` (consensus-based indel caller bcftools ≥ 1.20) поднимает F1 инделов на v5.0q с <!--ev:indel_v5_f1_legacy-->0.8399<!--/ev--> (<!--ev:indel_v5_f1_legacy_ci-->0.817–0.860<!--/ev-->) до <!--ev:indel_v5_f1-->0.9081<!--/ev-->; интервалы не пересекаются; SNV не меняется (<!--ev:snp_v5_f1_legacy-->0.9863<!--/ev--> против <!--ev:snp_v5_f1-->0.9868<!--/ev-->) | `scripts/run_pipeline.sh -o results/legacy 'mpileup_profile=""'`, `make db` | один участок и одна библиотека |
| C-05 | Спектр замен ложноположительных SNV не обогащён C>A (8-oxoG): тест Фишера p = <!--ev:oxog_fisher_p-->0.58<!--/ev--> | отчёт, раздел «Спектр замен» | FP SNV всего <!--ev:fp_snv_v5-->42<!--/ev-->: тест заметит только сильный эффект |

## Воспроизводимость

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-06 | VCF побайтно одинаковый во всех <!--ev:repro_comparisons-->10<!--/ev--> сравнениях: 4 и 2 потока, повторный запуск, cwltool и Toil на Slurm, образ, пересобранный с нуля, другая машина за прокси с подменой TLS, пять сборок bwa-mem2 под разные наборы инструкций (SSE4.1…AVX-512BW) | `make repro`; `scripts/run_pipeline.sh bwa_simd=sse41`; отчёты `docs/results/reproducibility_*.md` | машины x86-64 с AVX-512; сжатие (libdeflate) на CPU без AVX-512 не проверялось |
| C-07 | При одинаковом числе потоков побайтно одинаковый и BAM | `docs/results/reproducibility_same_threads.md` | при разном числе потоков отличается только `@PG` с `-t N` |
| C-08 | Образ собирается из исходников с тестами: htslib <!--ev:htslib_tests_passed-->364<!--/ev-->/<!--ev:htslib_tests_total-->364<!--/ev-->, samtools <!--ev:samtools_tests_passed-->1020<!--/ev--> пройдено и <!--ev:samtools_tests_failed-->0<!--/ev--> ошибок, bcftools <!--ev:bcftools_tests_passed-->2538<!--/ev-->/<!--ev:bcftools_tests_total-->2538<!--/ev--> | `make image` (`RUN_TESTS=1`), `docs/results/build_tests.txt` | на snapshot Debian 20261123 |
| C-09 | Данные проверены: участок референса совпадает с UCSC hg38 побайтно, все REF-аллели эталонов — с референсом, стратификации — по MD5 релиза | `make data` (останавливается при расхождении) | проверка на момент подготовки |

## Ресурсы и кластер

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-10 | Шаги пайплайна вместе занимают <!--ev:total_wall_s-->40<!--/ev--> с и <!--ev:total_cpu_s-->66<!--/ev--> CPU-с на 4 потоках; пик памяти самого тяжёлого шага (fastp) <!--ev:max_peak_rss_mb-->1138<!--/ev--> МБ | отчёт, раздел «Время и память по шагам» | время внутри контейнеров; с запуском контейнеров cwltool прогон идёт около минуты |
| C-11 | fastp ускорен с <!--ev:fastp_before_s-->39.6<!--/ev--> до <!--ev:fastp_after_s-->2.1<!--/ev--> с без изменения результата | `docs/results/fastp_profile.txt`, [D-05](docs/DEBUGGING.md#d-05) | fastp 1.4.0, эти данные |
| C-12 | Пайплайн запускается в Slurm тремя способами: sbatch (cwltool), Toil (по задаче Slurm на шаг, 12 задач), job array для когорты | `docs/results/slurm.md`, `docs/results/slurm_sacct.txt` | одноузловой Slurm 23.11 в контейнере, Docker вместо Apptainer |
| C-13 | Нижняя оценка вычислений для генома 30x: ≈ <!--ev:cpu_h_per_genome_lb-->19<!--/ev--> CPU-часов, для 100 000 геномов ≈ <!--ev:cpu_mh_100k_lb-->1.9<!--/ev--> млн CPU-часов, для <!--ev:cohort_120k-->120 000<!--/ev--> — ≈ <!--ev:cpu_mh_120k_lb-->2.3<!--/ev--> млн | отчёт, раздел «Время и память»; `cohort_claims` в `scripts/build_evidence.py` | линейная экстраполяция по числу оснований, без индексации и hap.py; реальная цифра выше |

## Качество кода

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-14 | <!--ev:unit_tests-->166<!--/ev--> автотестов проходят, пропусков нет; в их числе статические проверки CWL на правила воспроизводимости | `make test` | тесты не запускают контейнеры; полный прогон — задание `pipeline:hg002` |
| C-15 | <!--ev:cwl_tools-->19<!--/ev--> инструментов CWL v1.2, все проходят `cwltool --validate` | `make lint` | |

## Вызыватели и метрика приёмки

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-16 | На одном BAM Strelka2 точнее bcftools: на v5.0q SNV F1 <!--ev:strelka2_snp_v5_f1-->0.9955<!--/ev--> [<!--ev:strelka2_snp_v5_f1_ci-->0.993–0.997<!--/ev-->] против <!--ev:bcftools_snp_v5_f1-->0.9868<!--/ev--> [<!--ev:bcftools_snp_v5_f1_ci-->0.983–0.990<!--/ev-->], инделы <!--ev:strelka2_indel_v5_f1-->0.9383<!--/ev--> против <!--ev:bcftools_indel_v5_f1-->0.9081<!--/ev-->; парный тест Макнемара по истинным SNV p = <!--ev:mcnemar_snp_v5_strelka2_bcftools_p-->0.013<!--/ev--> | `make callers`; `docs/results/callers/compare.md` | один образец, 2 Мб, ~35x; на v4.2.1 разница по SNV не значима |
| C-17 | DeepVariant 1.10 и Strelka2 по F1 на v5.0q не различаются (SNV <!--ev:dv_snp_v5_f1-->0.9957<!--/ev--> и <!--ev:strelka2_snp_v5_f1-->0.9955<!--/ev-->, инделы <!--ev:dv_indel_v5_f1-->0.9430<!--/ev--> и <!--ev:strelka2_indel_v5_f1-->0.9383<!--/ev-->, интервалы перекрываются); DeepVariant находит больше истинных инделов (p = <!--ev:mcnemar_indel_v5_strelka2_dv_p-->0.004<!--/ev-->) и тратит в <!--ev:dv_vs_strelka2_cpu_x-->8.6<!--/ev--> раза больше CPU | `make callers` | модель WGS, chr20 исключена из её обучения; CPU замерен на 4 ядрах одной машины |
| C-18 | VCF и gVCF Strelka2 и DeepVariant побайтно одинаковы при 4 и 2 потоках (Strelka2: <!--ev:strelka2_repro_vcf-->да<!--/ev-->, DeepVariant: <!--ev:dv_repro_vcf-->да<!--/ev-->) | `docs/results/callers/reproducibility_*.md` | у DeepVariant меняется нарезка make_examples; TensorFlow в обоих прогонах видел 4 ядра |
| C-19 | Метрика F по формуле патента RU 2846268 на тех же вызовах: на v4.2.1 порог 99,9 % проходит <!--ev:patent_pass_v421-->1<!--/ev--> вызыватель из трёх, на v5.0q — <!--ev:patent_pass_v5-->0<!--/ev-->; пропуски и лишние вызовы в F не входят | `make metric`; `docs/results/metrics/patent_metric.md`; `tests/test_concordance.py` | эталоны GIAB, а не российский эталонный набор; формула реализована по тексту патента |
| C-20 | Нормализация в `scripts/concordance.py` совпадает с `bcftools norm -m -any -f ref` на <!--ev:norm_check_records-->17759<!--/ev--> записях пяти VCF, расхождений <!--ev:norm_check_diff-->0<!--/ev--> | `scripts/check_normalization.sh` | символьные аллели не сравниваются |
| C-27 | На ридах, прореженных до <!--ev:depth_f145_x-->5.5<!--/ev-->x, все три вызывателя проходят порог патента с F = <!--ev:depth_f145_bcftools_f_v421-->100.00<!--/ev--> % (v4.2.1), хотя SNV F1 на v5.0q <!--ev:depth_f145_bcftools_snp_f1-->0.695<!--/ev-->–<!--ev:depth_f145_dv_snp_f1-->0.874<!--/ev-->: в знаменатель F входит <!--ev:depth_f145_bcftools_share_v421-->1.8<!--/ev-->–<!--ev:depth_f145_dv_share_v421-->3.5<!--/ev--> % эталона. Три зерна на одной глубине дают F bcftools <!--ev:depth_rep_f290_bcftools_f_v421-->99.38–99.66<!--/ev--> % (~10x) | `make depth`; `docs/results/depth/curve.md` | один образец, 2 Мб; прореживание меняет глубину, но не библиотеку; DeepVariant — только с зерном 1 |

## RNA-seq

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-21 | Отклик на ERCC линейный: наклон log2(фрагменты на кб) против log2(концентрации) <!--ev:rnaseq_slope_min-->0.94<!--/ev-->–<!--ev:rnaseq_slope_max-->0.99<!--/ev-->, 95 % интервал накрывает 1 у <!--ev:rnaseq_slope_ci_cover_1-->6<!--/ev--> образцов из 6, R² <!--ev:rnaseq_r2_min-->0.966<!--/ev-->–<!--ev:rnaseq_r2_max-->0.979<!--/ev--> | `make rnaseq-data rnaseq`; `docs/results/rnaseq/rnaseq.report.json` | ERCC с ≥ 10 фрагментами; один набор UHR/HBR, риды chr22 и ERCC |
| C-22 | Кратность UHR/HBR по ERCC после поправки на долю мРНК (×<!--ev:rnaseq_fc_offset-->1.28<!--/ev-->, по подгруппе B) коррелирует с известной на <!--ev:rnaseq_fc_pearson-->0.984<!--/ev-->, RMSE <!--ev:rnaseq_fc_rmse-->0.21<!--/ev--> log2; наибольшее смещение подгруппы — <!--ev:rnaseq_fc_max_bias-->0.18<!--/ev--> log2 (1 : 2) | то же | <!--ev:rnaseq_fc_n-->35<!--/ev--> ERCC с ≥ 10 фрагментами во всех шести репликах; смещение B равно нулю по построению |
| C-23 | При 4 и 2 потоках совпадают матрица счётов (<!--ev:rnaseq_repro_threads_4_vs_2_counts-->да<!--/ev-->), записи BAM (<!--ev:rnaseq_repro_threads_4_vs_2_bam_records-->да<!--/ev-->) и числа отчёта (<!--ev:rnaseq_repro_threads_4_vs_2_report-->да<!--/ev-->); при повторе на тех же потоках BAM побайтно одинаковый (<!--ev:rnaseq_repro_same_threads_bam_bytes-->да<!--/ev-->) | `scripts/check_rnaseq_reproducibility.sh`; `docs/results/rnaseq/reproducibility_*.md` | одна машина x86-64; заголовок BAM содержит `--runThreadN N` |
| C-24 | featureCounts собран из исходников, при сборке проходит <!--ev:featurecounts_tests_passed-->52<!--/ev--> проверки своего набора тестов, провалов <!--ev:featurecounts_tests_failed-->0<!--/ev-->; на тех же BAM он и счётчик STAR совпадают по ERCC до фрагмента, по генам сумма расходится не больше чем на <!--ev:rnaseq_counter_diff_max-->0.5<!--/ev--> % | `make rnaseq-image`; `docs/results/rnaseq/build_tests.txt` | тесты Subread сами код ошибки не возвращают, его выставляет сборка ([D-18](docs/DEBUGGING.md#d-18)) |
| C-25 | Реплики согласованы (Пирсон log2 CPM внутри групп ≥ <!--ev:rnaseq_rep_within_min-->0.980<!--/ev-->, между UHR и HBR ≤ <!--ev:rnaseq_rep_between_max-->0.536<!--/ev-->); <!--ev:rnaseq_markers-->8/8<!--/ev--> маркерных генов chr22 изменились в ожидаемую по биологии образцов сторону | `make rnaseq` | <!--ev:rnaseq_rep_genes-->265<!--/ev--> генов с ≥ 10 фрагментами в каждом образце; маркеры выбраны до прогона |

## Чужой код

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-26 | В fastp 1.4.0 гистограмма длины вставки строится только в рабочем потоке 0: при 1–4 потоках в неё попадают <!--ev:fastp_isize_rna_share_t1-->100<!--/ev-->, <!--ev:fastp_isize_rna_share_t2-->50<!--/ev-->, <!--ev:fastp_isize_rna_share_t3-->33<!--/ev--> и <!--ev:fastp_isize_rna_share_t4-->25<!--/ev--> % пар, и пик меняется. Патч из трёх строк делает гистограмму независимой от числа потоков (<!--ev:fastp_isize_patched_thread_independent-->да<!--/ev-->), риды не меняются (<!--ev:fastp_isize_reads_identical-->да<!--/ev-->) | `make fastp-isize-image fastp-isize`; `docs/results/fastp_isize_threads.md` | проверено на 1–4 потоках, на парных ридах с обрезкой адаптеров по перекрытию; одиночные риды длину вставки не считают |

## База частот

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-28 | На одном BAM <!--ev:repr_share_min-->17<!--/ev-->–<!--ev:repr_share_max-->53<!--/ev--> % различий между вызывателями по ключу (CHROM, POS, REF, ALT) — запись, а не разные варианты: разбиение мультиаллельных записей убирает <!--ev:repr_split_share_min-->17<!--/ev-->–<!--ev:repr_split_share_max-->30<!--/ev--> %, сдвиг влево — <!--ev:repr_shift_total-->0<!--/ev-->, ещё <!--ev:repr_bcftools_dv_same-->19<!--/ev--> и <!--ev:repr_strelka2_dv_same-->46<!--/ev--> ключей — тот же гаплотип в другой записи. Все <!--ev:repr_loci_total-->16<!--/ev--> таких случаев подтверждены сборкой гаплотипов из референса (<!--ev:repr_loci_verified-->16<!--/ev--> из <!--ev:repr_loci_total-->16<!--/ev-->) | `make depth aggregation`; `docs/results/aggregation/representation.md`; `tests/test_representation.py` | один образец, 2 Мб, три вызывателя; доверенные участки v5.0q |
| C-29 | В когорте из <!--ev:cohort_all_samples-->7<!--/ev--> копий HG002 на глубине <!--ev:cohort_all_x-->5.5–34.5<!--/ev-->x AF гетерозигот при AN = 2N — <!--ev:cohort_all_het_naive-->0.475<!--/ev-->, по генотипам с GQ ≥ <!--ev:callable_gq_min-->20<!--/ev--> — <!--ev:cohort_all_het_honest-->0.496<!--/ev-->; ошибка AF больше 0,1 у <!--ev:cohort_all_het_naive_off-->9.0<!--/ev--> и <!--ev:cohort_all_het_honest_off-->1.3<!--/ev--> % вариантов. В когорте от 20x средняя AF одна и та же (<!--ev:cohort_ge20x_het_naive-->0.498<!--/ev-->), ошибка больше 0,1 — у <!--ev:cohort_ge20x_het_naive_off-->1.1<!--/ev--> и <!--ev:cohort_ge20x_het_honest_off-->0.5<!--/ev--> % | `make depth aggregation`; `docs/results/aggregation/callable.md`; `tests/test_callable.py`, `tests/test_scripts.py` | модель: копии одного генома, глубина получена прореживанием; доверенные участки GIAB |

## Хранение

| № | Утверждение | Как воспроизвести | Граница |
|---|---|---|---|
| C-30 | CRAM 3.1 занимает <!--ev:cram_v31_share-->29<!--/ev--> % объёма BAM (CRAM 3.0 — <!--ev:cram_v30_share-->34<!--/ev--> %, профиль archive — <!--ev:cram_v31a_share-->26<!--/ev--> %); записи те же (<!--ev:cram_records_identical-->да<!--/ev-->), вызовы bcftools из CRAM побайтно те же (<!--ev:cram_calls_identical-->да<!--/ev-->); чтение на одном потоке в <!--ev:cram_v31_read_x-->1.6<!--/ev--> раза дольше. Грубая оценка для когорты геномов 30x: на <!--ev:cram_cohort-->100 000<!--/ev--> разница с BAM ≈ <!--ev:cram_saving_v31_pb-->2.4<!--/ev--> ПБ, на <!--ev:cohort_120k-->120 000<!--/ev--> — ≈ <!--ev:cram_saving_v31_120k_pb-->2.9<!--/ev--> ПБ (BAM ≈ <!--ev:cram_bam_120k_pb-->4.1<!--/ev--> ПБ, CRAM 3.1 ≈ <!--ev:cram_v31_120k_pb-->1.2<!--/ev--> ПБ) | `make cram`; `docs/results/cram/cram.md`; `cohort_claims` в `scripts/build_evidence.py` | участок 2 Мб, один образец; порядок дополнительных полей SAM в CRAM другой (MD и NM восстанавливаются при чтении); оценка для когорты — линейный пересчёт участка на геном |

# Источники

Что прочитано при подготовке и что из каждого источника взято в работу. Обзор открытых источников сделан в ноябре 2026 года. Препринты помечены отдельно: их выводы могут измениться.

## Эталоны и сверка

| Источник | Что взято в работу |
|---|---|
| NIST, Genome in a Bottle — [страница программы](https://www.nist.gov/programs-projects/genome-bottle) и [релиз HG002 v5.0q](https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/v5.0q/) | v5.0q — текущий эталон малых вариантов HG002, v4.2.1 помечен как устаревший. Поэтому основной эталон — v5.0q, а v4.2.1 оставлен для сравнения ([ADR-005](adr/ADR-005-two-truth-sets.md)) |
| *The Genome In A Bottle HG002 assembly-based variant benchmark set…* — [bioRxiv, 2026](https://www.biorxiv.org/content/10.64898/2026.09.23.752440v1.full) (препринт) | v5.0q построен по сборке HG002 Q100 (DeFrABB) для GRCh37, GRCh38 и CHM13 и сравнивается с v4.2.1. Отсюда ожидание, что на v5.0q метрики ниже за счёт сложных участков, и это подтвердилось |
| *A complete diploid human genome benchmark for personalized genomics* — [bioRxiv, 2025](https://www.biorxiv.org/content/10.1101/2025.09.21.677443v1.full.pdf) (препринт) | контекст: что такое HG002 Q100 и почему сборка «от теломеры до теломеры» даёт эталон без белых пятен сложных участков |
| Krusche et al. *Best practices for benchmarking germline small-variant calls in human genomes.* Nat Biotechnol 2019 — [препринт](https://www.biorxiv.org/content/biorxiv/early/2018/03/15/270157.full.pdf) | стандарт GA4GH: сопоставление по гаплотипам, TP/FN/FP, стратификация; hap.py как реализация |
| Dwarshuis et al. *The GIAB genomic stratifications resource for human reference genomes.* Nat Commun 2024 — [PMC11489684](https://pmc.ncbi.nlm.nih.gov/articles/PMC11489684) | восемь страт v3.6 (сложные участки, гомополимеры, повторы, картируемость, сегдупы, GC, экзоны); MD5 по списку релиза |
| [Illumina/hap.py](https://github.com/Illumina/hap.py) | движок xcmp, выход summary/extended/ROC; образ biocontainers 0.3.15 по digest |
| Dunn & Narayanasamy. *vcfdist.* [Nat Commun 2023](https://www.nature.com/articles/s41467-023-43876-x); [Genome Biol 2024](https://genomebiology.biomedcentral.com/articles/10.1186/s13059-024-03394-5) | альтернатива hap.py для фазированных вызовов с частичным зачётом; в [ROADMAP](ROADMAP.md) |
| Holt et al. *Aardvark.* [bioRxiv, 2025](https://www.biorxiv.org/content/10.1101/2025.10.03.680257v1.full) (препринт) | быстрее hap.py с совместимой схемой оценки генотипов; кандидат на замену после рецензирования, в [ROADMAP](ROADMAP.md) |

## Инструменты

| Источник | Что взято в работу |
|---|---|
| [Руководство bcftools](https://samtools.github.io/bcftools/bcftools.html) | профили `-X` (`illumina` = `--indels-cns --indel-size 110` с 1.20); маркировка `--indels-cns` как экспериментального, поэтому его эффект измерен отдельно ([C-04](../CLAIMS_REGISTRY.md)) |
| Danecek et al. *Twelve years of SAMtools and BCFtools.* GigaScience 2021 | модель вызова bcftools, нормализация, общая библиотека htslib |
| [fastp](https://github.com/OpenGene/fastp) и [практика обрезки poly-G](https://speciationgenomics.github.io/fastp) | poly-G на двухцветной химии и почему обрезка по качеству его не снимает |
| bwa `-K` и воспроизводимость — [обсуждение на Biostars](https://biostars.org/p/337527), [документация NVIDIA Parabricks fq2bam](https://docs.nvidia.com/clara/parabricks/tool-reference/tools/fq2bam) | фиксированный размер пачки в основаниях делает вывод независимым от числа потоков; здесь проверено напрямую (4 против 2 потоков) |
| [cwltool releases](https://github.com/common-workflow-language/cwltool/releases); *Simplifying the development of portable, scalable, and reproducible workflows* — [PMC8514239](https://pmc.ncbi.nlm.nih.gov/articles/PMC8514239/) | CWL v1.2.1 как актуальная версия стандарта; cwltool как эталонная реализация, Toil как кластерная |

## Вызыватели и метрики, использованные в работе

| Источник | Что взято в работу |
|---|---|
| Kim S. et al. *Strelka2: fast and accurate calling of germline and somatic variants.* Nat Methods 2018 | Strelka2 2.9.10 — производственный вызыватель популяционных проектов; запущен на том же BAM ([PRODUCTION](PRODUCTION.md)) |
| Poplin R. et al. *A universal SNP and small-indel variant caller using deep neural networks.* Nat Biotechnol 2018; [документация DeepVariant](https://github.com/google/deepvariant) | DeepVariant 1.10, модель WGS; chr20–22 исключены из обучения модели, поэтому на участке chr20 оценку не завышает то, что модель видела эти данные |
| McNemar Q. *Note on the sampling error of the difference between correlated proportions or percentages.* Psychometrika 1947 | парный точный тест для двух вызывателей на одних и тех же истинных вариантах ([METHODOLOGY](METHODOLOGY.md#статистика)) |
| Tan A., Abecasis G. R., Kang H. M. *Unified representation of genetic variants.* Bioinformatics 2015 | алгоритм нормализации (обрезка и сдвиг влево) в `scripts/concordance.py`, сверен с `bcftools norm` |
| Патент RU 2846268 C1 (2025). *Способ оценки точности результатов высокопроизводительного секвенирования и биоинформатической обработки генома человека* | формула метрики F и порог 99,9 %; посчитана рядом с GA4GH ([METRICS](METRICS.md)) |
| Юдин В. С. и др. Экстремальная биомедицина. 2026;28(1):19–27 | описание производственного стека: NovaSeq 6000, bcl2fastq, DRAGEN, Strelka2, FastQC, samtools, mosdepth ([PRODUCTION](PRODUCTION.md)) |

## Глубина и приёмка образца

Пороги, с которыми крупные программы принимают геном. Нужны для раздела [F и глубина](METRICS.md#f-и-глубина): там доля эталона в знаменателе F сопоставлена с порогами на покрытие.

| Источник | Что взято в работу |
|---|---|
| All of Us Research Program. *Genomic Research Data Quality Report, CDR v8* — [support.researchallofus.org](https://support.researchallofus.org/hc/en-us/article_attachments/40491583732116) (2025) | приёмка генома: средняя глубина не ниже 30x и покрытие не ниже 20x на 90 % оснований; контаминация до 3 % для исследовательских данных |
| Genomics England. *Sample QC* — [документация Research Environment](https://re-docs.genomicsengland.co.uk/sample_qc/) | условие поставки: покрытие не ниже 15x на 95 % генома; FREEMIX ниже 0,03 |
| gnomAD v3.1 — [заметка о выпуске](https://gnomad.broadinstitute.org/news/2020-10-gnomad-v3-1-new-content-methods-annotations-and-data-availability) (2020) | жёсткие фильтры образцов: контаминация или химерные риды выше 5 %, средняя глубина на chr20 ниже 15x |

## База частот

Как крупные программы собирают частоты из десятков и сотен тысяч геномов. Нужны для раздела об AN в [AGGREGATION](AGGREGATION.md).

| Источник | Что взято в работу |
|---|---|
| gnomAD v4.0 — [заметка о выпуске](https://gnomad.broadinstitute.org/news/2023-11-gnomad-v4-0) (2023) | 76 215 геномов; gVCF образцов объединены в Hail, опорные блоки сохраняются, поэтому AN считается по известным генотипам |
| gnomAD v3.0 — [заметка о выпуске](https://gnomad.broadinstitute.org/news/2019-10-gnomad-v3-0) (2019) | цена хранения: геномы в разреженной матрице Hail — 20 ТБ, в виде плотного VCF — около 900 ТБ |
| The All of Us Research Program Genomics Investigators. *Genomic data in the All of Us Research Program.* Nature 2024 — [doi:10.1038/s41586-023-06957-x](https://doi.org/10.1038/s41586-023-06957-x) | 245 388 геномов, DRAGEN; совместный вызов в Genomic Variant Store, выдача в Hail VDS |
| Genomics England. *aggV3* — [документация Research Environment](https://re-docs.genomicsengland.co.uk/aggv3/) | 138 406 образцов, DRAGEN 3.7.8; агрегация итеративным генотипированием gVCF в DRAGEN |

## Сравнения вызывателей (контекст, не воспроизводилось)

| Источник | Что говорит |
|---|---|
| *Variant calling in genomics: A comparative performance analysis and decision guide.* [PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0339891) | на chr20 DeepVariant точнее всех, GATK близко |
| *Comprehensive assessment of WGS-based variant calling pipelines in monozygotic twins.* [Brief Bioinform 2025](https://academic.oup.com/bib/article/26/6/bbaf652/8374034) | конвейеры на bcftools конкурентны по скорости и точности |
| [Frontiers in Bioinformatics, 2025](https://www.frontiersin.org/journals/bioinformatics/articles/10.3389/fbinf.2025.1691056/full) | использует черновой эталон Q100 для GRCh38 |

Вывод для этой работы: прямого свежего сравнения bcftools, Strelka2 и DeepVariant на одном эталоне v5.0q с одинаковыми фильтрами в открытых источниках не нашлось, поэтому оно сделано здесь на одном BAM ([PRODUCTION](PRODUCTION.md)). Его границы — один образец и 2 Мб ([LIMITS](../LIMITS.md)).

## RNA-seq

| Источник | Что взято в работу |
|---|---|
| Jiang L. et al. *Synthetic spike-in standards for RNA-seq experiments.* Genome Res 2011 | ERCC как эталон для RNA-seq: известная концентрация, линейный отклик в log-log координатах |
| Munro S. A. et al. *Assessing technical performance in differential gene expression experiments with external spike-in RNA control ratio mixtures.* Nat Commun 2014 | смеси Mix 1 и Mix 2 с четырьмя кратностями; поправка отношений ERCC на разную долю мРНК в образцах; ROC по подгруппам — следующий шаг |
| SEQC/MAQC-III Consortium. Nat Biotechnol 2014 | UHR и HBR как общие референсные РНК; ERCC в межлабораторном сравнении RNA-seq |
| Griffith M. et al. *Informatics for RNA sequencing: a web resource for analysis on the cloud.* PLoS Comput Biol 2015 | открытый набор UHR/HBR с ERCC, три реплики, chr22 |
| Dobin A. et al. *STAR: ultrafast universal RNA-seq aligner.* Bioinformatics 2013; руководство STAR | выравнивание; параметры ENCODE; `--genomeSAindexNbases` для маленького генома; `--quantMode GeneCounts` как второй счётчик |
| Liao Y., Smyth G. K., Shi W. *featureCounts.* Bioinformatics 2014 | счёт фрагментов на ген; `-p --countReadPairs` с Subread 2.0.2 |
| Frankish A. et al. *GENCODE 2023.* Nucleic Acids Res 2023 | аннотация GENCODE (здесь релиз 50, Ensembl 116) |
| Patro R. et al. *Salmon provides fast and bias-aware quantification of transcript expression.* Nat Methods 2017; Srivastava A. et al. Genome Biol 2020 | квантование транскриптов с selective alignment и decoy; кандидат на сравнение с featureCounts на тех же ERCC ([ROADMAP](ROADMAP.md)) |
| Love M. I., Huber W., Anders S. *DESeq2.* Genome Biol 2014 | стандартный тест дифференциальной экспрессии для следующего шага ([ROADMAP](ROADMAP.md)) |
| Yu Y. et al. *Quartet RNA reference materials improve the quality of transcriptomic data through ratio-based profiling.* Nat Biotechnol 2024 | эталонные материалы для оценки RNA-seq по отношениям между образцами; та же идея, что у Mix 1 / Mix 2, на эндогенных генах |

## Национальные референсные ресурсы

Публикации о российских референсных данных. Здесь они только поясняют раздел методики о переносе на другой эталон; на них в репозитории ничего не построено, а сведения о составе выборок и сроках в разных источниках расходятся.

| Источник | О чём |
|---|---|
| [Профиль, 2026](https://profile.ru/news/scitech/razrabotana-rossijskaya-referensnaya-posledovatelnost-genoma-cheloveka-1856166/) | российская референсная последовательность GRCh38.rus и эталонный образец ДНК с методикой оценки точности секвенирования и биоинформатической обработки |
| [Ремедиум, 2026](https://remedium.ru/news/sozdan-natsionalnyy-pangenom-ch/) | национальный пангеном по полным сборкам геномов |
| [Интерфакс, 2024](https://www.interfax.ru/russia/986600) | база популяционных частот вариантов по полногеномным данным |

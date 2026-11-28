# Воспроизводимость Strelka2: 4 потока против 2

Один и тот же BAM основного прогона, `scripts/run_pipeline.sh -w cwl/workflows/call-strelka2.cwl` с `threads=4` и `threads=2`. Записи и байты сравниваются так же, как в `scripts/check_reproducibility.sh`.

| уровень | A | B | совпадает |
|---|---|---|---|
| VCF, байты (sha256) | `5bba5b4d4df9d475` | `5bba5b4d4df9d475` | да |
| VCF, записи | `33743b3b518887a2` | `33743b3b518887a2` | да |
| gVCF, байты (sha256) | `9d03d5afab65c583` | `9d03d5afab65c583` | да |
| gVCF, записи | `d7091558ab3d6485` | `d7091558ab3d6485` | да |
| hap.py giab_v5.0q | `09a71300e45f2f1d` | `09a71300e45f2f1d` | да |
| hap.py giab_v4.2.1 | `e4c01fa3758957a9` | `e4c01fa3758957a9` | да |

**Итог: VCF и gVCF Strelka2 побайтно одинаковые при разном числе потоков.** До исправления D-15 байты различались строкой `##bcftools_viewCommand` с путём и датой, записи совпадали.

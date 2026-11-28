# Воспроизводимость DeepVariant: 4 шарда против 2

Один и тот же BAM основного прогона, `scripts/run_pipeline.sh -w cwl/workflows/call-deepvariant.cwl` с `threads=4` и `threads=2` (это `--num_shards` для make_examples). call_variants (TensorFlow на CPU) в обоих прогонах видел 4 ядра: совпадение при другом числе ядер для TensorFlow этим сравнением не проверено.

| уровень | A | B | совпадает |
|---|---|---|---|
| VCF, байты (sha256) | `0a5463f7b89f9583` | `0a5463f7b89f9583` | да |
| VCF, записи | `5773973b712e5a91` | `5773973b712e5a91` | да |
| gVCF, байты (sha256) | `206f7effd73a6bf9` | `206f7effd73a6bf9` | да |
| gVCF, записи | `cf21e0d86eb2e347` | `cf21e0d86eb2e347` | да |
| hap.py giab_v5.0q | `0b47470673303ead` | `0b47470673303ead` | да |
| hap.py giab_v4.2.1 | `181f6ea89604a88b` | `181f6ea89604a88b` | да |

**Итог: VCF и gVCF DeepVariant побайтно одинаковые при разной нарезке make_examples.**

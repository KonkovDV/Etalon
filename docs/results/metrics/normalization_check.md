# Нормализация concordance.py против bcftools norm

`scripts/check_normalization.sh`: каждый VCF нормализован дважды — `bcftools norm -m -any -f ref` в образе tools и функцией `split_records` из `scripts/concordance.py`; сравниваются наборы (CHROM, POS, REF, ALT, GT без фазы). Символьные аллели (`*`, `<...>`) не учитываются.

| VCF | записей у bcftools norm | только concordance.py | только bcftools norm |
|---|---|---|---|
| HG002.vcf.gz | 3424 | 0 | 0 |
| HG002.strelka2.vcf.gz | 3429 | 0 | 0 |
| HG002.deepvariant.vcf.gz | 4372 | 0 | 0 |
| giab_v5.0q.vcf.gz | 3426 | 0 | 0 |
| giab_v4.2.1.vcf.gz | 3108 | 0 | 0 |

Итог: 17759 записей, расхождений 0.

# ADR-004. Образы: свой для htslib-семейства, готовый для hap.py

**Решение:** htslib, samtools и bcftools собираются из исходников в своём образе; fastp и bwa-mem2 берутся официальными бинарниками с проверкой sha256; hap.py — готовый образ biocontainers по digest.

**Контекст.** Сборка из исходников даёт контроль над флагами (libdeflate, libcurl, S3/GCS) и одну общую libhts для трёх программ, а при сборке можно прогнать их наборы тестов. У hap.py сборка из исходников требует Boost и Python 2 и занимает десятки минут, а выигрыша не даёт. У bwa-mem2 официальный архив содержит бинарники под пять наборов инструкций SIMD и выбирает нужный при запуске.

**Как закреплено.** Базовый образ по digest; пакеты Debian на дату `snapshot.debian.org`, совпадающую с датой сборки базового образа; тарболы через `ADD --checksum`; frontend Dockerfile по digest; образы CI по digest.

**Последствия.** Образ пересобирается с нуля в тот же результат: прогон на пересобранном образе дал побайтно тот же VCF ([REPRODUCIBILITY](../REPRODUCIBILITY.md)). Версию bwa-mem2 нельзя проверять по `bwa-mem2 version` ([D-03](../DEBUGGING.md#d-03)).

**Проверка.** `test_third_party_images_are_pinned_by_digest`, `docs/results/reproducibility_rebuilt_image.md`.

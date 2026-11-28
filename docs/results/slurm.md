# Проверка запуска в Slurm

Одноузловой Slurm 23.11.4 (slurmctld, slurmd, slurmdbd с MariaDB), 4 CPU, Docker вместо Apptainer (`RUNNER=docker`). Учёт задач — [slurm_sacct.txt](slurm_sacct.txt).

| Способ | Задачи Slurm | Итог | Что проверено |
|---|---|---|---|
| `sbatch slurm/run_cwltool_apptainer.sbatch` | 1 | COMPLETED за 1 мин 05 с; порог качества 13 из 13 | весь пайплайн одной задачей; потоки берутся из `SLURM_CPUS_PER_TASK` |
| `toil-cwl-runner --batchSystem slurm` | 12, по одной на шаг | все COMPLETED; VCF и BAM побайтно совпали с cwltool | ресурсы задач взяты из `ResourceRequirement`: `samtools sort` получил 2.50G = 4 × 512 МБ + 512 МБ, `bcftools filter` — 512M; два hap.py шли параллельно |
| `sbatch --array=1-1 slurm/array_cohort.sbatch` | 1 элемент массива | COMPLETED за 50 с; порог качества 5 из 5 | режим когорты: без эталона scatter hap.py пуст, отчёт без раздела точности, образец загружен в SQLite |

`sacct` для первой задачи показал MaxRSS 231 МБ и TotalCPU 4.5 с при том, что шаги внутри контейнеров заняли до 1.1 ГБ и около 66 CPU-секунд: под Docker Slurm не видит процессы контейнеров ([D-10](../DEBUGGING.md#d-10)).

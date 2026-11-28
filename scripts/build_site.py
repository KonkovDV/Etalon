#!/usr/bin/env python3
"""Сайт проекта для GitLab Pages и GitHub Pages.

    python3 scripts/build_site.py --out public
    python3 scripts/build_site.py --out public --run-report results/run/HG002.report.json \\
        --run-html results/run/HG002.report.html --commit "$CI_COMMIT_SHORT_SHA"

Устройство сайта:
  index.html          обзор: что это, результат, с чего начать, как устроено, чем подтверждено
  report/             полный HTML-отчёт прогона (самодостаточный файл из make_report.py)
  docs/index.html     все документы по разделам
  docs/*.html         документы из docs/*.md и корня репозитория, теми же текстами, что на GitHub;
                      у каждой страницы боковое меню разделов, оглавление, крошки и соседние страницы
  sitemap.xml, robots.txt, 404.html, assets/

Числа на главной берутся из report.json прогона и evidence.json, как в README. Внешних запросов
нет: CSP разрешает только свой адрес, шрифты системные, JavaScript на страницах сайта нет.
"""

import argparse
import html
import json
import os
import re
import shutil
import sys
import time

import markdown
from markdown.extensions.toc import slugify_unicode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# frame-ancestors здесь нет: в <meta> браузеры его игнорируют и пишут ошибку в консоль
CSP = "default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'self'; base-uri 'none'; form-action 'none'"

# Разделы сайта по задаче читателя: (название, [(исходник, адрес, название страницы)])
SECTIONS = [
    (
        "Для работодателя",
        [
            ("docs/VACANCY.md", "docs/vacancy.html", "Соответствие вакансии"),
            ("docs/IMPROVEMENTS.md", "docs/improvements.html", "План усиления пайплайна"),
            ("docs/GLOSSARY.md", "docs/glossary.html", "Словарь терминов"),
            ("docs/paper/ARTICLE.md", "docs/article.html", "Черновик статьи"),
            ("docs/paper/ABSTRACT.md", "docs/abstract.html", "Тезисы доклада"),
        ],
    ),
    (
        "Результаты",
        [
            ("docs/SPRAVKA.md", "docs/spravka.html", "Справка"),
            ("docs/RESULTS.md", "docs/results.html", "Аналитический отчёт"),
            ("docs/PRODUCTION.md", "docs/production.html", "Производственный стек и вызыватели"),
            ("docs/METRICS.md", "docs/metrics.html", "Метрика приёмки"),
            ("docs/AGGREGATION.md", "docs/aggregation.html", "База частот"),
            ("docs/RNASEQ.md", "docs/rnaseq.html", "RNA-seq и эталон ERCC"),
            ("docs/REPRODUCIBILITY.md", "docs/reproducibility.html", "Воспроизводимость"),
            ("CLAIMS_REGISTRY.md", "docs/claims.html", "Реестр утверждений"),
        ],
    ),
    (
        "Как устроено",
        [
            ("docs/METHODOLOGY.md", "docs/methodology.html", "Методика"),
            ("PROVENANCE.md", "docs/provenance.html", "Происхождение данных и программ"),
            ("docs/adr/ADR-001-bcftools-caller.md", "docs/adr-001.html", "ADR-001 · вызыватель"),
            ("docs/adr/ADR-002-mini-contig.md", "docs/adr-002.html", "ADR-002 · мини-контиг"),
            ("docs/adr/ADR-003-measure-inside-step.md", "docs/adr-003.html", "ADR-003 · замер в шаге"),
            ("docs/adr/ADR-004-images.md", "docs/adr-004.html", "ADR-004 · образы"),
            ("docs/adr/ADR-005-two-truth-sets.md", "docs/adr-005.html", "ADR-005 · два эталона"),
        ],
    ),
    (
        "Запуск",
        [
            ("docs/QUICKSTART.md", "docs/quickstart.html", "Быстрый старт"),
            ("docs/CLUSTER.md", "docs/cluster.html", "Кластер: Slurm, Toil"),
            ("docs/GITLAB.md", "docs/gitlab.html", "GitLab и CI"),
            ("docs/OFFLINE.md", "docs/offline.html", "Закрытый контур"),
        ],
    ),
    (
        "Сопровождение",
        [
            ("docs/DEBUGGING.md", "docs/debugging.html", "Журнал отладки"),
            ("LIMITS.md", "docs/limits.html", "Область применения"),
            ("docs/ROADMAP.md", "docs/roadmap.html", "Что дальше"),
            ("docs/LITERATURE.md", "docs/literature.html", "Источники"),
        ],
    ),
]
DOCS = {src: (out, title) for _, pages in SECTIONS for src, out, title in pages}
ORDER = [(src, out, title, sec) for sec, pages in SECTIONS for src, out, title in pages]
NAV = [
    ("index.html", "Обзор"),
    ("docs/spravka.html", "Справка"),
    ("docs/results.html", "Результаты"),
    ("report/index.html", "Отчёт прогона"),
    ("docs/methodology.html", "Методика"),
    ("docs/quickstart.html", "Запуск"),
    ("docs/index.html", "Документация"),
]


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def rel(from_page, to_page):
    """Относительная ссылка между страницами сайта (сайт живёт в подкаталоге /<проект>/)."""
    return os.path.relpath(to_page, os.path.dirname(from_page) or ".").replace(os.sep, "/")


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return fh.read()


def load_json(path):
    with open(path if os.path.isabs(path) else os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


def f(x, d=4):
    return "–" if x is None else ("%." + str(d) + "f") % x


# ----------------------------------------------------------------- оболочка страницы


def active_nav(path):
    """Какой пункт главного меню подсветить: свой адрес, иначе для документов — «Документация»."""
    if path in dict(NAV):
        return path
    return "docs/index.html" if path.startswith("docs/") else None


def page(path, title, body, ctx, description=""):
    active = active_nav(path)
    nav = "".join(
        '<li><a href="%s"%s>%s</a></li>'
        % (esc(rel(path, href)), ' aria-current="page"' if href == active else "", esc(label))
        for href, label in NAV
    )
    foot = "".join(
        '<li><a href="%s">%s</a></li>' % (esc(rel(path, out)), esc(title))
        for _, pages in SECTIONS
        for _, out, title in pages
        if not title.startswith("ADR")
    )
    canonical = ('<link rel="canonical" href="%s">' % esc(ctx["site_url"] + path)) if ctx["site_url"] else ""
    return """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161617" media="(prefers-color-scheme: dark)">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:locale" content="ru_RU">
<meta property="og:site_name" content="Etalon">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
{canonical}
<link rel="icon" href="{icon}" type="image/svg+xml">
<link rel="stylesheet" href="{css}">
</head>
<body>
<a class="skip" href="#main">К содержанию</a>
<header class="top"><div class="in">
<a class="brand" href="{home}"><img src="{icon}" alt="" width="26" height="26">Etalon <small>WGS · RNA-seq</small></a>
<nav aria-label="Главное меню"><ul>{nav}</ul></nav>
<a class="gh" href="{repo}">GitHub</a>
</div></header>
{body}
<footer><div class="in">
<ul>{foot}</ul>
<p>Etalon · сборка <code>{commit}</code> от {built} · данные GIAB (NIST) и DeepVariant case study, публичные ·
код под лицензией MIT · <a href="{repo}">исходный код</a></p>
</div></footer>
</body>
</html>
""".format(
        csp=CSP,
        title=esc(title),
        desc=esc(description or title),
        canonical=canonical,
        icon=esc(rel(path, "assets/favicon.svg")),
        css=esc(rel(path, "assets/style.css")),
        home=esc(rel(path, "index.html")),
        nav=nav,
        foot=foot,
        body=body,
        repo=esc(ctx["repo_url"]),
        commit=esc(ctx["commit"]),
        built=esc(ctx["built"]),
    )


def picture(path, name, alt):
    """Четыре варианта картинки: узкий экран (до 700 px) или широкий × светлая или тёмная тема."""

    def a(variant):
        return esc(rel(path, "assets/%s-%s.svg" % (name, variant)))

    return (
        "<picture>"
        '<source media="(max-width: 700px) and (prefers-color-scheme: dark)" srcset="%s">'
        '<source media="(max-width: 700px)" srcset="%s">'
        '<source media="(prefers-color-scheme: dark)" srcset="%s">'
        '<img src="%s" alt="%s" width="1200" loading="lazy"></picture>'
        % (a("narrow-dark"), a("narrow-light"), a("dark"), a("light"), esc(alt))
    )


# Фото главной страницы (site/img): по два размера WebP, описание — в site/img/README.md
PHOTO_W, PHOTO_H = 1536, 1024


def photo(path, name, alt, eager=False, sizes="(max-width: 980px) calc(100vw - 32px), 540px", cls="photo"):
    """Фото в двух размерах: телефон берёт файл 768 px, широкий экран — 1536 px. Первое фото грузится сразу."""

    def a(suffix):
        return esc(rel(path, "assets/img/%s%s.webp" % (name, suffix)))

    load = ' fetchpriority="high"' if eager else ' loading="lazy" decoding="async"'
    return (
        '<figure class="%s"><img src="%s" srcset="%s 768w, %s 1536w" sizes="%s" width="%d" height="%d" '
        'alt="%s"%s></figure>' % (cls, a(""), a("-768"), a(""), esc(sizes), PHOTO_W, PHOTO_H, esc(alt), load)
    )


def media(photo_html, body_html, flip=False):
    """Фото рядом с текстом; flip ставит фото справа на широком экране, на телефоне оно всегда первое."""
    return '<div class="split media%s">%s<div>%s</div></div>' % (" flip" if flip else "", photo_html, body_html)


def table(header, rows, num=()):
    out = ['<div class="scroll" tabindex="0" role="region" aria-label="Таблица"><table><thead><tr>']
    out += [
        '<th class="num" scope="col">%s</th>' % esc(h) if i in num else '<th scope="col">%s</th>' % esc(h)
        for i, h in enumerate(header)
    ]
    out.append("</tr></thead><tbody>")
    for r in rows:
        out.append(
            "<tr>"
            + "".join('<td class="num">%s</td>' % c if i in num else "<td>%s</td>" % c for i, c in enumerate(r))
            + "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


# ----------------------------------------------------------------- главная


def index_page(ev, run, ctx):
    """Обзор проекта: от главного к деталям. Каждое число — из evidence.json или отчёта прогона."""
    c = ev["claims"]
    p = "index.html"
    checks = run.get("checks", [])
    passed = sum(1 for x in checks if x["pass"])
    ok = bool(checks) and passed == len(checks)
    status = '<span class="status %s">%s порог качества: %d из %d</span>' % (
        "ok" if ok else "fail",
        "✓" if ok else "✕",
        passed,
        len(checks),
    )

    def link(page_, label, cls="btn link"):
        return '<a class="%s" href="%s">%s</a>' % (cls, esc(rel(p, page_)), esc(label))

    def metric(value, title, note, href):
        return (
            '<div class="metric"><div class="v">%s</div><div class="k"><a href="%s">%s</a></div>'
            '<div class="s">%s</div></div>' % (esc(value), esc(rel(p, href)), esc(title), esc(note))
        )

    def findings(items):
        return '<ul class="findings">%s</ul>' % "".join(
            "<li><b>%s</b><span>%s</span></li>" % (esc(t), esc(s_)) for t, s_ in items
        )

    def figure(name, alt, caption):
        return "<figure>%s<figcaption>%s</figcaption></figure>" % (picture(p, name, alt), esc(caption))

    def section(sid, eyebrow, title, lead, body, alt=False):
        return (
            '<section class="section%s" id="%s" aria-labelledby="%s-h"><div class="wrap">'
            '<span class="eyebrow">%s</span><h2 class="headline" id="%s-h">%s</h2>%s%s</div></section>'
            % (
                " alt" if alt else "",
                sid,
                sid,
                esc(eyebrow),
                sid,
                esc(title),
                '<p class="lead">%s</p>' % esc(lead) if lead else "",
                body,
            )
        )

    b = ['<main id="main" class="home">']

    # 1. главное в одном экране
    b.append(
        '<section class="hero" aria-labelledby="hero-h"><div class="wrap">'
        '<span class="eyebrow">Открытый проект Etalon</span>'
        '<h1 id="hero-h">Пайплайны WGS и RNA-seq со сверкой с эталонными образцами</h1>'
        '<p class="lead">Варианты сверяются с эталоном GIAB HG002, экспрессия — со spike-in ERCC. Точность '
        "считается с 95 %% интервалами и отдельно по типам участков генома, прогоны воспроизводятся побайтно. "
        "Каждое число воспроизводится одной командой.</p>"
        '<p class="actions">%s%s%s%s</p>'
        '<p class="meta">%s · сборка <code>%s</code> · все числа на сайте сверены с данными в CI</p>'
        "%s</div></section>"
        % (
            link("docs/results.html", "Результаты", "btn primary"),
            link("docs/vacancy.html", "Соответствие вакансии"),
            link("docs/spravka.html", "Справка на одну страницу"),
            '<a class="btn link" href="%s">Исходный код</a>' % esc(ctx["repo_url"]),
            status,
            esc(ctx["commit"]),
            photo(
                p,
                "workplace",
                "Светлое рабочее место у большого окна с видом на осенний парк — ноутбук и два "
                "монитора с графиками, стеклянная модель ДНК, чашка чая",
                eager=True,
                sizes="(max-width: 1160px) calc(100vw - 32px), 1076px",
                cls="photo hero-photo",
            ),
        )
    )

    # 2. шесть чисел
    b.append(
        '<section class="section tight" aria-labelledby="nums-h"><div class="wrap">'
        '<h2 class="vh" id="nums-h">Основные числа</h2><div class="metrics">'
        + metric(
            "%s из %s" % (c["repro_comparisons"], c["repro_comparisons"]),
            "VCF совпал побайтно",
            "другое число потоков, Toil на Slurm, пересобранный образ, другая машина, пять сборок bwa-mem2",
            "docs/reproducibility.html",
        )
        + metric(
            c["strelka2_snp_v5_f1"],
            "SNV F1, Strelka2",
            "GIAB v5.0q, 95 %% ДИ %s; тот же BAM, что у bcftools и DeepVariant" % c["strelka2_snp_v5_f1_ci"],
            "docs/production.html",
        )
        + metric(
            c["rnaseq_fc_pearson"],
            "RNA-seq против ERCC",
            "корреляция измеренной кратности с известной; наклон линейности %s–%s при теоретической 1"
            % (c["rnaseq_slope_min"], c["rnaseq_slope_max"]),
            "docs/rnaseq.html",
        )
        + metric(
            "до %s %%" % c["repr_share_max"],
            "различий по ключу — запись",
            "одна и та же вариация у разных программ; %s случаев из %s подтверждены сборкой гаплотипов"
            % (c["repr_loci_verified"], c["repr_loci_total"]),
            "docs/aggregation.html",
        )
        + metric(
            "%s–%s %%" % (c["depth_f145_bcftools_share_v421"], c["depth_f145_dv_share_v421"]),
            "эталона в знаменателе F на %sx" % c["depth_f145_x"],
            "F при этом 100 % у всех трёх вызывателей, поэтому рядом с F нужна эта доля",
            "docs/metrics.html#f-и-глубина",
        )
        + metric(
            c["debug_cases"],
            "разобранных ошибок",
            "от теста htslib за прокси до гистограммы fastp, которую строит один поток из N; с патчем",
            "docs/debugging.html",
        )
        + "</div></div></section>"
    )

    # 2a. вакансия: обязанности и что по каждой сделано
    duties = (
        (
            "Пайплайны WGS и RNA-seq",
            "%s инструментов CWL v1.2: три вызывателя на одном BAM, сверка с GIAB HG002 и ERCC." % c["cwl_tools"],
        ),
        (
            "Сборка и установка программ",
            "htslib, samtools, bcftools и featureCounts — из исходников с их тестами; у bcftools пройдено %s из %s."
            % (c["bcftools_tests_passed"], c["bcftools_tests_total"]),
        ),
        (
            "Отладка чужого кода",
            "Разобрано ошибок: %s; ошибка fastp исправлена патчем из трёх строк." % c["debug_cases"],
        ),
        (
            "Документация, отчёты и справки",
            "Методика, решения ADR, справка на одну страницу, аналитический отчёт, черновик статьи и тезисы.",
        ),
    )
    b.append(
        section(
            "vacancy",
            "Вакансия «Биоинформатик-программист»",
            "Каждая обязанность — готовый результат",
            "Обязанности и требования вакансии сопоставлены с файлами, командами и числами проекта.",
            media(
                photo(
                    p,
                    "team",
                    "Четверо коллег у экрана с графиками в светлой переговорной; объясняет женщина, все улыбаются",
                ),
                findings(duties)
                + '<p class="actions start">%s%s</p>'
                % (
                    link("docs/vacancy.html", "Соответствие вакансии", "btn primary"),
                    link("docs/glossary.html", "Словарь терминов"),
                ),
            ),
        )
    )

    # 3. два пайплайна
    duo = (
        '<div class="duo">'
        '<div class="panel"><h3>WGS</h3><ul class="flow" aria-label="Шаги WGS">'
        "<li>FASTQ</li><li>fastp</li><li>bwa-mem2</li><li>samtools</li><li>bcftools · Strelka2 · DeepVariant</li>"
        "<li>hap.py</li></ul><dl>"
        "<dt>Эталон</dt><dd>GIAB HG002 v5.0q и v4.2.1, страты GIAB v3.6</dd>"
        "<dt>Данные</dt><dd>NovaSeq 6000, 2×151, %s пар ридов, %sx, chr20 2 Мб</dd>"
        "<dt>Точность</dt><dd>SNV F1 %s–%s, инделы %s–%s у трёх вызывателей</dd>"
        "<dt>Ресурсы</dt><dd>шаги вместе %s с, пик %s МБ; замер внутри шага</dd></dl></div>"
        '<div class="panel"><h3>RNA-seq</h3><ul class="flow" aria-label="Шаги RNA-seq">'
        "<li>FASTQ</li><li>fastp</li><li>STAR</li><li>featureCounts</li><li>ERCC</li></ul><dl>"
        "<dt>Эталон</dt><dd>92 транскрипта ERCC в смесях Mix 1 и Mix 2</dd>"
        "<dt>Данные</dt><dd>UHR и HBR, по три реплики, 2×100, chr22</dd>"
        "<dt>Линейность</dt><dd>наклон %s–%s при теоретической 1, R² ≥ %s</dd>"
        "<dt>Кратность</dt><dd>4 : 1, 1 : 1, 2 : 3, 1 : 2 — корреляция с известной %s</dd></dl></div>"
        "</div>"
        % tuple(
            esc(x)
            for x in (
                "{:,}".format(int(c["read_pairs"])).replace(",", "\u00a0"),
                c["mean_depth"],
                c["bcftools_snp_v5_f1"],
                c["dv_snp_v5_f1"],
                c["bcftools_indel_v5_f1"],
                c["dv_indel_v5_f1"],
                c["total_wall_s"],
                c["max_peak_rss_mb"],
                c["rnaseq_slope_min"],
                c["rnaseq_slope_max"],
                c["rnaseq_r2_min"],
                c["rnaseq_fc_pearson"],
            )
        )
    )
    b.append(
        section(
            "pipelines",
            "Как устроено",
            "Два пайплайна с общей сборкой и запуском",
            "Шаги описаны на CWL v1.2, программы работают в Docker-образах, закреплённых по digest; htslib, "
            "samtools, bcftools, featureCounts и fastp собираются из исходников вместе со своими тестами. Время, "
            "CPU и пик памяти меряются внутри каждого шага. Запуск — cwltool, Toil или Slurm, проверки — "
            "GitHub Actions и GitLab CI.",
            duo
            + figure(
                "pipeline",
                "Схема WGS: риды, fastp, bwa-mem2, samtools, bcftools, hap.py, с временем и памятью каждого шага",
                "Шаги WGS со временем и пиком памяти, измеренными внутри шага, на 4 потоках.",
            ),
            alt=True,
        )
    )

    # 4. точность WGS
    b.append(
        section(
            "accuracy",
            "Точность WGS",
            "Где ошибается вызов вариантов",
            "Вызовы сверяются с эталоном по гаплотипам (hap.py, GA4GH) и раскладываются по стратам GIAB. "
            "У каждой доли есть 95 % интервал: без него разницу в десятые доли процента не отличить от шума.",
            media(
                photo(
                    p,
                    "lab",
                    "Учёная в белом халате и голубых перчатках ставит пробирку с образцом в секвенатор "
                    "в светлой лаборатории",
                ),
                findings(
                    [
                        (
                            "От эталона зависит не меньше, чем от программы",
                            "Одни и те же вызовы на v4.2.1 и v5.0q расходятся по F1 инделов на 7 п. п.: в v5.0q "
                            "вошли сложные участки.",
                        ),
                        (
                            "Ошибки сосредоточены в повторах",
                            "Вне сложных участков SNV F1 %s, в тандемных повторах — %s."
                            % (c["snp_v5_easy_f1"], c["snp_v5_tr_f1"]),
                        ),
                        (
                            "Strelka2 точнее bcftools, DeepVariant не точнее Strelka2",
                            "На одном BAM SNV F1 %s у Strelka2 и %s у DeepVariant; CPU у DeepVariant в %s раза больше."
                            % (c["strelka2_snp_v5_f1"], c["dv_snp_v5_f1"], c["dv_vs_strelka2_cpu_x"]),
                        ),
                    ]
                ),
            )
            + figure(
                "accuracy",
                "F1 с 95 % интервалами по участкам генома для SNV и инделов на эталонах v5.0q и v4.2.1",
                "F1 с 95 % интервалом по стратификациям GIAB v3.6, эталонный прогон bcftools.",
            ),
        )
    )

    # 5. метрика приёмки и глубина
    b.append(
        section(
            "metric",
            "Эталонный образец",
            "Что видит метрика приёмки и чего не видит",
            "Доля совпавших генотипов (патент RU 2846268, порог 99,9 %%) посчитана рядом с GA4GH на тех же "
            "вызовах и на данных, прореженных до %s–%sx. Это дополнение к методике, а не замена."
            % (c["depth_min_x"], c["depth_max_x"]),
            findings(
                [
                    (
                        "Порог зависит от эталона",
                        "На v4.2.1 его проходит %s вызыватель из трёх, на v5.0q — %s: в v5.0q есть сложные участки."
                        % (c["patent_pass_v421"], c["patent_pass_v5"]),
                    ),
                    (
                        "Пропуски и лишние вызовы в F не входят",
                        "Пайплайн, который стал пропускать варианты, F не ухудшит; это видят recall и precision.",
                    ),
                    (
                        "На малой глубине F растёт",
                        "На %sx F = 100 %% у всех трёх вызывателей: фильтр sum(AD) > 10 оставляет в знаменателе "
                        "%s–%s %% эталона. Рядом с F нужна эта доля или recall."
                        % (
                            c["depth_f145_x"],
                            c["depth_f145_bcftools_share_v421"],
                            c["depth_f145_dv_share_v421"],
                        ),
                    ),
                ]
            )
            + figure(
                "depth",
                "Три графика от глубины 5–35x для bcftools, Strelka2 и DeepVariant: F1 на GIAB v5.0q, F по "
                "патенту с порогом 99,9 % и доля эталона в знаменателе F",
                "F1 по GA4GH, F по формуле патента и доля эталона, вошедшая в знаменатель F, на прореженных "
                "данных HG002.",
            ),
            alt=True,
        )
    )

    # 6. база частот
    rows = []
    for a, bb, tag in (
        ("bcftools", "Strelka2", "bcftools_strelka2"),
        ("bcftools", "DeepVariant", "bcftools_dv"),
        ("Strelka2", "DeepVariant", "strelka2_dv"),
    ):
        rows.append(
            [
                esc("%s / %s" % (a, bb)),
                esc(c["repr_%s_raw" % tag]),
                esc(c["repr_%s_split" % tag]),
                esc(c["repr_%s_same" % tag]),
                esc(c["repr_%s_real" % tag]),
                esc("%s %%" % c["repr_%s_share" % tag]),
            ]
        )
    b.append(
        section(
            "aggregation",
            "База популяционных частот",
            "Одна и та же вариация, разные записи",
            "В базе частот вариант — это ключ CHROM, POS, REF, ALT. Три программы на одном BAM пишут одни и те же "
            "варианты по-разному, и при сравнении по ключу часть «различий» оказывается одной вариацией.",
            media(
                photo(
                    p,
                    "family",
                    "Бабушка, мама, папа и маленькая дочка гуляют по аллее осеннего парка; девочка "
                    "смеётся, повиснув на руках бабушки и мамы",
                ),
                findings(
                    [
                        (
                            "Нормализация нужна, но её мало",
                            "Разбиение мультиаллельных записей убирает %s–%s %% различий; сложные события в повторах "
                            "совпадают только по гаплотипам." % (c["repr_split_share_min"], c["repr_split_share_max"]),
                        ),
                        (
                            "Каждый такой случай проверен без hap.py",
                            "Гаплотипы собраны из референса перебором фаз и совпали в %s случаях из %s."
                            % (c["repr_loci_verified"], c["repr_loci_total"]),
                        ),
                        (
                            "AN — по образцам с известным генотипом",
                            "В когорте разной глубины AF гетерозигот при AN = 2N — %s, по генотипам с GQ ≥ %s — %s."
                            % (c["cohort_all_het_naive"], c["callable_gq_min"], c["cohort_all_het_honest"]),
                        ),
                    ]
                ),
                flip=True,
            )
            + table(
                ["пара", "различий по ключу", "убрало разбиение", "тот же гаплотип", "настоящих", "доля записи"],
                rows,
                num=(1, 2, 3, 4, 5),
            ),
        )
    )

    # 7. RNA-seq
    b.append(
        section(
            "rnaseq",
            "RNA-seq",
            "Экспрессия против известных концентраций",
            "UHR и HBR со spike-in ERCC: 92 транскрипта известной концентрации в двух смесях, различающихся "
            "в 4, 1, 2/3 и 1/2 раза. Пайплайн STAR + featureCounts проверяется по тем же правилам, что и WGS.",
            findings(
                [
                    (
                        "Отклик линейный",
                        "Наклон %s–%s, интервал накрывает 1 у %s образцов из 6; R² ≥ %s."
                        % (
                            c["rnaseq_slope_min"],
                            c["rnaseq_slope_max"],
                            c["rnaseq_slope_ci_cover_1"],
                            c["rnaseq_r2_min"],
                        ),
                    ),
                    (
                        "Кратность измерена почти без смещения",
                        "После поправки на долю мРНК (×%s) корреляция с известной %s, RMSE %s log2."
                        % (c["rnaseq_fc_offset"], c["rnaseq_fc_pearson"], c["rnaseq_fc_rmse"]),
                    ),
                    (
                        "Маркерные гены и реплики",
                        "%s маркерных генов chr22 изменились в ожидаемую сторону; реплики коррелируют не ниже %s."
                        % (c["rnaseq_markers"], c["rnaseq_rep_within_min"]),
                    ),
                ]
            )
            + figure(
                "ercc",
                "Линейность ERCC в шести образцах и кратность UHR/HBR по подгруппам A–D против известной",
                "Линейность по ERCC в шести образцах и кратность по подгруппам A–D против известной.",
            ),
            alt=True,
        )
    )

    # 8. инженерия
    cards = (
        (
            "docs/reproducibility.html",
            "VCF совпал в %s сравнениях из %s" % (c["repro_comparisons"], c["repro_comparisons"]),
            "Потоки, Toil на Slurm, пересобранный образ, другая машина за прокси, пять сборок bwa-mem2.",
            "Воспроизводимость",
        ),
        (
            "docs/debugging.html#d-23",
            "fastp строит гистограмму вставки в одном потоке",
            "При N потоках в неё попадает каждая N-я пачка ридов. Патч из трёх строк делает её одинаковой при любом "
            "числе потоков.",
            "D-23",
        ),
        (
            "docs/debugging.html#d-05",
            "fastp в 19 раз медленнее из-за одного флага",
            "Автоопределение адаптеров для парных ридов — отдельный однопоточный проход: %s → %s с без него."
            % (c["fastp_before_s"], c["fastp_after_s"]),
            "D-05",
        ),
        (
            "docs/debugging.html#d-20",
            "STAR и границы бинов сортировки",
            "Повтор на тех же потоках давал другие байты BAM; теперь BAM переписывается блоками htslib.",
            "D-20",
        ),
    )
    b.append(
        section(
            "engineering",
            "Инженерия",
            "Воспроизводимость и чужой код",
            "Прогоны сравниваются побайтно, по sha256 выходных файлов. Каждое расхождение разобрано до причины, "
            "в том числе в чужом коде.",
            media(
                photo(
                    p,
                    "twins",
                    "Две одинаковые стеклянные модели двойной спирали ДНК стоят рядом на белом столе, "
                    "свет рисует под ними одинаковые блики",
                ),
                '<div class="cards">%s</div>'
                % "".join(
                    '<a class="card" href="%s"><b>%s</b><span>%s</span><em>%s</em></a>'
                    % (esc(rel(p, h)), esc(t), esc(s_), esc(m))
                    for h, t, s_, m in cards
                ),
            ),
        )
    )

    # 9. запуск
    steps = [
        ("make setup && source .venv/bin/activate", "cwltool и инструменты разработки"),
        ("make image data run", "образ из исходников с тестами, данные HG002, прогон с отчётом и порогом качества"),
        ("make callers metric", "Strelka2 и DeepVariant на том же BAM, метрика патента рядом с GA4GH"),
        ("make depth aggregation", "серия по глубине 5–35x и проверки для базы частот"),
        ("make rnaseq-image rnaseq-data rnaseq", "RNA-seq: STAR, featureCounts, сверка с ERCC"),
        ("make repro", "два прогона и побайтное сравнение"),
    ]
    b.append(
        section(
            "run",
            "Запуск",
            "От чистой машины до отчёта",
            "Нужны Docker и Python. Прогон WGS идёт около минуты, поэтому его можно повторять на каждый коммит. "
            "Эталон, референс и пороги задаются в job-файле, код при этом не меняется.",
            '<ol class="steps">%s</ol><p class="actions start">%s%s</p>'
            % (
                "".join("<li><code>%s</code><span>%s</span></li>" % (esc(cmd), esc(note)) for cmd, note in steps),
                link("docs/quickstart.html", "Быстрый старт"),
                link("docs/cluster.html", "Кластер: Slurm, Toil, Apptainer"),
            ),
            alt=True,
        )
    )

    # 10. документация
    doc_cards = []
    for _, pages in SECTIONS:
        for src, out, title in pages:
            if title.startswith("ADR"):
                continue
            doc_cards.append(
                '<a class="card" href="%s"><b>%s</b><span>%s</span></a>'
                % (esc(rel(p, out)), esc(title), esc(first_sentence(src)))
            )
    b.append(
        section(
            "docs",
            "Документация",
            "Документы проекта",
            "Справка, методика, результаты, журнал отладки, границы применимости и источники. Те же тексты лежат "
            "в репозитории.",
            media(
                photo(
                    p,
                    "report",
                    "Женщина у окна с видом на осенний парк читает распечатанную справку на одной "
                    "странице с графиком и таблицей; на столе чай, маркер и очки",
                ),
                "<h3>Главное — на одной странице</h3>"
                "<p>Справка: цель, материалы, методы, результаты, выводы, предложения и ограничения. Каждое число в "
                "ней сверяется с данными в CI, а подробности — по ссылкам на документы.</p>"
                '<p class="actions start">%s%s</p>'
                % (
                    link("docs/spravka.html", "Открыть справку", "btn primary"),
                    link("docs/results.html", "Аналитический отчёт"),
                ),
                flip=True,
            )
            + '<div class="cards">%s</div>' % "".join(doc_cards),
        )
    )
    b.append("</main>")
    return page(
        p,
        "Etalon — точность пайплайнов WGS и RNA-seq по эталонным образцам",
        "\n".join(b),
        ctx,
        description="Открытый проект: WGS и RNA-seq со сверкой с эталонами GIAB HG002 и ERCC, побайтно "
        "воспроизводимые прогоны, CWL, Docker, Slurm. SNV F1 %s, VCF совпал в %s сравнениях из %s."
        % (c["strelka2_snp_v5_f1"], c["repro_comparisons"], c["repro_comparisons"]),
    )


# ----------------------------------------------------------------- документы


# srcset too: a <picture> in Markdown keeps its dark-theme variant there
LINK = re.compile(r'(href|src|srcset)="([^"#:]+?)(#[^"]*)?"')


def rewrite_links(html_text, src_md, out_page, ctx):
    """Ссылки из Markdown: на опубликованные документы — на их страницы, на код — в репозиторий."""
    src_dir = os.path.dirname(src_md)

    def fix(m):
        attr, target, anchor = m.group(1), m.group(2), m.group(3) or ""
        repo_path = os.path.normpath(os.path.join(src_dir, target)).replace(os.sep, "/")
        if repo_path in DOCS:
            return '%s="%s%s"' % (attr, rel(out_page, DOCS[repo_path][0]), anchor)
        if repo_path == "docs/results/reference/HG002.report.html":
            return '%s="%s%s"' % (attr, rel(out_page, "report/index.html"), anchor)
        if repo_path.startswith("docs/assets/"):
            return '%s="%s"' % (attr, rel(out_page, "assets/" + os.path.basename(repo_path)))
        if repo_path == "README.md":
            return '%s="%s"' % (attr, rel(out_page, "index.html"))
        if repo_path in ("docs/README.md", "docs/adr"):
            return '%s="%s"' % (attr, rel(out_page, "docs/index.html"))
        kind = "tree" if target.endswith("/") or os.path.isdir(os.path.join(ROOT, repo_path)) else "blob"
        return '%s="%s/%s/main/%s%s"' % (
            attr,
            ctx["repo_url"],
            kind if not ctx["gitlab"] else "-/" + kind,
            repo_path,
            anchor,
        )

    return LINK.sub(fix, html_text)


def sidebar(path):
    out = []
    for sec, pages in SECTIONS:
        items = "".join(
            '<li><a href="%s"%s>%s</a></li>'
            % (esc(rel(path, out_)), ' aria-current="page"' if out_ == path else "", esc(title))
            for _, out_, title in pages
        )
        out.append("<p>%s</p><ul>%s</ul>" % (esc(sec), items))
    return "".join(out)


def toc_html(tokens):
    items = []
    for t in tokens:  # h1 is the page title; its children are the h2 sections
        for h2 in t.get("children", []):
            sub = "".join('<li><a href="#%s">%s</a></li>' % (esc(h3["id"]), h3["name"]) for h3 in h2["children"])
            items.append(
                '<li><a href="#%s">%s</a>%s</li>' % (esc(h2["id"]), h2["name"], "<ul>%s</ul>" % sub if sub else "")
            )
    return "<ul>%s</ul>" % "".join(items) if len(items) > 1 else ""


# a <picture> written in Markdown: light and dark variants of one figure from docs/assets
MD_PICTURE = re.compile(
    r'<picture>\s*<source media="\(prefers-color-scheme: dark\)" srcset="[^"]*?([\w-]+)-dark\.svg">\s*'
    r'<img src="[^"]*?\1-light\.svg" alt="([^"]*)"[^>]*>\s*</picture>'
)


def with_narrow_variants(html_text, out_page):
    """На телефоне широкая картинка нечитаема: если у неё есть узкий вариант, подставить все четыре."""

    def fix(m):
        name, alt = m.group(1), html.unescape(m.group(2))
        if not os.path.exists(os.path.join(ROOT, "docs", "assets", "%s-narrow-light.svg" % name)):
            return m.group(0)
        return picture(out_page, name, alt)

    return MD_PICTURE.sub(fix, html_text)


def doc_page(src, out, title, ctx):
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )
    body = md.convert(read(src))
    # scrollable regions must be reachable from the keyboard (WCAG 2.1.1; axe scrollable-region-focusable)
    body = body.replace("<table>", '<div class="scroll" tabindex="0" role="region" aria-label="Таблица"><table>')
    body = body.replace("</table>", "</table></div>").replace("<pre>", '<pre tabindex="0">')
    body = with_narrow_variants(rewrite_links(body, src, out, ctx), out)
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    page_title = re.sub(r"<[^>]+>", "", m.group(1)) if m else title
    toc = toc_html(md.toc_tokens)

    i = next(k for k, item in enumerate(ORDER) if item[0] == src)
    sec = ORDER[i][3]
    prev_, next_ = (ORDER[i - 1] if i > 0 else None), (ORDER[i + 1] if i + 1 < len(ORDER) else None)
    pager = '<nav class="pager" aria-label="Соседние страницы">'
    if prev_:
        pager += '<a class="prev" href="%s"><small>Назад</small>%s</a>' % (esc(rel(out, prev_[1])), esc(prev_[2]))
    if next_:
        pager += '<a class="next" href="%s"><small>Дальше</small>%s</a>' % (esc(rel(out, next_[1])), esc(next_[2]))
    pager += "</nav>"
    crumbs = (
        '<nav class="crumbs" aria-label="Путь"><a href="%s">Обзор</a> › <a href="%s#%s">%s</a> › '
        '<span aria-current="page">%s</span></nav>'
        % (
            esc(rel(out, "index.html")),
            esc(rel(out, "docs/index.html")),
            esc(slugify_unicode(sec, "-")),
            esc(sec),
            esc(title),
        )
    )
    source = '<p class="meta src">Исходник страницы: <a href="%s/%s/main/%s">%s</a></p>' % (
        ctx["repo_url"],
        "-/blob" if ctx["gitlab"] else "blob",
        src,
        esc(src),
    )

    layout = [
        '<div class="layout">',
        '<nav class="side" aria-label="Документация">%s</nav>' % sidebar(out),
        '<main id="main" class="doc">',
        crumbs,
        '<details class="side-m"><summary>Все разделы</summary>%s</details>' % sidebar(out),
    ]
    if toc:
        layout.append('<details class="toc-m"><summary>На этой странице</summary>%s</details>' % toc)
    layout += [body, source, pager, "</main>"]
    if toc:
        layout.append('<aside class="toc" aria-label="На этой странице"><p>На этой странице</p>%s</aside>' % toc)
    layout.append("</div>")
    return page(out, "%s · Etalon" % page_title, "\n".join(layout), ctx)


def first_sentence(src):
    """Первое предложение после заголовка документа: подпись к его карточке."""
    for block in read(src).split("\n\n")[1:]:
        text = block.strip()
        if text and not text.startswith(("#", "|", "-", "*", "<", "`", "1.")):
            text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", re.sub(r"<!--.*?-->", "", text))
            text = text.replace("**", "").replace("`", "")
            # «Цель. Убедиться, что…»: короткую метку в начале абзаца склеить со следующим предложением
            parts, out = re.split(r"(?<=[.:])\s", text), ""
            for part in parts:
                out = (out + " " + part).strip()
                if len(out) >= 40:
                    break
            return out.rstrip(".:")[:170]
    return ""


def docs_index(ctx):
    p = "docs/index.html"
    intro = {
        "Для работодателя": "требования вакансии и их подтверждение, план усиления пайплайна, словарь, статья и тезисы",
        "Результаты": "что получилось, с какой точностью и как получить каждое число заново",
        "Как устроено": "почему выбраны эти данные, инструменты и параметры; откуда взяты данные и программы",
        "Запуск": "как запустить на своей машине, на кластере Slurm и в GitLab CI",
        "Сопровождение": "найденные ошибки, ограничения, планы и источники",
    }
    b = [
        '<main id="main" class="home">',
        "<h1>Документация</h1>",
        '<p class="lead">Те же тексты, что в репозитории, разложенные по разделам. Проще всего начать с '
        '<a href="%s">быстрого старта</a> или с <a href="%s">отчёта прогона</a>.</p>'
        % (esc(rel(p, "docs/quickstart.html")), esc(rel(p, "report/index.html"))),
    ]
    for sec, pages in SECTIONS:
        b.append(
            '<h2 id="%s">%s</h2><p class="meta">%s</p>' % (esc(slugify_unicode(sec, "-")), esc(sec), esc(intro[sec]))
        )
        b.append(
            '<div class="grid2">'
            + "".join(
                '<a class="card" href="%s"><b>%s</b><span>%s</span></a>'
                % (esc(rel(p, out)), esc(title), esc(first_sentence(src)))
                for src, out, title in pages
            )
            + "</div>"
        )
    b.append("</main>")
    return page(p, "Документация · Etalon", "\n".join(b), ctx)


def report_page(src_html):
    """Отчёт прогона как есть, плюс строка навигации обратно на сайт."""
    with open(src_html, encoding="utf-8") as fh:
        text = fh.read()
    back = (
        '<p class="note"><a href="../index.html">← Etalon: обзор</a> · <a href="../docs/results.html">'
        'аналитический отчёт</a> · <a href="../docs/methodology.html">методика</a></p>'
    )
    return text.replace("<main>", "<main>" + back, 1)


def not_found(ctx):
    body = (
        '<main id="main" class="home"><h1>Страница не найдена</h1><p>Такого адреса на сайте нет. '
        '<a href="index.html">Обзор проекта</a> · <a href="docs/index.html">Документация</a></p></main>'
    )
    return page("404.html", "Страница не найдена · Etalon", body, ctx)


def sitemap(pages, site_url):
    urls = "".join("<url><loc>%s%s</loc></url>" % (esc(site_url), esc(p)) for p in sorted(pages) if p != "404.html")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "%s</urlset>\n" % urls
    )


# ----------------------------------------------------------------- сборка


def build(args):
    ev = load_json("evidence.json")
    run = load_json(args.run_report)
    site_url = args.site_url.rstrip("/") + "/" if args.site_url else ""
    ctx = {
        "repo_url": args.repo_url.rstrip("/"),
        "gitlab": "gitlab" in args.repo_url,
        "site_url": site_url,
        "commit": args.commit or "local",
        "built": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    out = args.out
    if os.path.exists(out):
        shutil.rmtree(out)
    for sub in ("assets", "assets/img", "docs", "report"):
        os.makedirs(os.path.join(out, sub))
    for name in ("style.css", "favicon.svg"):
        shutil.copy(os.path.join(ROOT, "site", name), os.path.join(out, "assets", name))
    for name in sorted(os.listdir(os.path.join(ROOT, "site", "img"))):
        if name.endswith(".webp"):
            shutil.copy(os.path.join(ROOT, "site", "img", name), os.path.join(out, "assets", "img", name))
    for name in sorted(os.listdir(os.path.join(ROOT, "docs", "assets"))):
        if name.endswith(".svg"):
            shutil.copy(os.path.join(ROOT, "docs", "assets", name), os.path.join(out, "assets", name))
    shutil.copy(args.run_report, os.path.join(out, "report", "report.json"))

    pages = {
        "index.html": index_page(ev, run, ctx),
        "404.html": not_found(ctx),
        "docs/index.html": docs_index(ctx),
        "report/index.html": report_page(args.run_html),
    }
    for src, (dst, title) in DOCS.items():
        pages[dst] = doc_page(src, dst, title, ctx)
    for dst, text in pages.items():
        with open(os.path.join(out, dst), "w", encoding="utf-8") as fh:
            fh.write(text)
    if site_url:
        with open(os.path.join(out, "sitemap.xml"), "w", encoding="utf-8") as fh:
            fh.write(sitemap(pages, site_url))
        with open(os.path.join(out, "robots.txt"), "w", encoding="utf-8") as fh:
            fh.write("User-agent: *\nAllow: /\nSitemap: %ssitemap.xml\n" % site_url)
    print("site: %d pages -> %s" % (len(pages), out))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", default="public")
    p.add_argument(
        "--run-report",
        default=os.path.join(ROOT, "docs/results/reference/HG002.report.json"),
        help="report.json of the run to show (CI: results/run/HG002.report.json)",
    )
    p.add_argument("--run-html", default=os.path.join(ROOT, "docs/results/reference/HG002.report.html"))
    p.add_argument("--repo-url", default=os.environ.get("CI_PROJECT_URL", "https://github.com/KonkovDV/Etalon"))
    p.add_argument(
        "--site-url",
        default=os.environ.get("CI_PAGES_URL", "https://konkovdv.github.io/Etalon/"),
        help="public address of the site, for canonical links and sitemap.xml",
    )
    p.add_argument("--commit", default=os.environ.get("CI_COMMIT_SHORT_SHA") or os.environ.get("GITHUB_SHA", "")[:8])
    return build(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())

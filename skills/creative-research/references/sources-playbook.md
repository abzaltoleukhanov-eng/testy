# Где и как искать

## Площадки для сумок

| Площадка | Что искать | Пример запроса |
|---|---|---|
| Reddit | треды с болями, выбором, сравнениями | `site:reddit.com tote bag shoulder pain laptop`, `site:reddit.com r/HerOneBag tote backpack convertible` |
| Сабреддиты | r/HerOneBag, r/onebag, r/travel, r/solotravel, r/handbags, r/BuyItForLife, r/digitalnomad, r/flightattendants, r/AskWomenOver30, r/AskWomenOver40, r/backpacking, r/TravelHacks | `site:reddit.com/r/HerOneBag personal item tote` |
| Mumsnet (UK) | женщины 35–60+, честные мнения о брендах, в том числе о Nordace | `site:mumsnet.com nordace`, `site:mumsnet.com travel tote bag` |
| Trustpilot | отзывы на Nordace и конкурентов | `nordace trustpilot`, `site:trustpilot.com nordace` |
| Amazon | отзывы на конкурентов, особенно 2–3★ (самые полезные: человек купил, но что-то не так) | `amazon convertible tote backpack reviews`, страница товара → отзывы |
| YouTube | обзоры Nordace и конкурентов; комментарии под обзорами | `nordace review`, `best travel tote 2026`, `personal item bag review` |
| TikTok | тренды, язык, форматы; комментарии | `nordace`, `personal item bag`, `travel tote hack` (часто недоступно автоматически) |
| Quora | вопросы «какую сумку выбрать» | `site:quora.com best tote bag for work and travel` |
| Блоги, СМИ | мнения экспертов, «лучшие сумки года», тренды | `best travel tote bags 2026 review`, `Wirecutter tote bag` |
| Facebook | комментарии под рекламой Nordace и конкурентов, группы путешественниц | автоматически почти недоступно: просить скриншоты у пользователя |

## Конкуренты (стартовый список, уточнять под продукт)
Béis, Calpak, Lo & Sons, Dagne Dover, Monos, Longchamp (Le Pliage), Bellroy, Baggallini, Travelon, Vera Bradley, Cuyana, Antler, Samsonite (дорожные тоуты), Kipling. Для антивор-позиционирования: Pacsafe, Travelon. Для дешёвых аналогов: Amazon-бренды (BAGSMART, Lovevook, MOSISO).

Что записывать по каждому объявлению конкурента: бренд, продукт, угол, хук (первая фраза или кадр), формат, оффер, дата начала показа (в Ad Library), ссылка. Объявление, которое крутится больше 30–60 дней, вероятно, прибыльное: его угол стоит изучить внимательнее.

## Рынки и язык
Nordace продаёт в нескольких странах. Для каждого целевого рынка:
- США, Канада, Австралия: Reddit, Amazon.com, YouTube.
- Великобритания: Mumsnet, Amazon.co.uk, Reddit (r/UKPersonalFinance для темы цены, r/CasualUK).
- Германия, Франция и т.д.: локальные форумы и Amazon на местном языке (`site:amazon.de Rucksack Tasche Rezension`), цитаты в оригинале + перевод.
- Отмечай рынок в каждой строке VOC, чтобы видеть различия.

## Как строить запросы
Комбинируй: **[продукт/категория] + [боль / ситуация / персона / сравнение]**.
- Боли: `shoulder pain`, `back hurts`, `can't find anything in my bag`, `too heavy`, `strap breaks`, `doesn't fit laptop`, `doesn't fit under seat`.
- Ситуации: `personal item`, `carry-on only`, `commute`, `business trip`, `airport`, `mom bag`, `work to gym`.
- Персоны: `over 50`, `nurse`, `teacher`, `flight attendant`, `solo female travel`.
- Сравнения: `vs`, `alternative to`, `dupe`, `worth it`, `regret buying`.
- Возражения: `worth the money`, `quality issues`, `returned`, `scam` (проверь и про Nordace: что пишут о доверии к бренду).

## Технические советы
- Поиск выдаёт ссылки: открывай страницы (fetch) и бери цитаты из самих тредов и отзывов, а не из сниппетов.
- Reddit: если страница не открывается, попробуй `old.reddit.com/...` или добавь `.json` в конец URL треда.
- YouTube-комментарии массово: если есть shell с сетью, `yt-dlp --skip-download --write-comments --extractor-args "youtube:max_comments=300" <url>` (скилл `yt-grab` умеет качать субтитры и комментарии).
- TikTok, Instagram, Facebook, Meta Ad Library: если не открываются, не трать время, попроси у пользователя скриншоты и отметь пробел.
- Записывай каждый использованный источник во вкладку «Источники», даже если из него взята одна цитата.

# Метрики: что это и как читать

Названия как в Ads Manager (английский интерфейс). В скобках: формула и как читать.

## Показ
| Метрика | Что это | Как читать |
|---|---|---|
| Amount spent | потрачено | база для всех решений: судить можно только при достаточном спенде |
| Impressions | показы | сколько раз объявление показано |
| Reach | охват | сколько уникальных людей видели |
| Frequency | частота = Impressions / Reach | сколько раз в среднем один человек видел. Растёт → аудитория выгорает |
| CPM | цена 1000 показов = Spend / Impressions × 1000 | сколько стоит внимание. Зависит от страны, сезона (Q4 дорого), аудитории, качества креатива |

## Видео
| Метрика | Что это | Как читать |
|---|---|---|
| 3-second video plays | досмотры до 3 секунд | база для hook rate |
| ThruPlays | досмотр до 15 секунд (или до конца, если видео короче 15 с) | база для hold rate |
| Video plays at 25% / 50% / 75% / 95% / 100% | досмотры до доли ролика | показывает, где именно уходят зрители |
| Video average play time | среднее время просмотра | сравнивай с длиной ролика |
| **Hook rate** | 3-second video plays / Impressions | цепляет ли начало. Отвечает за первые 1–3 секунды |
| **Hold rate** | ThruPlays / 3-second video plays | держит ли середина тех, кого зацепил хук |

## Клик
| Метрика | Что это | Как читать |
|---|---|---|
| Link clicks | клики по ссылке | интерес к продукту |
| CTR (link click-through rate) | Link clicks / Impressions | убеждает ли ролик перейти. Не путать с CTR (all), где считаются все клики, включая лайки и раскрытие текста |
| CPC (cost per link click) | Spend / Link clicks | цена перехода; зависит от CPM и CTR одновременно |
| Landing page views (LPV) | загрузки страницы после клика | |
| **LPV rate** | LPV / Link clicks | < 70–80%: сайт грузится медленно или клики случайные |

## Покупка
| Метрика | Что это | Как читать |
|---|---|---|
| Adds to cart (ATC) | добавления в корзину | промежуточный сигнал интереса |
| Checkouts initiated | начатые оформления | |
| Purchases | покупки | |
| Cost per purchase (CPA) | Spend / Purchases | при цели ROAS 1.0 CPA должен быть ≤ AOV |
| Purchases conversion value | выручка с покупок | |
| Purchase ROAS | Purchase value / Spend | главный KPI бонуса. 1.0 = окупили расход |
| **AOV** | Purchase value / Purchases | средний чек |
| **Click-to-purchase rate** | Purchases / Link clicks | конверсия сайта и оффера |

## Связи между метриками
- CPA = CPM / (1000 × CTR × click-to-purchase rate). Поэтому высокий CPM можно компенсировать высоким CTR или конверсией.
- ROAS = AOV / CPA. При AOV $80 и CPA $80 ROAS = 1.0.
- Hook rate × hold rate показывает, какая доля показов досмотрела до важной части ролика.

## Окно атрибуции
По умолчанию 7-day click, 1-day view. ROAS в Ads Manager зависит от окна: при 1-day click он ниже. Сравнивай только цифры с одинаковым окном и спрашивай, какое окно учитывается для бонуса.

## Набор колонок для скриншотов
Предложи пользователю один раз сохранить в Ads Manager пресет колонок (Columns → Customize columns → Save as preset), чтобы на любом скриншоте было всё нужное:

Delivery, Attribution setting, Amount spent, Impressions, Reach, Frequency, CPM, 3-second video plays, ThruPlays, Video plays at 25%, 50%, 75%, 95%, Video average play time, Link clicks, CTR (link click-through rate), CPC (cost per link click), Landing page views, Adds to cart, Checkouts initiated, Purchases, Cost per purchase, Purchases conversion value, Purchase ROAS.

Плюс две пользовательские метрики (Columns → Customize columns → Create custom metric):
- `Hook rate` = 3-second video plays / Impressions, формат процент
- `Hold rate` = ThruPlays / 3-second video plays, формат процент

Полезные срезы (Breakdown): Age, Gender, Country, Placement, Platform. По ним видно, кому на самом деле заходит креатив, и это напрямую возвращается в ресерч персон.
